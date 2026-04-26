#!/bin/sh
# =============================================================================
# Cloud entrypoint for the LegalDataPlatform API (Railway / Render / Fly).
#
# Steps:
#   1. Parse DATABASE_URL (Railway-style) into POSTGRES_* env vars
#   2. Wait for Postgres to be reachable
#   3. Run alembic migrations (creates partitioned tables, indexes, MViews)
#   4. Seed the database the first time (idempotent — checks row count)
#   5. Launch uvicorn on $PORT (default 8000)
# =============================================================================
set -e

# -----------------------------------------------------------------------------
# Step 1 — DATABASE_URL → POSTGRES_* (so PostgresSettings picks it up)
# -----------------------------------------------------------------------------
if [ -n "$DATABASE_URL" ]; then
    echo ">>> Parsing DATABASE_URL into POSTGRES_* env vars..."
    eval $(python - <<'PY'
import os, sys
from urllib.parse import urlparse, unquote
url = os.environ["DATABASE_URL"]
# Railway uses postgresql:// (or postgres://) — normalize
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]
p = urlparse(url)
print(f'export POSTGRES_HOST="{p.hostname}"')
print(f'export POSTGRES_PORT="{p.port or 5432}"')
print(f'export POSTGRES_USER="{unquote(p.username or "")}"')
print(f'export POSTGRES_PASSWORD="{unquote(p.password or "")}"')
print(f'export POSTGRES_DB="{(p.path or "/postgres").lstrip("/")}"')
PY
)
fi

echo ">>> [1/4] Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
python - <<'PY'
import os, time, sys
import psycopg

dsn = (
    f"host={os.environ.get('POSTGRES_HOST','localhost')} "
    f"port={os.environ.get('POSTGRES_PORT','5432')} "
    f"user={os.environ.get('POSTGRES_USER','postgres')} "
    f"password={os.environ.get('POSTGRES_PASSWORD','')} "
    f"dbname={os.environ.get('POSTGRES_DB','postgres')}"
)
for attempt in range(60):
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            print(f"  connected after {attempt+1} attempt(s)")
            break
    except Exception as e:
        time.sleep(2)
else:
    print("ERROR: PostgreSQL not reachable after 120s", file=sys.stderr)
    sys.exit(1)
PY

echo ">>> [2/4] Running alembic migrations..."
alembic upgrade head || {
    echo "WARN: alembic failed — continuing anyway (table may already exist)"
}

echo ">>> [3/4] Seeding sample CSV (idempotent)..."
python - <<'PY'
import os
import psycopg
from pathlib import Path

dsn = (
    f"host={os.environ.get('POSTGRES_HOST','localhost')} "
    f"port={os.environ.get('POSTGRES_PORT','5432')} "
    f"user={os.environ.get('POSTGRES_USER','postgres')} "
    f"password={os.environ.get('POSTGRES_PASSWORD','')} "
    f"dbname={os.environ.get('POSTGRES_DB','postgres')}"
)

try:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM legal_documents")
        count = cur.fetchone()[0]
except Exception as e:
    print(f"  could not check row count ({e}) — skipping seed")
    count = -1

if count == -1:
    pass
elif count >= 1000:
    print(f"  legal_documents already has {count} rows — skipping seed")
else:
    print(f"  legal_documents has {count} rows — running seed pipeline")
    try:
        from src.api.processor import process_csv
        sample = Path("data/samples/legal_documents.csv")
        if sample.exists():
            result = process_csv(sample, pipeline_name="cloud_seed")
            print(f"  seeded: extracted={result['extracted']} loaded={result['loaded']}")
        else:
            print(f"  WARN: sample file {sample} not found")
    except Exception as e:
        print(f"  WARN: seed failed: {e}")
PY

PORT="${PORT:-8000}"
echo ">>> [4/4] Launching uvicorn on 0.0.0.0:${PORT}"
exec uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT}" --workers 2
