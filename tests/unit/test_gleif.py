"""Unit tests for the GLEIF extractor.

Uses httpx.MockTransport to avoid hitting the real GLEIF API during CI.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.pipelines.extractors.gleif import GleifConfig, GleifExtractor

pytestmark = pytest.mark.asyncio


FAKE_GLEIF_RESPONSE_PAGE_1 = {
    "meta": {
        "pagination": {
            "currentPage": 1,
            "perPage": 2,
            "from": 1,
            "to": 2,
            "total": 3,
            "lastPage": 2,
        }
    },
    "data": [
        {
            "id": "HWUPKR0MPOU8FGXBT394",
            "type": "lei-records",
            "attributes": {
                "lei": "HWUPKR0MPOU8FGXBT394",
                "entity": {
                    "legalName": {"name": "APPLE INC."},
                    "legalAddress": {"country": "US", "city": "Cupertino"},
                    "status": "ACTIVE",
                    "legalForm": {"id": "XTIQ"},
                    "jurisdiction": "US-CA",
                },
                "registration": {
                    "initialRegistrationDate": "2012-06-06",
                    "lastUpdateDate": "2024-03-15",
                },
            },
        },
        {
            "id": "INR2EJN1ERAN0W5ZP974",
            "type": "lei-records",
            "attributes": {
                "lei": "INR2EJN1ERAN0W5ZP974",
                "entity": {
                    "legalName": {"name": "MICROSOFT CORPORATION"},
                    "legalAddress": {"country": "US", "city": "Redmond"},
                    "status": "ACTIVE",
                    "legalForm": {"id": "XTIQ"},
                },
                "registration": {
                    "initialRegistrationDate": "2012-07-25",
                    "lastUpdateDate": "2024-01-12",
                },
            },
        },
    ],
}

FAKE_GLEIF_RESPONSE_PAGE_2 = {
    "meta": {
        "pagination": {
            "currentPage": 2,
            "perPage": 2,
            "from": 3,
            "to": 3,
            "total": 3,
            "lastPage": 2,
        }
    },
    "data": [
        {
            "id": "5493007B4QEKJ5WIB869",
            "type": "lei-records",
            "attributes": {
                "lei": "5493007B4QEKJ5WIB869",
                "entity": {
                    "legalName": {"name": "GOOGLE LLC"},
                    "legalAddress": {"country": "US"},
                    "status": "ACTIVE",
                },
                "registration": {"initialRegistrationDate": "2013-08-12"},
            },
        },
    ],
}


def make_mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page[number]")
        if page == "1":
            return httpx.Response(200, json=FAKE_GLEIF_RESPONSE_PAGE_1)
        if page == "2":
            return httpx.Response(200, json=FAKE_GLEIF_RESPONSE_PAGE_2)
        return httpx.Response(200, json={"data": [], "meta": {"pagination": {"lastPage": 2}}})

    return httpx.MockTransport(handler)


def patch_client(monkeypatch) -> None:
    transport = make_mock_transport()
    original = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr("src.pipelines.extractors.gleif.httpx.AsyncClient", patched)


async def test_extractor_paginates_and_normalizes(monkeypatch):
    patch_client(monkeypatch)

    extractor = GleifExtractor(
        GleifConfig(
            country_code="US",
            max_pages=5,
            page_size=2,
            rate_limit_rps=1000,
        )
    )
    all_records = []
    async for batch in extractor.extract():
        all_records.extend(batch.records)

    assert len(all_records) == 3

    apple = next(r for r in all_records if r["name"] == "APPLE INC.")
    assert apple["external_id"] == "LEI-HWUPKR0MPOU8FGXBT394"
    assert apple["tax_id"] == "HWUPKR0MPOU8FGXBT394"
    assert apple["country_code"] == "US"
    assert apple["metadata"]["lei"] == "HWUPKR0MPOU8FGXBT394"
    assert apple["metadata"]["status"] == "ACTIVE"
    assert len(apple["metadata"]["source_hash"]) == 64


async def test_extractor_respects_max_pages(monkeypatch):
    patch_client(monkeypatch)

    extractor = GleifExtractor(
        GleifConfig(
            country_code="US",
            max_pages=1,
            page_size=2,
            rate_limit_rps=1000,
        )
    )
    records = []
    async for batch in extractor.extract():
        records.extend(batch.records)

    assert len(records) == 2  # only page 1


async def test_extractor_skips_incomplete_records(monkeypatch):
    """Records without a legalName or country should be dropped."""
    incomplete = {
        "meta": {"pagination": {"lastPage": 1}},
        "data": [
            {
                "id": "NOID1234567890",
                "attributes": {"entity": {"legalAddress": {"country": "US"}}},
                # missing legalName
            },
            {
                "id": "NOCOUNTRY1234567",
                "attributes": {"entity": {"legalName": {"name": "NO COUNTRY LTD"}}},
                # missing country
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr("src.pipelines.extractors.gleif.httpx.AsyncClient", patched)

    extractor = GleifExtractor(GleifConfig(max_pages=1, rate_limit_rps=1000))
    records = []
    async for batch in extractor.extract():
        records.extend(batch.records)

    assert records == []  # both filtered out


async def test_deterministic_source_hash(monkeypatch):
    patch_client(monkeypatch)

    async def collect() -> list[str]:
        extractor = GleifExtractor(GleifConfig(max_pages=5, rate_limit_rps=1000))
        hashes = []
        async for b in extractor.extract():
            hashes.extend(r["metadata"]["source_hash"] for r in b.records)
        return hashes

    first = await collect()
    second = await collect()
    assert first == second
    assert len(set(first)) == len(first)
