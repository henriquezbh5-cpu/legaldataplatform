"""Fixtures for integration tests against a real PostgreSQL.

Two operation modes:
    1. CI (GitHub Actions):   POSTGRES_HOST points to a `services.postgres` container.
       → we connect directly.
    2. Local dev:             POSTGRES_HOST is localhost, Docker Compose stack is up.
       → same: connect directly.

In both cases we create a dedicated test database per session, run migrations,
and tear it down at the end. This keeps tests isolated from the dev database
and makes them safe to run concurrently in CI.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_USER = os.environ.get("POSTGRES_USER", "ldp_admin")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "ldp_dev_password")


def _dsn(db: str) -> str:
    return f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db}"


def _async_dsn(db: str) -> str:
    return f"postgresql+asyncpg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db}"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_db_name() -> AsyncIterator[str]:
    """Create a unique test database for the session; drop it at teardown."""
    name = f"ldp_test_{uuid.uuid4().hex[:12]}"
    admin_conn = await asyncpg.connect(_dsn("postgres"))
    try:
        await admin_conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin_conn.close()

    yield name

    admin_conn = await asyncpg.connect(_dsn("postgres"))
    try:
        # Terminate any lingering connections before DROP
        await admin_conn.execute(f"""
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = '{name}' AND pid <> pg_backend_pid()
        """)
        await admin_conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await admin_conn.close()


@pytest_asyncio.fixture(scope="session")
async def applied_migrations(test_db_name: str) -> str:
    """Apply Alembic migrations to the test database."""
    import subprocess
    env = os.environ.copy()
    env["POSTGRES_DB"] = test_db_name
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic migrations failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    return test_db_name


@pytest_asyncio.fixture
async def db_session(applied_migrations: str) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy session bound to the migrated test DB.

    Each test gets a fresh session; changes are committed (tests should clean
    up what they insert, or use unique identifiers to avoid collisions).
    """
    engine = create_async_engine(_async_dsn(applied_migrations), pool_pre_ping=True)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        yield session
    await engine.dispose()
