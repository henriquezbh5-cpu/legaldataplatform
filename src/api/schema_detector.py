"""Detect which target schema a CSV maps to, by header similarity.

The platform exposes 3 ingestion targets today:
    - legal_documents      (the legal-ingestion-flow)
    - counterparties       (the commercial flow, partial)
    - transactions         (the commercial flow, partial)

Given the headers of an uploaded CSV, this module returns the best match
along with a confidence score. If no match is good enough, the API can
fall back to a manual mapping UI (out of scope for v0).
"""
from __future__ import annotations

from dataclasses import dataclass


# Canonical headers (and synonyms) per target. Synonyms cover common
# variations users tend to send.
KNOWN_SCHEMAS: dict[str, set[str]] = {
    "legal_documents": {
        "doc_id", "source_id", "document_id", "id",
        "date", "document_date", "filing_date",
        "source_system", "source",
        "type", "document_type", "form",
        "title", "name",
        "content", "body", "description",
        "jurisdiction", "country",
        "tags",
    },
    "counterparties": {
        "external_id", "counterparty_id", "id",
        "name", "legal_name", "company_name",
        "tax_id", "ein", "vat", "lei",
        "country_code", "country",
        "risk_score", "risk", "score",
    },
    "transactions": {
        "transaction_date", "date", "txn_date",
        "contract_number", "contract_id",
        "counterparty_external_id", "counterparty_id", "external_id",
        "amount", "value",
        "currency", "ccy",
        "transaction_type", "type", "txn_type",
        "reference", "ref", "txn_ref",
        "source_system", "source",
    },
}


@dataclass
class SchemaMatch:
    schema: str
    score: float                  # 0..1 — fraction of input headers we recognize
    matched_headers: list[str]    # headers that were recognized
    unknown_headers: list[str]    # headers that aren't in any known schema

    @property
    def is_confident(self) -> bool:
        """A confident match needs >=50% of input headers recognized."""
        return self.score >= 0.5


def detect_schema(headers: list[str]) -> SchemaMatch:
    """Return the best schema match for the given headers."""
    if not headers:
        return SchemaMatch(schema="unknown", score=0.0, matched_headers=[], unknown_headers=[])

    normalized = [_normalize(h) for h in headers]

    best_schema = "unknown"
    best_score = 0.0
    best_matched: list[str] = []

    for schema_name, vocabulary in KNOWN_SCHEMAS.items():
        matched = [h for h, n in zip(headers, normalized, strict=False) if n in vocabulary]
        score = len(matched) / len(headers)
        if score > best_score:
            best_score = score
            best_schema = schema_name
            best_matched = matched

    matched_set = set(best_matched)
    unknown = [h for h in headers if h not in matched_set]

    return SchemaMatch(
        schema=best_schema if best_score > 0 else "unknown",
        score=best_score,
        matched_headers=best_matched,
        unknown_headers=unknown,
    )


def _normalize(header: str) -> str:
    """Lowercase + strip + replace separators so 'Document ID' == 'document_id'."""
    return header.strip().lower().replace(" ", "_").replace("-", "_")
