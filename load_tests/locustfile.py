"""Locust load test for the PostgreSQL query layer.

Runs representative read-path queries against a running PostgreSQL (or
PgBouncer) instance. Each task maps to one of the real analytical
queries the application performs.

Usage:
    pip install locust sqlalchemy psycopg[binary]

    locust -f load_tests/locustfile.py \\
      --host postgresql://ldp_admin:ldp_dev_password@localhost:5432/legaldata

Then open http://localhost:8089.

For headless mode (CI / benchmarks):
    locust -f load_tests/locustfile.py \\
      --host postgresql://ldp_admin:ldp_dev_password@localhost:5432/legaldata \\
      --users 50 --spawn-rate 5 --run-time 2m --headless \\
      --csv=load_tests/results/run
"""

from __future__ import annotations

import random
import time

from locust import HttpUser, User, between, events, task
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

# ---------------------------------------------------------------------------
# Engine is process-wide and shared across users. QueuePool size tuned to
# a small multiplier over expected concurrency so Locust doesn't saturate
# PostgreSQL directly (use PgBouncer for the real test).
# ---------------------------------------------------------------------------
_engine: Engine | None = None


def get_engine(dsn: str) -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            dsn,
            poolclass=QueuePool,
            pool_size=20,
            max_overflow=40,
            pool_pre_ping=True,
        )
    return _engine


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    """Warm the connection pool before measurements start."""
    host = environment.parsed_options.host
    if not host:
        return
    engine = get_engine(host)
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    print(f"[locust] Connection pool warmed against {host}")


def timed_query(environment, name: str, sql: str, params: dict | None = None) -> None:
    """Run a query and report timing to locust's event bus.

    This produces the same p50/p95/p99 stats you'd see in Grafana for real
    application requests.
    """
    host = environment.parsed_options.host
    engine = get_engine(host)

    start = time.perf_counter()
    err = None
    rows = 0
    try:
        with engine.connect() as c:
            result = c.execute(text(sql), params or {})
            rows = len(result.fetchall())
    except Exception as e:  # noqa: BLE001
        err = e

    elapsed_ms = (time.perf_counter() - start) * 1000

    events.request.fire(
        request_type="SQL",
        name=name,
        response_time=elapsed_ms,
        response_length=rows,
        exception=err,
        context={},
    )


# ---------------------------------------------------------------------------
# User classes — each task represents one class of query the app runs.
# ---------------------------------------------------------------------------


class PostgresUser(User):
    """A single simulated API/BI user running mixed analytical queries."""

    wait_time = between(0.5, 2.0)

    @task(5)
    def count_recent_transactions(self):
        """Partition-pruning workload. High weight because it's called often."""
        timed_query(
            self.environment,
            "count_recent_transactions",
            """
            SELECT count(*) FROM transactions
             WHERE transaction_date >= CURRENT_DATE - INTERVAL '30 days'
            """,
        )

    @task(3)
    def top_counterparties_by_revenue(self):
        """Covering-index workload."""
        timed_query(
            self.environment,
            "top_counterparties_by_revenue",
            """
            SELECT counterparty_id, sum(amount) AS revenue
              FROM transactions
             WHERE transaction_date >= CURRENT_DATE - INTERVAL '90 days'
               AND transaction_type = 'INVOICE'
             GROUP BY counterparty_id
             ORDER BY revenue DESC
             LIMIT 20
            """,
        )

    @task(4)
    def monthly_revenue_scan(self):
        """Materialized-view workload — should be sub-ms."""
        timed_query(
            self.environment,
            "monthly_revenue_scan",
            """
            SELECT month, sum(total_amount) AS revenue
              FROM mv_monthly_revenue_per_counterparty
             WHERE currency = :currency
             GROUP BY month
             ORDER BY month DESC
             LIMIT 12
            """,
            {"currency": random.choice(["USD", "EUR", "GBP"])},
        )

    @task(2)
    def fuzzy_entity_search(self):
        """Trigram GIN index workload."""
        needle = random.choice(["acme", "trade", "global", "corp", "ltd"])
        timed_query(
            self.environment,
            "fuzzy_entity_search",
            """
            SELECT id, legal_name
              FROM legal_entities
             WHERE legal_name ILIKE :pattern
             LIMIT 50
            """,
            {"pattern": f"%{needle}%"},
        )

    @task(1)
    def point_in_time_counterparty(self):
        """SCD2 time-travel workload."""
        days_ago = random.randint(30, 365)
        timed_query(
            self.environment,
            "point_in_time_counterparty",
            """
            SELECT external_id, name, risk_score
              FROM dim_counterparty
             WHERE :target_date BETWEEN valid_from AND valid_to
             LIMIT 100
            """,
            {"target_date": f"CURRENT_DATE - INTERVAL '{days_ago} days'"},
        )


# Fallback HttpUser so --host accepts a URL; not used for SQL scenarios
class HealthCheckUser(HttpUser):
    """Pings the Prefect UI if a URL-based host is provided alongside."""

    wait_time = between(5, 10)
    abstract = True   # activate only when explicitly selected

    @task
    def prefect_health(self):
        self.client.get("/api/health", name="prefect_health")
