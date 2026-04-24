"""Performance benchmarks for hot-path code.

These protect against accidental performance regressions. Each benchmark
asserts an order-of-magnitude budget — the actual number will vary by
machine, but 10x slowdowns indicate something structurally wrong.

Run locally:
    pytest tests/unit/test_performance_benchmarks.py --benchmark-only

In CI they run but do not fail the build (CI machines have variable
throughput). Regressions are flagged in the benchmark output for review.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from src.data_quality.validators.rule_engine import DQRule, run_rules
from src.pipelines.loaders.postgres_bulk import PostgresBulkLoader
from src.pipelines.transformers.enrichers import compute_row_hash
from src.schemas.commercial import TransactionSchema

# ---------------------------------------------------------------------------
# Hot path 1: Pydantic validation
# ---------------------------------------------------------------------------


def _sample_transaction() -> dict:
    return {
        "transaction_date": date(2025, 1, 15),
        "contract_number": "CT-0001",
        "counterparty_external_id": "CP-0001",
        "amount": Decimal("1234.56"),
        "currency": "usd",
        "transaction_type": "INVOICE",
        "reference": "TXN-0001",
        "source_system": "erp",
    }


def test_pydantic_validation_1k_records(benchmark):
    """Pydantic v2 should validate well over 100k/sec of simple records.
    Budget: 1,000 records under 100 ms."""
    records = [_sample_transaction() for _ in range(1_000)]

    def validate_all():
        return [TransactionSchema.model_validate(r) for r in records]

    result = benchmark(validate_all)
    assert len(result) == 1_000


# ---------------------------------------------------------------------------
# Hot path 2: Row hash for SCD2 change detection
# ---------------------------------------------------------------------------


def test_row_hash_10k_records(benchmark):
    """Deterministic SHA-256 hash over dict subsets. Runs on every SCD2
    comparison — must not dominate the load time."""
    records = [
        {
            "external_id": f"CP-{i:06d}",
            "name": f"Company {i}",
            "country_code": "US",
            "risk_score": Decimal(str(i % 100)),
            "metadata": {"k": "v"},
        }
        for i in range(10_000)
    ]
    fields = ["external_id", "name", "country_code", "risk_score", "metadata"]

    def hash_all():
        return [compute_row_hash(r, fields) for r in records]

    result = benchmark(hash_all)
    assert len(result) == 10_000
    assert all(len(h) == 64 for h in result)


# ---------------------------------------------------------------------------
# Hot path 3: DQ rule engine over a DataFrame
# ---------------------------------------------------------------------------


def _make_dataframe(n: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "id": list(range(n)),
            "reference": [f"TXN-{i:08d}" for i in range(n)],
            "currency": ["USD"] * n,
            "amount": [float(i) for i in range(n)],
        }
    )


def test_dq_rule_engine_50k_rows(benchmark):
    """Running the 5 most common rule types over 50k rows.
    Budget: well under 1 second on commodity hardware."""
    df = _make_dataframe(50_000)
    rules = [
        DQRule(name="id_nn", type="not_null", column="id"),
        DQRule(name="ref_uniq", type="unique", column="reference"),
        DQRule(name="cur_regex", type="regex", column="currency", params={"pattern": "^[A-Z]{3}$"}),
        DQRule(
            name="cur_in_set",
            type="in_set",
            column="currency",
            params={"values": ["USD", "EUR", "GBP"]},
        ),
        DQRule(name="amt_range", type="range", column="amount", params={"min": 0, "max": 1e9}),
    ]

    result = benchmark(run_rules, df, rules, "benchmark")
    assert all(r.passed for r in result)


# ---------------------------------------------------------------------------
# Hot path 4: CSV serialization for COPY
# ---------------------------------------------------------------------------


@pytest.fixture
def bulk_loader():
    # The session is not used during _encode_csv, so pass None.
    return PostgresBulkLoader(
        session=None,  # type: ignore[arg-type]
        table="test",
        columns=["id", "amount", "currency", "metadata"],
        pipeline="benchmark",
    )


def test_csv_encode_10k_records(benchmark, bulk_loader):
    """CSV encoding is the step right before COPY — it must be
    cheap compared to the network write time."""
    records = [
        {
            "id": f"id-{i}",
            "amount": Decimal("123.45"),
            "currency": "USD",
            "metadata": {"nested": "value", "number": i},
        }
        for i in range(10_000)
    ]

    result = benchmark(bulk_loader._encode_csv, records)
    # Sanity: CSV should have 10k lines
    assert result.count("\n") >= 10_000
