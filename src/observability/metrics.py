"""Prometheus metrics for pipeline observability.

Metrics follow the RED (Rate, Errors, Duration) method plus data-specific
counters (records processed, quarantined, quality failures).
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, push_to_gateway

registry = CollectorRegistry()

records_extracted = Counter(
    "ldp_records_extracted_total",
    "Total records extracted from source",
    ["source", "pipeline"],
    registry=registry,
)

records_loaded = Counter(
    "ldp_records_loaded_total",
    "Total records loaded to target",
    ["target", "pipeline"],
    registry=registry,
)

records_quarantined = Counter(
    "ldp_records_quarantined_total",
    "Records moved to quarantine due to quality failures",
    ["pipeline", "rule"],
    registry=registry,
)

pipeline_duration = Histogram(
    "ldp_pipeline_duration_seconds",
    "Pipeline execution duration",
    ["pipeline", "stage"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
    registry=registry,
)

pipeline_errors = Counter(
    "ldp_pipeline_errors_total",
    "Total pipeline errors",
    ["pipeline", "stage", "error_type"],
    registry=registry,
)

dq_checks = Counter(
    "ldp_dq_checks_total",
    "Data quality checks executed",
    ["suite", "result"],  # result: passed|failed
    registry=registry,
)


def push_metrics(gateway_url: str, job_name: str) -> None:
    """Push current metrics to Prometheus Pushgateway (for batch jobs)."""
    push_to_gateway(gateway_url, job=job_name, registry=registry)
