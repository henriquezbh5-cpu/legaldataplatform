"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def sample_legal_docs() -> AsyncIterator[list[dict]]:
    yield [
        {
            "doc_id": "DOC-1",
            "date": "2025-01-15",
            "source_system": "api:courts",
            "type": "judgment",
            "title": "ACME v. Foo Corp.",
            "content": "Judgment in favor of plaintiff.",
            "jurisdiction": "US-NY",
        },
        {
            "doc_id": "DOC-2",
            "date": "2025-01-16",
            "source_system": "api:registry",
            "type": "REGULATION",
            "title": "Data Protection Act Amendment",
            "content": "New section on pseudonymization.",
            "jurisdiction": "UK",
        },
    ]
