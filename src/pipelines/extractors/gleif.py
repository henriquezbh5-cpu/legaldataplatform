"""GLEIF extractor — real source of Legal Entity Identifiers.

GLEIF (Global Legal Entity Identifier Foundation) maintains the global
registry of LEI codes — 20-character alphanumeric identifiers assigned to
every legal entity that participates in a financial transaction.

The LEI is mandated by regulators worldwide (EU MiFID II, US Dodd-Frank,
EMIR, etc.) so this is a primary reference data source for any legal /
commercial platform.

Endpoints used:
    GET https://api.gleif.org/api/v1/lei-records
        → paginated list of LEI records, with rich filter support

Public API, no API key required. Rate limit: soft, recommended to stay
under ~60 req/min per IP.

This extractor:
    - Paginates the JSON:API response (links.next, meta.pagination)
    - Maps LEI records to CounterpartySchema-compatible records
    - Enriches counterparties with jurisdiction (LEI is ISO-3166 country-aware)
    - Computes deterministic hash for idempotent UPSERT
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.observability import get_logger, records_extracted
from src.pipelines.extractors.base import ExtractBatch, Extractor

logger = get_logger(__name__)

GLEIF_API_BASE = "https://api.gleif.org/api/v1"
DEFAULT_PAGE_SIZE = 200  # max supported by the API


@dataclass
class GleifConfig:
    country_code: str | None = None  # ISO-3166 alpha-2: "US", "ES", "DE"
    entity_status: str | None = "ACTIVE"  # ACTIVE | INACTIVE | NULL (all)
    max_pages: int | None = 10  # None = unlimited
    page_size: int = DEFAULT_PAGE_SIZE
    rate_limit_rps: float = 1.0  # conservative under GLEIF's limits
    source_name: str = "gleif"


class GleifExtractor(Extractor):
    """Pulls Legal Entity Identifiers from GLEIF's public registry."""

    source_system = "gleif"

    def __init__(self, config: GleifConfig | None = None) -> None:
        self.config = config or GleifConfig()
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

    async def extract(self) -> AsyncIterator[ExtractBatch]:
        async with httpx.AsyncClient(
            base_url=GLEIF_API_BASE,
            headers={
                "Accept": "application/vnd.api+json",
                "User-Agent": "LegalDataPlatform/0.1",
            },
            timeout=30.0,
        ) as client:
            page_size = self.config.page_size
            page_number = 1
            pages_fetched = 0

            params: dict[str, Any] = {"page[size]": page_size, "page[number]": page_number}
            if self.config.country_code:
                params["filter[entity.legalAddress.country]"] = self.config.country_code
            if self.config.entity_status:
                params["filter[entity.status]"] = self.config.entity_status

            while True:
                if self.config.max_pages and pages_fetched >= self.config.max_pages:
                    logger.info("gleif.max_pages_reached", pages=pages_fetched)
                    break

                params["page[number]"] = page_number
                payload = await self._get(client, "/lei-records", params)

                records = payload.get("data", [])
                if not records:
                    logger.info("gleif.no_more_records")
                    break

                normalized = [self._normalize(r) for r in records]
                normalized = [r for r in normalized if r is not None]

                batch = ExtractBatch.new(
                    source_system="gleif",
                    source_name=self.config.source_name,
                    records=normalized,
                    attributes={"page": page_number, "country": self.config.country_code},
                )
                records_extracted.labels(source="gleif", pipeline=self.config.source_name).inc(
                    batch.size
                )
                logger.info(
                    "gleif.batch_ready",
                    batch_id=batch.batch_id,
                    size=batch.size,
                    page=page_number,
                )
                yield batch

                meta = payload.get("meta", {}).get("pagination", {})
                total_pages = meta.get("lastPage") or meta.get("total_pages")
                if total_pages and page_number >= total_pages:
                    break

                page_number += 1
                pages_fetched += 1

    async def _rate_limit(self) -> None:
        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            interval = 1.0 / self.config.rate_limit_rps
            elapsed = now - self._last_request_time
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            self._last_request_time = asyncio.get_event_loop().time()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _get(
        self, client: httpx.AsyncClient, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        await self._rate_limit()
        response = await client.get(path, params=params)
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "5"))
            logger.warning("gleif.rate_limited", retry_after=retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.HTTPError("Rate limited by GLEIF")
        response.raise_for_status()
        return response.json()

    def _normalize(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Map a GLEIF LEI record into CounterpartySchema-compatible shape."""
        lei = record.get("id")
        attr = record.get("attributes", {})
        entity = attr.get("entity", {})

        if not (lei and entity):
            return None

        legal_name = (entity.get("legalName") or {}).get("name", "")
        legal_address = entity.get("legalAddress", {}) or {}
        country_code = legal_address.get("country", "")

        if not (legal_name and country_code):
            return None

        # Deterministic hash for SCD2 change detection
        canonical = f"gleif|{lei}|{legal_name}|{country_code}".encode()
        row_hash = hashlib.sha256(canonical).hexdigest()

        return {
            "external_id": f"LEI-{lei}",
            "name": legal_name,
            "tax_id": lei,  # LEI is the global identifier
            "country_code": country_code.upper(),
            "risk_score": None,  # GLEIF doesn't provide this
            "metadata": {
                "lei": lei,
                "status": entity.get("status"),
                "legal_form": (entity.get("legalForm") or {}).get("id"),
                "legal_jurisdiction": entity.get("jurisdiction"),
                "registration_initial_date": (attr.get("registration") or {}).get(
                    "initialRegistrationDate"
                ),
                "registration_last_update": (attr.get("registration") or {}).get("lastUpdateDate"),
                "bic": entity.get("bic"),
                "mic": entity.get("mic"),
                "source_hash": row_hash,
            },
        }
