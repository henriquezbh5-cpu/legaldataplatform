# syntax=docker/dockerfile:1.7
# =============================================================================
# Pipeline worker image — runs Prefect flows, extractors and loaders.
# =============================================================================
# Multi-stage build:
#   - builder: compile wheels with dev toolchain, then discard
#   - runtime: minimal image with only runtime deps
#
# Resulting image is ~280 MB (vs ~1.2 GB if single-stage).
# =============================================================================

ARG PYTHON_VERSION=3.11

# -----------------------------------------------------------------------------
# Stage 1: builder
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build toolchain needed by some native deps (asyncpg, pyarrow on arm64, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy only the dependency descriptors first to maximize layer caching
COPY pyproject.toml README.md ./
COPY src ./src

# Install into a relocatable directory
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -e .

# -----------------------------------------------------------------------------
# Stage 2: runtime
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Runtime-only libs (libpq for psycopg, ca-certs for HTTPS, tini for PID 1)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 ldp \
    && useradd --system --uid 1001 --gid ldp --home /app ldp

WORKDIR /app

# Bring in the prebuilt venv and application code
COPY --from=builder /opt/venv /opt/venv
COPY --chown=ldp:ldp src ./src
COPY --chown=ldp:ldp alembic.ini ./
COPY --chown=ldp:ldp config ./config
COPY --chown=ldp:ldp scripts ./scripts

USER ldp

# Health check: can the Python process import the package?
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import src; import prefect" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command runs the Prefect worker against a configured queue.
# Override with:
#   docker run ldp-pipeline python -m src.pipelines.orchestration.sec_edgar_flow
CMD ["prefect", "worker", "start", "--pool", "default-agent-pool"]
