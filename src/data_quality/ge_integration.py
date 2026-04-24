"""Great Expectations integration: build Expectation Suites from YAML rules.

GE provides:
- Data Docs (static HTML documentation auto-generated from suites)
- Statistical expectations (distributions, means, quantiles)
- Profiling to bootstrap new suites

We keep the two systems complementary:
    rule_engine.py  → fast, in-pipeline, structural checks
    ge_integration  → richer checks + documentation artifacts
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:  # GE is optional for lightweight deployments
    import great_expectations as gx
    from great_expectations.core.expectation_suite import ExpectationSuite
    GE_AVAILABLE = True
except ImportError:
    GE_AVAILABLE = False

from src.observability import get_logger

logger = get_logger(__name__)


def build_expectation_suite(
    suite_name: str,
    column_expectations: dict[str, list[dict[str, Any]]],
) -> "ExpectationSuite":
    """Build a GE suite from a dict of {column: [expectation_dicts]}.

    Example:
        build_expectation_suite("txn", {
            "amount": [
                {"type": "expect_column_values_to_not_be_null"},
                {"type": "expect_column_values_to_be_between",
                 "kwargs": {"min_value": -1e9, "max_value": 1e9}},
            ]
        })
    """
    if not GE_AVAILABLE:
        raise RuntimeError("Great Expectations is not installed.")

    suite = ExpectationSuite(name=suite_name)
    for column, exps in column_expectations.items():
        for exp in exps:
            kwargs = dict(exp.get("kwargs", {}))
            kwargs["column"] = column
            suite.add_expectation_configuration(
                gx.core.ExpectationConfiguration(
                    expectation_type=exp["type"],
                    kwargs=kwargs,
                )
            )
    return suite


def validate_dataframe(
    df: pd.DataFrame,
    suite: "ExpectationSuite",
    data_docs_dir: Path | None = None,
) -> dict[str, Any]:
    """Run a suite against a DataFrame, optionally rendering Data Docs."""
    if not GE_AVAILABLE:
        raise RuntimeError("Great Expectations is not installed.")

    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas("in_mem")
    asset = data_source.add_dataframe_asset("frame")
    batch_def = asset.add_batch_definition_whole_dataframe("default_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": df})

    result = batch.validate(suite)

    if data_docs_dir:
        data_docs_dir.mkdir(parents=True, exist_ok=True)
        # Writing Data Docs requires a filesystem context; skipped in ephemeral
        logger.info("ge.data_docs_dir_requested", path=str(data_docs_dir))

    return result.to_json_dict()
