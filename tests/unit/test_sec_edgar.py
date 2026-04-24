"""Unit tests for the SEC EDGAR extractor.

Uses httpx.MockTransport to avoid hitting the real SEC API during CI.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from src.pipelines.extractors.sec_edgar import (
    FORM_TO_TYPE,
    SecEdgarConfig,
    SecEdgarExtractor,
)

pytestmark = pytest.mark.asyncio


FAKE_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}

FAKE_SUBMISSIONS_AAPL = {
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-24-000123", "0000320193-24-000089"],
            "filingDate": ["2024-11-01", "2024-08-02"],
            "reportDate": ["2024-09-28", "2024-06-29"],
            "form": ["10-K", "10-Q"],
            "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm"],
            "primaryDocDescription": ["Annual Report", "Quarterly Report"],
            "size": [12_000_000, 8_500_000],
        }
    },
}

FAKE_SUBMISSIONS_MSFT = {
    "name": "MICROSOFT CORP",
    "filings": {
        "recent": {
            "accessionNumber": ["0000789019-24-000345"],
            "filingDate": ["2024-10-24"],
            "reportDate": ["2024-09-30"],
            "form": ["10-Q"],
            "primaryDocument": ["msft-20240930.htm"],
            "primaryDocDescription": ["Quarterly Report"],
            "size": [9_200_000],
        }
    },
}


def make_mock_transport() -> httpx.MockTransport:
    """Build a transport that returns canned SEC responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "company_tickers.json" in url:
            return httpx.Response(200, json=FAKE_TICKERS)
        if "CIK0000320193.json" in url:
            return httpx.Response(200, json=FAKE_SUBMISSIONS_AAPL)
        if "CIK0000789019.json" in url:
            return httpx.Response(200, json=FAKE_SUBMISSIONS_MSFT)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def config() -> SecEdgarConfig:
    return SecEdgarConfig(
        user_agent="Test/1.0 (test@example.com)",
        max_companies=2,
        max_rps=100,  # high for tests to not add latency
        batch_size=10,
        source_name="sec_edgar_test",
    )


async def test_extractor_yields_normalized_filings(config, monkeypatch):
    """Real end-to-end with mocked HTTP."""
    # Patch httpx.AsyncClient to use our mock transport
    transport = make_mock_transport()

    original_client = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("src.pipelines.extractors.sec_edgar.httpx.AsyncClient", patched_client)

    extractor = SecEdgarExtractor(config)
    batches = []
    async for b in extractor.extract():
        batches.append(b)

    all_records = [r for b in batches for r in b.records]
    assert len(all_records) == 3  # 2 AAPL + 1 MSFT

    aapl_10k = next(r for r in all_records if r["metadata"]["form"] == "10-K")
    assert aapl_10k["source_system"] == "sec_edgar"
    assert aapl_10k["document_type"] == "ANNUAL_REPORT"
    assert aapl_10k["jurisdiction"] == "US-SEC"
    assert aapl_10k["document_date"] == date(2024, 11, 1)
    assert aapl_10k["metadata"]["ticker"] == "AAPL"
    assert aapl_10k["metadata"]["cik"] == 320193
    assert len(aapl_10k["source_hash"]) == 64  # SHA-256 hex
    assert "aapl" in aapl_10k["tags"]
    assert "10-k" in aapl_10k["tags"]


def test_config_rejects_user_agent_without_email():
    with pytest.raises(ValueError, match="contact email"):
        SecEdgarExtractor(SecEdgarConfig(user_agent="NoEmailHere/1.0", max_companies=1))


def test_form_to_type_mapping_covers_major_forms():
    assert FORM_TO_TYPE["10-K"] == "ANNUAL_REPORT"
    assert FORM_TO_TYPE["10-Q"] == "QUARTERLY_REPORT"
    assert FORM_TO_TYPE["8-K"] == "MATERIAL_EVENT"
    assert FORM_TO_TYPE["DEF 14A"] == "PROXY"


async def test_form_type_filter(config, monkeypatch):
    """Only 10-K filings should come through when the filter is set."""
    config.form_types = ["10-K"]

    transport = make_mock_transport()
    original_client = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("src.pipelines.extractors.sec_edgar.httpx.AsyncClient", patched_client)

    extractor = SecEdgarExtractor(config)
    all_records = []
    async for b in extractor.extract():
        all_records.extend(b.records)

    assert len(all_records) == 1
    assert all_records[0]["metadata"]["form"] == "10-K"


async def test_since_date_filter(config, monkeypatch):
    """Filings older than since_date should be excluded."""
    config.since_date = date(2024, 9, 1)

    transport = make_mock_transport()
    original_client = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("src.pipelines.extractors.sec_edgar.httpx.AsyncClient", patched_client)

    extractor = SecEdgarExtractor(config)
    all_records = []
    async for b in extractor.extract():
        all_records.extend(b.records)

    # AAPL 10-K (2024-11-01) and MSFT 10-Q (2024-10-24) pass; AAPL 10-Q (2024-08-02) does not
    assert len(all_records) == 2
    dates = {r["document_date"] for r in all_records}
    assert date(2024, 8, 2) not in dates


async def test_deterministic_source_hash(config, monkeypatch):
    """Same filing should produce the same hash across runs — enables idempotent UPSERT."""
    transport = make_mock_transport()
    original_client = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("src.pipelines.extractors.sec_edgar.httpx.AsyncClient", patched_client)

    async def collect_hashes() -> list[str]:
        extractor = SecEdgarExtractor(config)
        hashes = []
        async for b in extractor.extract():
            hashes.extend(r["source_hash"] for r in b.records)
        return hashes

    first = await collect_hashes()
    second = await collect_hashes()
    assert first == second
    assert len(set(first)) == len(first)  # all distinct
