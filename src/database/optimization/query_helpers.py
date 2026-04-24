"""Query optimization utilities.

Provides helpers to:
    - Run EXPLAIN ANALYZE and parse the plan
    - Detect slow queries from pg_stat_statements
    - Compute table bloat estimates
    - Auto-run VACUUM/ANALYZE
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.observability import get_logger

logger = get_logger(__name__)


@dataclass
class QueryPlan:
    query: str
    plan: dict[str, Any]
    execution_time_ms: float
    planning_time_ms: float
    buffers_hit: int
    buffers_read: int

    @property
    def cache_hit_ratio(self) -> float:
        total = self.buffers_hit + self.buffers_read
        return self.buffers_hit / total if total else 1.0


async def explain_analyze(session: AsyncSession, query: str) -> QueryPlan:
    """Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and return parsed plan."""
    result = await session.execute(
        text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}")
    )
    rows = result.scalar_one()
    node = rows[0]

    buffers_hit = node.get("Plan", {}).get("Shared Hit Blocks", 0)
    buffers_read = node.get("Plan", {}).get("Shared Read Blocks", 0)

    return QueryPlan(
        query=query,
        plan=node,
        execution_time_ms=node.get("Execution Time", 0.0),
        planning_time_ms=node.get("Planning Time", 0.0),
        buffers_hit=buffers_hit,
        buffers_read=buffers_read,
    )


async def top_slow_queries(
    session: AsyncSession, limit: int = 20
) -> list[dict[str, Any]]:
    """Return top N slowest queries from pg_stat_statements."""
    sql = text("""
        SELECT
            queryid,
            calls,
            total_exec_time,
            mean_exec_time,
            rows,
            100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0)
                AS cache_hit_ratio,
            query
        FROM pg_stat_statements
        WHERE calls > 10
        ORDER BY mean_exec_time DESC
        LIMIT :limit
    """)
    result = await session.execute(sql, {"limit": limit})
    return [dict(r._mapping) for r in result]


async def table_stats(session: AsyncSession, table_name: str) -> dict[str, Any]:
    """Return size, row estimate, bloat estimate for a table."""
    sql = text("""
        SELECT
            pg_size_pretty(pg_total_relation_size(c.oid))      AS total_size,
            pg_size_pretty(pg_relation_size(c.oid))            AS table_size,
            pg_size_pretty(pg_indexes_size(c.oid))             AS indexes_size,
            c.reltuples::BIGINT                                AS estimated_rows,
            s.n_live_tup                                       AS live_rows,
            s.n_dead_tup                                       AS dead_rows,
            CASE WHEN s.n_live_tup > 0
                 THEN ROUND(100.0 * s.n_dead_tup / s.n_live_tup, 2)
                 ELSE 0 END                                    AS bloat_pct,
            s.last_vacuum,
            s.last_autovacuum,
            s.last_analyze
        FROM pg_class c
        JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE c.relname = :tbl
    """)
    result = await session.execute(sql, {"tbl": table_name})
    row = result.first()
    return dict(row._mapping) if row else {}


async def vacuum_analyze(session: AsyncSession, table: str) -> None:
    """Run VACUUM ANALYZE on a table. Uses autocommit for VACUUM."""
    logger.info("vacuum_analyze.start", table=table)
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    # asyncpg requires autocommit for VACUUM
    await raw.driver_connection.execute(f"VACUUM ANALYZE {table}")
    logger.info("vacuum_analyze.done", table=table)
