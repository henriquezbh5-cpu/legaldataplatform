#!/usr/bin/env bash
# Cross-platform bootstrap script for LegalDataPlatform (bash).
# Works on macOS, Linux, WSL, and Git Bash on Windows.
#
# Usage:
#   bash scripts/setup.sh
#
# Steps:
#   1. Check prerequisites (python, docker, git)
#   2. Create .env from .env.example if missing
#   3. Create and activate Python virtualenv
#   4. Install Python dependencies
#   5. Start Docker stack
#   6. Wait for PostgreSQL readiness
#   7. Apply Alembic migrations
#   8. Generate sample data

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

info()    { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()      { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
warn()    { printf "\033[1;33m[WARN]\033[0m  %s\n" "$*"; }
fail()    { printf "\033[1;31m[FAIL]\033[0m  %s\n" "$*"; exit 1; }

require() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing prerequisite: $1. Install it and re-run."
}

info "Checking prerequisites..."
require python3 2>/dev/null || require python
require docker
require git
ok "Prerequisites present."

# ---------------------------------------------------------------------------
# Select python binary
# ---------------------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi

PY_VERSION="$($PY -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
REQ_MAJOR=3
REQ_MINOR=11
CUR_MAJOR="${PY_VERSION%%.*}"
CUR_MINOR="${PY_VERSION##*.}"
if [[ "$CUR_MAJOR" -lt "$REQ_MAJOR" ]] || { [[ "$CUR_MAJOR" -eq "$REQ_MAJOR" ]] && [[ "$CUR_MINOR" -lt "$REQ_MINOR" ]]; }; then
    fail "Python $REQ_MAJOR.$REQ_MINOR+ required; found $PY_VERSION."
fi
ok "Python $PY_VERSION detected."

# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
    info "Creating .env from .env.example..."
    cp .env.example .env
    ok ".env created. Edit it if you need non-default values."
else
    ok ".env already exists (not overwriting)."
fi

# ---------------------------------------------------------------------------
# Virtualenv
# ---------------------------------------------------------------------------
if [[ ! -d .venv ]]; then
    info "Creating Python virtualenv in .venv..."
    "$PY" -m venv .venv
    ok "Virtualenv created."
fi

# Detect activation script (POSIX vs Git Bash on Windows)
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [[ -f .venv/Scripts/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
else
    fail "Could not locate virtualenv activate script."
fi
ok "Virtualenv activated."

info "Upgrading pip..."
python -m pip install --upgrade pip --quiet
ok "pip upgraded."

info "Installing dependencies (this may take a few minutes the first time)..."
pip install -e ".[dev]" --quiet
ok "Dependencies installed."

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon is not running. Start Docker Desktop / dockerd and re-run."
fi

info "Starting Docker stack (postgres, pgbouncer, minio, prefect, prometheus, grafana)..."
docker compose up -d
ok "Containers requested."

info "Waiting for PostgreSQL to be ready..."
MAX_ATTEMPTS=30
for i in $(seq 1 $MAX_ATTEMPTS); do
    if docker compose exec -T postgres pg_isready -U ldp_admin -d legaldata >/dev/null 2>&1; then
        ok "PostgreSQL is accepting connections."
        break
    fi
    if [[ "$i" -eq "$MAX_ATTEMPTS" ]]; then
        fail "PostgreSQL did not become ready in time. Check 'docker compose logs postgres'."
    fi
    sleep 2
done

# ---------------------------------------------------------------------------
# Migrations + seed
# ---------------------------------------------------------------------------
info "Applying Alembic migrations..."
alembic upgrade head
ok "Schema ready."

info "Generating sample data..."
python scripts/seed_data.py
ok "Sample data generated in data/samples/."

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n"
ok "Setup complete. Next steps:"
printf "  \033[1;36mmake pipeline\033[0m        # run the legal ingestion flow\n"
printf "  \033[1;36mmake test\033[0m            # run the test suite\n"
printf "  \033[1;36mmake benchmark\033[0m       # measure query performance\n"
printf "\n"
printf "UIs:\n"
printf "  Prefect:    http://localhost:4200\n"
printf "  MinIO:      http://localhost:9001  (minioadmin / minioadmin123)\n"
printf "  Prometheus: http://localhost:9090\n"
printf "  Grafana:    http://localhost:3000  (admin / admin)\n"
