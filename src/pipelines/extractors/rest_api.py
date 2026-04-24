"""REST API extractor with pagination, retry, and rate limit awareness.

Supports:
- Cursor/offset/page-based pagination (configurable)
- Exponential backoff via tenacity
- Respects Retry-After header on 429 responses
- Extracts nested data via JSON path
- Emits structured logs for every request
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.observability import get_logger, records_extracted
from src.pipelines.extractors.base import ExtractBatch, Extractor

logger = get_logger(__name__)

PaginationMode = Literal["offset", "cursor", "page"]


@dataclass
class RestAPIConfig:
    base_url: str
    endpoint: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    data_path: str = "data"              # JSON path to list of records
    next_cursor_path: str | None = None  # JSON path to next cursor
    pagination_mode: PaginationMode = "offset"
    page_size: int = 100
    max_pages: int | None = None         # None = unlimited
    timeout_seconds: float = 30.0
    source_system: str = "rest_api"
    source_name: str = "default"


class RestAPIExtractor(Extractor):
    """Generic REST API extractor.

    Designed for legal-data APIs that typically return paginated JSON.
    """

    def __init__(self, config: RestAPIConfig) -> None:
        self.config = config
        self.source_system = config.source_system

    async def extract(self) -> AsyncIterator[ExtractBatch]:
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=self.config.headers,
            timeout=self.config.timeout_seconds,
        ) as client:
            page_count = 0
            cursor: Any = None
            offset = 0

            while True:
                if self.config.max_pages and page_count >= self.config.max_pages:
                    logger.info("rest_extractor.max_pages_reached", pages=page_count)
                    break

                params = dict(self.config.query_params)
                if self.config.pagination_mode == "offset":
                    params["limit"] = self.config.page_size
                    params["offset"] = offset
                elif self.config.pagination_mode == "page":
                    params["per_page"] = self.config.page_size
                    params["page"] = page_count + 1
                elif self.config.pagination_mode == "cursor" and cursor:
                    params["cursor"] = cursor

                response = await self._request_with_retry(client, params)
                payload = response.json()
                records = self._extract_path(payload, self.config.data_path)

                if not records:
                    logger.info("rest_extractor.no_more_records")
                    break

                batch = ExtractBatch.new(
                    source_system=self.config.source_system,
                    source_name=self.config.source_name,
                    records=records,
                    attributes={
                        "endpoint": self.config.endpoint,
                        "page": page_count + 1,
                    },
                )
                records_extracted.labels(
                    source=self.config.source_system,
                    pipeline=self.config.source_name,
                ).inc(batch.size)

                logger.info(
                    "rest_extractor.batch_ready",
                    batch_id=batch.batch_id,
                    size=batch.size,
                    page=page_count + 1,
                )
                yield batch

                page_count += 1
                offset += self.config.page_size

                if self.config.pagination_mode == "cursor":
                    cursor = self._extract_path(payload, self.config.next_cursor_path or "")
                    if not cursor:
                        break

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _request_with_retry(
        self, client: httpx.AsyncClient, params: dict[str, Any]
    ) -> httpx.Response:
        response = await client.request(
            method=self.config.method,
            url=self.config.endpoint,
            params=params,
        )

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "5"))
            logger.warning("rest_extractor.rate_limited", retry_after=retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.HTTPError("Rate limited")

        response.raise_for_status()
        return response

    @staticmethod
    def _extract_path(payload: Any, path: str) -> Any:
        """Navigate a dot-separated JSON path, returning [] if not found."""
        if not path:
            return payload
        node: Any = payload
        for key in path.split("."):
            if isinstance(node, dict):
                node = node.get(key)
            else:
                return []
        return node or []
