"""Enrichers: derive additional fields from normalized records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any


def compute_row_hash(record: dict[str, Any], fields: list[str]) -> str:
    """Deterministic SHA-256 over selected fields.

    Used for:
    - Change detection in SCD2 loads
    - Idempotency keys in staging
    - Duplicate detection
    """
    subset = {k: record.get(k) for k in sorted(fields)}
    canonical = json.dumps(subset, default=_json_default, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def risk_tier_from_score(score: Decimal | None) -> str:
    """Bucket risk scores into tiers for reporting."""
    if score is None:
        return "UNKNOWN"
    if score < 25:
        return "LOW"
    if score < 50:
        return "MODERATE"
    if score < 75:
        return "HIGH"
    return "CRITICAL"


def enrich_commercial(record: dict[str, Any]) -> dict[str, Any]:
    """Add computed fields to a commercial record without mutating the input."""
    enriched = dict(record)
    if "risk_score" in enriched:
        enriched.setdefault("metadata", {})
        enriched["metadata"]["risk_tier"] = risk_tier_from_score(enriched.get("risk_score"))
    return enriched
