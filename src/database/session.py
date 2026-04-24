"""SQLAlchemy 2.0 async session management.

Two engines are maintained:
    - DIRECT (for DDL, migrations, COPY, transactions holding locks)
    - POOLED via PgBouncer (for high-concurrency OLTP reads/writes)

Using PgBouncer in transaction pooling mode requires avoiding session-level
features (SET, prepared statements), which SQLAlchemy handles correctly
when `statement_cache_size=0` is set on the asyncpg driver.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings

_settings = get_settings()


def _build_direct_engine() -> AsyncEngine:
    """Direct connection — use for migrations, COPY, long transactions."""
    return create_async_engine(
        _settings.postgres.async_dsn,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )


def _build_pooled_engine() -> AsyncEngine:
    """PgBouncer-pooled engine — for concurrent workloads."""
    dsn = (
        f"postgresql+asyncpg://{_settings.postgres.user}:{_settings.postgres.password}"
        f"@{_settings.pgbouncer.host}:{_settings.pgbouncer.port}/{_settings.postgres.db}"
    )
    return create_async_engine(
        dsn,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )


direct_engine: AsyncEngine = _build_direct_engine()
pooled_engine: AsyncEngine = _build_pooled_engine()

DirectSession = async_sessionmaker(direct_engine, expire_on_commit=False)
PooledSession = async_sessionmaker(pooled_engine, expire_on_commit=False)


@asynccontextmanager
async def direct_session() -> AsyncIterator[AsyncSession]:
    """Context manager for direct DB session."""
    async with DirectSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def pooled_session() -> AsyncIterator[AsyncSession]:
    """Context manager for PgBouncer-pooled session."""
    async with PooledSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
