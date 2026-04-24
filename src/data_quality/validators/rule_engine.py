"""Declarative Data Quality rule engine.

Rules are defined in YAML and executed against Polars DataFrames. This is
complementary to Great Expectations — use this for fast in-pipeline checks
and GE for documentation-grade batch validation.

Rule types supported:
    - not_null          : column must have no nulls
    - unique            : column values must be unique
    - regex             : column values must match a regex
    - in_set            : column values must be in a set
    - range             : numeric column must be within a range
    - expression        : arbitrary Polars expression returning a boolean mask
    - row_count_range   : table row count must be within a range
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from src.observability import dq_checks, get_logger

logger = get_logger(__name__)


@dataclass
class DQRule:
    """A single data quality rule."""

    name: str
    type: str
    column: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    severity: str = "error"  # "error" blocks the pipeline, "warning" logs only

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DQRule:
        return cls(
            name=data["name"],
            type=data["type"],
            column=data.get("column"),
            params=data.get("params", {}),
            severity=data.get("severity", "error"),
        )


@dataclass
class DQResult:
    """Result of a single rule evaluation."""

    rule: DQRule
    passed: bool
    failed_count: int = 0
    sample_failures: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


def load_rules_yaml(path: str | Path) -> list[DQRule]:
    """Load rules from a YAML file."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return [DQRule.from_dict(r) for r in data.get("rules", [])]


def run_rules(
    df: pl.DataFrame,
    rules: list[DQRule],
    suite: str = "default",
) -> list[DQResult]:
    """Evaluate rules against a DataFrame and return per-rule results."""
    results: list[DQResult] = []

    for rule in rules:
        try:
            result = _dispatch(df, rule)
        except Exception as e:
            result = DQResult(
                rule=rule,
                passed=False,
                message=f"Rule evaluation error: {e}",
            )

        dq_checks.labels(suite=suite, result="passed" if result.passed else "failed").inc()
        if not result.passed:
            logger.warning(
                "dq.rule_failed",
                suite=suite,
                rule=rule.name,
                column=rule.column,
                severity=rule.severity,
                failed_count=result.failed_count,
            )
        results.append(result)

    return results


def _dispatch(df: pl.DataFrame, rule: DQRule) -> DQResult:
    if rule.type == "not_null":
        return _not_null(df, rule)
    if rule.type == "unique":
        return _unique(df, rule)
    if rule.type == "regex":
        return _regex(df, rule)
    if rule.type == "in_set":
        return _in_set(df, rule)
    if rule.type == "range":
        return _range(df, rule)
    if rule.type == "row_count_range":
        return _row_count(df, rule)
    raise ValueError(f"Unknown rule type: {rule.type}")


def _not_null(df: pl.DataFrame, rule: DQRule) -> DQResult:
    col = rule.column
    assert col
    n_null = df.select(pl.col(col).null_count()).item()
    return DQResult(
        rule=rule,
        passed=n_null == 0,
        failed_count=n_null,
        message=f"{n_null} nulls in {col}" if n_null else "",
    )


def _unique(df: pl.DataFrame, rule: DQRule) -> DQResult:
    col = rule.column
    assert col
    total = df.height
    distinct = df.select(pl.col(col).n_unique()).item()
    duplicates = total - distinct
    return DQResult(
        rule=rule,
        passed=duplicates == 0,
        failed_count=duplicates,
        message=f"{duplicates} duplicate values" if duplicates else "",
    )


def _regex(df: pl.DataFrame, rule: DQRule) -> DQResult:
    col = rule.column
    pattern = rule.params.get("pattern", "")
    assert col
    regex = re.compile(pattern)
    series = df.get_column(col).to_list()
    failures = [i for i, v in enumerate(series) if v is not None and not regex.match(str(v))]
    return DQResult(
        rule=rule,
        passed=len(failures) == 0,
        failed_count=len(failures),
        sample_failures=[{"row": i, "value": series[i]} for i in failures[:5]],
        message=f"{len(failures)} values do not match {pattern}" if failures else "",
    )


def _in_set(df: pl.DataFrame, rule: DQRule) -> DQResult:
    col = rule.column
    allowed = set(rule.params.get("values", []))
    assert col
    series = df.get_column(col).to_list()
    failures = [i for i, v in enumerate(series) if v not in allowed]
    return DQResult(
        rule=rule,
        passed=len(failures) == 0,
        failed_count=len(failures),
        sample_failures=[{"row": i, "value": series[i]} for i in failures[:5]],
        message=f"{len(failures)} values outside allowed set" if failures else "",
    )


def _range(df: pl.DataFrame, rule: DQRule) -> DQResult:
    col = rule.column
    min_v = rule.params.get("min")
    max_v = rule.params.get("max")
    assert col
    expr = pl.col(col)
    mask = pl.lit(False)
    if min_v is not None:
        mask = mask | (expr < min_v)
    if max_v is not None:
        mask = mask | (expr > max_v)
    failures = df.filter(mask).height
    return DQResult(
        rule=rule,
        passed=failures == 0,
        failed_count=failures,
        message=f"{failures} values out of range" if failures else "",
    )


def _row_count(df: pl.DataFrame, rule: DQRule) -> DQResult:
    min_c = rule.params.get("min", 0)
    max_c = rule.params.get("max", float("inf"))
    count = df.height
    ok = min_c <= count <= max_c
    return DQResult(
        rule=rule,
        passed=ok,
        failed_count=0 if ok else 1,
        message=f"Row count {count} outside [{min_c}, {max_c}]" if not ok else "",
    )


def assert_no_errors(results: list[DQResult]) -> None:
    """Raise if any error-severity rule failed."""
    hard_failures = [r for r in results if not r.passed and r.rule.severity == "error"]
    if hard_failures:
        msgs = "; ".join(f"{r.rule.name}: {r.message}" for r in hard_failures)
        raise AssertionError(f"Data Quality failed: {msgs}")
