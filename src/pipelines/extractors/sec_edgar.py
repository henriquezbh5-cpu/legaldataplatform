"""SEC EDGAR extractor — real source of U.S. corporate legal filings.

The SEC (Securities and Exchange Commission) publishes every public-company
filing (10-K annual reports, 10-Q quarterly, 8-K material events, DEF 14A
proxies, S-1 registrations, etc.) via a free JSON API.

Endpoints used:
    GET https://www.sec.gov/files/company_tickers.json
        → master list of ~10,000 public companies (CIK, ticker, name)

    GET https://data.sec.gov/submissions/CIK{cik:010d}.json
        → recent filings for a given CIK (Central Index Key)

SEC fair-use policy (https://www.sec.gov/developer):
    - No more than 10 requests per second
    - MUST identify yourself via User-Agent header with contact email
    - Cache whenever possible

This extractor:
    - Respects the 10 req/s limit via an asyncio.Semaphore + sleep
    - Streams filings in batches as `ExtractBatch` compatible with the rest
    - Maps filings to LegalDocumentSchema fields (document_type, title, etc.)
    - Computes deterministic source_hash for idempotent re-ingestion
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
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

SEC_BASE_URL = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_MAX_RPS = 8  # below the 10 rps limit for safety margin

# SEC filings taxonomy — maps form types to a higher-level document category
FORM_TO_TYPE: dict[str, str] = {
    "10-K": "ANNUAL_REPORT",
    "10-K/A": "ANNUAL_REPORT",
    "10-Q": "QUARTERLY_REPORT",
    "10-Q/A": "QUARTERLY_REPORT",
    "8-K": "MATERIAL_EVENT",
    "8-K/A": "MATERIAL_EVENT",
    "DEF 14A": "PROXY",
    "S-1": "REGISTRATION",
    "S-1/A": "REGISTRATION",
    "S-3": "REGISTRATION",
    "S-4": "REGISTRATION",
    "20-F": "FOREIGN_ANNUAL",
    "6-K": "FOREIGN_INTERIM",
    "424B": "PROSPECTUS",
    "SC 13D": "OWNERSHIP_DISCLOSURE",
    "SC 13G": "OWNERSHIP_DISCLOSURE",
    "4": "INSIDER_TRANSACTION",
    "3": "INSIDER_TRANSACTION",
    "5": "INSIDER_TRANSACTION",
    "N-CSR": "FUND_REPORT",
    "13F-HR": "FUND_HOLDINGS",
}


@dataclass
class SecEdgarConfig:
    user_agent: str  # REQUIRED: "App/1.0 (contact@example.com)"
    max_companies: int | None = 50  # None → all public companies
    form_types: list[str] | None = None  # filter: ["10-K", "10-Q", "8-K"]
    since_date: date | None = None  # only filings >= this date
    max_rps: int = DEFAULT_MAX_RPS
    batch_size: int = 100
    source_name: str = "sec_edgar"


class SecEdgarExtractor(Extractor):
    """Pulls real filings from the SEC EDGAR public API."""

    source_system = "sec_edgar"

    def __init__(self, config: SecEdgarConfig) -> None:
        if "@" not in config.user_agent:
            raise ValueError(
                "SEC requires a User-Agent with a contact email. "
                "Example: 'LegalDataPlatform/0.1 (contact@example.com)'"
            )
        self.config = config
        # Semaphore ensures max_rps concurrent requests; combined with sleep
        # gives a smooth rate of max_rps req/s.
        self._semaphore = asyncio.Semaphore(config.max_rps)
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

    async def extract(self) -> AsyncIterator[ExtractBatch]:
        async with httpx.AsyncClient(
            headers={"User-Agent": self.config.user_agent, "Accept": "application/json"},
            timeout=30.0,
        ) as client:
            # Step 1: get the list of companies
            tickers = await self._fetch_tickers(client)
            if self.config.max_companies:
                tickers = tickers[: self.config.max_companies]
            logger.info("sec_edgar.tickers_loaded", count=len(tickers))

            # Step 2: for each company, fetch recent filings and yield batches
            buffer: list[dict[str, Any]] = []
            for ticker_entry in tickers:
                cik = ticker_entry["cik_str"]
                filings = await self._fetch_company_filings(client, cik)
                for f in filings:
                    normalized = self._normalize(f, ticker_entry)
                    if normalized and self._passes_filters(normalized):
                        buffer.append(normalized)

                        if len(buffer) >= self.config.batch_size:
                            yield self._build_batch(buffer)
                            buffer = []

            if buffer:
                yield self._build_batch(buffer)

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Enforce max_rps by sleeping the minimum interval between requests."""
        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            interval = 1.0 / self.config.max_rps
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
    async def _get(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        await self._rate_limit()
        async with self._semaphore:
            response = await client.get(url)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "5"))
                logger.warning("sec_edgar.rate_limited", retry_after=retry_after, url=url)
                await asyncio.sleep(retry_after)
                raise httpx.HTTPError("Rate limited by SEC")
            response.raise_for_status()
            return response.json()

    async def _fetch_tickers(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Fetch the master list of public companies."""
        data = await self._get(client, SEC_TICKERS_URL)
        # Response shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        return list(data.values())

    async def _fetch_company_filings(
        self, client: httpx.AsyncClient, cik: int
    ) -> list[dict[str, Any]]:
        """Fetch recent filings for a single CIK, flattening the SEC response."""
        url = f"{SEC_BASE_URL}/submissions/CIK{cik:010d}.json"
        try:
            data = await self._get(client, url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("sec_edgar.cik_not_found", cik=cik)
                return []
            raise

        recent = data.get("filings", {}).get("recent", {})
        # The SEC returns parallel arrays (column-oriented). Zip into records.
        columns = [
            "accessionNumber",
            "filingDate",
            "reportDate",
            "form",
            "primaryDocument",
            "primaryDocDescription",
            "size",
        ]
        rows = []
        count = len(recent.get("accessionNumber", []))
        for i in range(count):
            row = {col: recent.get(col, [None] * count)[i] for col in columns}
            row["cik"] = cik
            row["company_name"] = data.get("name", "")
            rows.append(row)
        return rows

    def _normalize(
        self, filing: dict[str, Any], ticker_entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Map SEC filing to a LegalDocumentSchema-compatible record."""
        form = filing.get("form")
        filing_date_str = filing.get("filingDate")
        accession = filing.get("accessionNumber")

        if not (form and filing_date_str and accession):
            return None

        try:
            filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

        document_type = FORM_TO_TYPE.get(form, "OTHER_FILING")
        company_name = filing.get("company_name") or ticker_entry.get("title", "")
        ticker = ticker_entry.get("ticker", "")

        source_id = accession  # globally unique within SEC
        canonical = f"sec_edgar|{source_id}|{filing_date.isoformat()}".encode()
        source_hash = hashlib.sha256(canonical).hexdigest()

        # Build a stable URL to the filing for traceability
        accession_stripped = accession.replace("-", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{filing['cik']}/{accession_stripped}/{filing.get('primaryDocument', '')}"
        )

        return {
            "document_date": filing_date,
            "source_system": "sec_edgar",
            "source_id": source_id,
            "source_hash": source_hash,
            "document_type": document_type,
            "title": f"{company_name} ({ticker}) — {form} filing {filing_date}",
            "content": filing.get("primaryDocDescription"),
            "jurisdiction": "US-SEC",
            "tags": [form.lower(), ticker.lower() if ticker else "unknown"],
            "metadata": {
                "cik": filing["cik"],
                "ticker": ticker,
                "company_name": company_name,
                "form": form,
                "accession_number": accession,
                "report_date": filing.get("reportDate"),
                "filing_size_bytes": filing.get("size"),
                "filing_url": filing_url,
            },
        }

    def _passes_filters(self, record: dict[str, Any]) -> bool:
        if self.config.since_date and record["document_date"] < self.config.since_date:
            return False
        if self.config.form_types:
            form = record["metadata"].get("form")
            if form not in self.config.form_types:
                return False
        return True

    def _build_batch(self, records: list[dict[str, Any]]) -> ExtractBatch:
        batch = ExtractBatch.new(
            source_system="sec_edgar",
            source_name=self.config.source_name,
            records=records,
            attributes={"api": "data.sec.gov/submissions"},
        )
        records_extracted.labels(source="sec_edgar", pipeline=self.config.source_name).inc(
            batch.size
        )
        logger.info("sec_edgar.batch_ready", batch_id=batch.batch_id, size=batch.size)
        return batch
