"""Tests for the normalization pipeline stage."""
from __future__ import annotations

from datetime import date

from src.pipelines.transformers.normalizers import normalize_legal


def _valid_doc(doc_id: str = "1"):
    return {
        "document_date": date(2025, 1, 1),
        "source_system": "courts",
        "source_id": doc_id,
        "source_hash": "a" * 64,
        "document_type": "judgment",
        "title": "test",
        "jurisdiction": "US-NY",
    }


def test_all_valid_records_pass():
    result = normalize_legal(
        "document",
        [_valid_doc("1"), _valid_doc("2")],
        pipeline="t",
    )
    assert result.valid_count == 2
    assert result.rejected_count == 0


def test_invalid_records_go_to_rejected():
    bad = _valid_doc()
    bad["source_hash"] = "too-short"
    result = normalize_legal("document", [bad, _valid_doc("1")], pipeline="t")
    assert result.valid_count == 1
    assert result.rejected_count == 1
    assert result.rejected[0]["schema"] == "LegalDocumentSchema"


def test_rejection_rate_computation():
    result = normalize_legal(
        "document",
        [_valid_doc("1"), {"bad": "record"}],
        pipeline="t",
    )
    assert 0.4 < result.rejection_rate < 0.6
