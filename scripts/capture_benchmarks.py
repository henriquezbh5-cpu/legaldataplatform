"""Runs the benchmark suite and produces a markdown report with real numbers.

Unlike `scripts/benchmarks/query_benchmark.py` which prints to stdout, this
script emits a structured markdown table that can be committed to the
evidence folder.

Usage:
    python scripts/capture_benchmarks.py > docs/evidence/benchmarks.md
"""
from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from src.database.optimization.query_helpers import explain_analyze, table_stats
from src.database.session import direct_session
from src.observability import configure_logging

configure_logging()


@dataclass
class Bench:
    name: str
    description: str
    query: str
    iterations: int = 20


BENCHES = [
    Bench(
        name="count_transactions_last_30d",
        description="Partition pruning check — only scans current month partition",
        query=(
            "SELECT count(*) FROM transactions "
            "WHERE transaction_date >= CURRENT_DATE - INTERVAL '30 days'"
        ),
    ),
    Bench(
        name="top_counterparties_by_revenue",
        description="Covering index read — uses ix_txn_counterparty_recent",
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
    Bench(
        name="fuzzy_search_entity_name",
        description="Trigram index (pg_trgm) — should avoid sequential scan",
        query="SELECT id, legal_name FROM legal_entities WHERE legal_name ILIKE '%ACME%' LIMIT 50",
    ),
    Bench(
        name="mv_monthly_revenue_scan",
        description="Scan the pre-computed materialized view",
        query="""
            SELECT month, SUM(total_amount) AS revenue
              FROM mv_monthly_revenue_per_counterparty
             GROUP BY month
             ORDER BY month DESC
             LIMIT 12
        """,
    ),
    Bench(
        name="sec_edgar_filings_by_type",
        description="Real SEC EDGAR data aggregation (requires sec_edgar_flow to have run)",
        query="""
            SELECT document_type, count(*) AS filings
              FROM legal_documents
             WHERE source_system = 'sec_edgar'
             GROUP BY document_type
             ORDER BY filings DESC
        """,
    ),
]


async def run_bench(b: Bench) -> dict:
    durations = []
    plan_exec_ms = None
    cache_hit = None

    async with direct_session() as session:
        try:
            # Warm-up
            await session.execute(text(b.query))
            await session.commit()

            for _ in range(b.iterations):
                start = time.perf_counter()
                await session.execute(text(b.query))
                await session.commit()
                durations.append((time.perf_counter() - start) * 1000)

            try:
                plan = await explain_analyze(session, b.query)
                plan_exec_ms = plan.execution_time_ms
                cache_hit = plan.cache_hit_ratio
            except Exception:
                pass
        except Exception as e:
            return {"name": b.name, "error": str(e)}

    if not durations:
        return {"name": b.name, "error": "no measurements"}

    durations.sort()
    return {
        "name": b.name,
        "description": b.description,
        "iterations": b.iterations,
        "p50": statistics.median(durations),
        "p95": durations[max(int(len(durations) * 0.95) - 1, 0)],
        "p99": durations[max(int(len(durations) * 0.99) - 1, 0)],
        "min": durations[0],
        "max": durations[-1],
        "plan_exec_ms": plan_exec_ms,
        "cache_hit": cache_hit,
    }


async def run_table_stats() -> list[dict]:
    stats = []
    for tbl in ["legal_documents", "legal_entities", "counterparties", "transactions"]:
        async with direct_session() as session:
            try:
                s = await table_stats(session, tbl)
                if s:
                    stats.append({"table": tbl, **s})
            except Exception:
                pass
    return stats


async def main() -> None:
    print(f"# Benchmark capture")
    print()
    print(f"Captured: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print()
    print("All values measured on the host machine (see `env.md` for details). "
          "Warm-up run excluded from statistics; each query runs 20 iterations.")
    print()

    # Table sizes
    print("## Table sizes")
    print()
    stats = await run_table_stats()
    if stats:
        print("| Table | Live rows | Total size | Indexes size | Bloat % | Last VACUUM |")
        print("|---|---|---|---|---|---|")
        for s in stats:
            print(f"| {s['table']} | "
                  f"{s.get('live_rows') or '—'} | "
                  f"{s.get('total_size', '—')} | "
                  f"{s.get('indexes_size', '—')} | "
                  f"{s.get('bloat_pct') or '—'} | "
                  f"{s.get('last_vacuum') or s.get('last_autovacuum') or '—'} |")
    else:
        print("*(no table statistics available — run `make pipeline` first)*")
    print()

    # Benchmarks
    print("## Query performance")
    print()
    results = []
    for b in BENCHES:
        results.append(await run_bench(b))

    print("| Query | p50 (ms) | p95 (ms) | p99 (ms) | Plan exec (ms) | Cache hit |")
    print("|---|---|---|---|---|---|")
    for r in results:
        if r.get("error"):
            print(f"| `{r['name']}` | — | — | — | error: {r['error'][:60]} | — |")
            continue
        cache = f"{r['cache_hit']:.2%}" if r.get("cache_hit") is not None else "—"
        plan = f"{r['plan_exec_ms']:.2f}" if r.get("plan_exec_ms") is not None else "—"
        print(f"| `{r['name']}` | "
              f"{r['p50']:.2f} | "
              f"{r['p95']:.2f} | "
              f"{r['p99']:.2f} | "
              f"{plan} | "
              f"{cache} |")
    print()

    print("## Query descriptions")
    print()
    for r in results:
        if r.get("error"):
            continue
        print(f"- **`{r['name']}`** — {r.get('description', '')}")


if __name__ == "__main__":
    asyncio.run(main())
