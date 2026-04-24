"""Tests for the declarative DQ rule engine."""
from __future__ import annotations

import polars as pl
import pytest

from src.data_quality.validators.rule_engine import (
    DQRule,
    assert_no_errors,
    run_rules,
)


def _df():
    return pl.DataFrame({
        "id":        [1, 2, 3, 4, 5],
        "email":     ["a@b.co", "no-at-sign", "c@d.co", "e@f.co", None],
        "status":    ["ACTIVE", "INACTIVE", "ACTIVE", "PENDING", "ACTIVE"],
        "amount":    [100, -5, 50, 200, 999999999],
    })


def test_not_null_passes_when_no_nulls():
    rules = [DQRule(name="id_nn", type="not_null", column="id")]
    [r] = run_rules(_df(), rules)
    assert r.passed


def test_not_null_fails_with_nulls():
    rules = [DQRule(name="email_nn", type="not_null", column="email")]
    [r] = run_rules(_df(), rules)
    assert not r.passed
    assert r.failed_count == 1


def test_unique_flags_duplicates():
    df = pl.DataFrame({"x": [1, 1, 2]})
    rules = [DQRule(name="x_uniq", type="unique", column="x")]
    [r] = run_rules(df, rules)
    assert not r.passed
    assert r.failed_count == 1


def test_regex_fails_for_bad_email():
    rules = [DQRule(
        name="email_fmt", type="regex", column="email",
        params={"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
    )]
    [r] = run_rules(_df(), rules)
    assert not r.passed
    # "no-at-sign" fails; None passes (regex check skips nulls)
    assert r.failed_count == 1


def test_in_set_rule():
    rules = [DQRule(
        name="status_set", type="in_set", column="status",
        params={"values": ["ACTIVE", "INACTIVE"]},
    )]
    [r] = run_rules(_df(), rules)
    assert not r.passed
    assert r.failed_count == 1   # "PENDING"


def test_range_rule_catches_outliers():
    rules = [DQRule(
        name="amount_range", type="range", column="amount",
        params={"min": 0, "max": 1_000_000},
    )]
    [r] = run_rules(_df(), rules)
    assert not r.passed
    # -5 and 999999999
    assert r.failed_count == 2


def test_row_count_bounds():
    rules = [DQRule(
        name="rows", type="row_count_range",
        params={"min": 10, "max": 100}, severity="error",
    )]
    [r] = run_rules(_df(), rules)
    assert not r.passed


def test_assert_no_errors_raises_on_error_severity():
    rules = [DQRule(name="a", type="not_null", column="email", severity="error")]
    results = run_rules(_df(), rules)
    with pytest.raises(AssertionError):
        assert_no_errors(results)


def test_assert_no_errors_skips_warnings():
    rules = [DQRule(name="a", type="not_null", column="email", severity="warning")]
    results = run_rules(_df(), rules)
    assert_no_errors(results)  # should not raise
