"""Tests for row-hash and enrichment helpers."""

from __future__ import annotations

from decimal import Decimal

from src.pipelines.transformers.enrichers import (
    compute_row_hash,
    enrich_commercial,
    risk_tier_from_score,
)


class TestRowHash:
    def test_deterministic(self):
        a = {"id": 1, "name": "foo"}
        assert compute_row_hash(a, ["id", "name"]) == compute_row_hash(a, ["id", "name"])

    def test_order_independent(self):
        a = {"id": 1, "name": "foo"}
        assert compute_row_hash(a, ["id", "name"]) == compute_row_hash(a, ["name", "id"])

    def test_different_for_different_content(self):
        a = compute_row_hash({"id": 1}, ["id"])
        b = compute_row_hash({"id": 2}, ["id"])
        assert a != b


class TestRiskTier:
    def test_tiers(self):
        assert risk_tier_from_score(None) == "UNKNOWN"
        assert risk_tier_from_score(Decimal("10")) == "LOW"
        assert risk_tier_from_score(Decimal("30")) == "MODERATE"
        assert risk_tier_from_score(Decimal("60")) == "HIGH"
        assert risk_tier_from_score(Decimal("90")) == "CRITICAL"


class TestEnrich:
    def test_adds_risk_tier_when_score_present(self):
        out = enrich_commercial({"risk_score": Decimal("80")})
        assert out["metadata"]["risk_tier"] == "CRITICAL"

    def test_does_not_mutate_input(self):
        src = {"risk_score": Decimal("40")}
        _ = enrich_commercial(src)
        assert "metadata" not in src
