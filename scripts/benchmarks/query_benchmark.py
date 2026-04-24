"""Benchmark a suite of representative queries before/after optimization.

Runs each query N times, reports p50/p95/p99 latency and cache hit ratio.
"""
from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass

from sqlalchemy import text

from src.database.optimization.query_helpers import explain_analyze, table_stats
from src.database.session import direct_session
from src.observability import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@dataclass
class Benchmark:
    name: str
    query: str
    iterations: int = 20


BENCHMARKS = [
    Benchmark(
        name="count_transactions_last_30d",
        query="""
            SELECT count(*) FROM transactions
            WHERE transaction_date >= CURRENT_DATE - INTERVAL '30 days'
        """,
    ),
    Benchmark(
        name="top_counterparties_by_revenue",
        query="""
            SELECT counterparty_id, SUM(amount) AS revenue
              FROM transactions
             WHERE transaction_date >= CURRENT_DATE - INTERVAL '90 days'
               AND transaction_type = 'INVOICE'
             GROUP BY counterparty_id
             ORDER BY revenue DESC
             LIMIT 20
        """,
    ),
    Benchmark(
        name="fuzzy_search_entity_name",
        query="""
            SELECT id, legal_name
              FROM legal_entities
             WHERE legal_name ILIKE '%ACME%'
             LIMIT 50
        """,
    ),
    Benchmark(
        name="mv_monthly_revenue_scan",
        query="""
            SELECT month, SUM(total_amount) AS revenue
              FROM mv_monthly_revenue_per_counterparty
             GROUP BY month
             ORDER BY month DESC
             LIMIT 12
        """,
    ),
]


async def run_benchmark(bench: Benchmark) -> None:
    durations: list[float] = []
    async with direct_session() as session:
        # Warm-up
        await session.execute(text(bench.query))
        await session.commit()

        for _ in range(bench.iterations):
            start = time.perf_counter()
            await session.execute(text(bench.query))
            await session.commit()
            durations.append((time.perf_counter() - start) * 1000)

        plan = await explain_analyze(session, bench.query)

    durations.sort()
    p50 = statistics.median(durations)
    p95 = durations[int(len(durations) * 0.95) - 1]
    p99 = durations[int(len(durations) * 0.99) - 1]

    print(f"\n=== {bench.name} ===")
    print(f"Iterations:     {bench.iterations}")
    print(f"p50:            {p50:.2f} ms")
    print(f"p95:            {p95:.2f} ms")
    print(f"p99:            {p99:.2f} ms")
    print(f"Plan exec_time: {plan.execution_time_ms:.2f} ms")
    print(f"Cache hit:      {plan.cache_hit_ratio:.2%}")


async def main() -> None:
    print("=== Table statistics ===")
    for tbl in ["legal_documents", "transactions", "counterparties"]:
        async with direct_session() as session:
            stats = await table_stats(session, tbl)
            if stats:
                print(f"{tbl}: rows={stats.get('estimated_rows'):,}  "
                      f"size={stats.get('total_size')}  "
                      f"bloat={stats.get('bloat_pct')}%")

    for bench in BENCHMARKS:
        await run_benchmark(bench)


if __name__ == "__main__":
    asyncio.run(main())
