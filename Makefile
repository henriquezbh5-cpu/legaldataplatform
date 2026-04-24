.PHONY: help install install-hooks up down logs migrate seed \
        test test-unit test-integration lint format \
        pipeline sec-edgar gleif commercial \
        benchmark evidence docker-build clean

help:
	@echo "LegalDataPlatform — Available commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install            Install Python dependencies"
	@echo "  make install-hooks      Install pre-commit git hooks"
	@echo ""
	@echo "Stack:"
	@echo "  make up                 Start local stack (Postgres, MinIO, Prefect, Grafana)"
	@echo "  make down               Stop local stack"
	@echo "  make logs               Tail all container logs"
	@echo "  make migrate            Apply Alembic migrations"
	@echo "  make seed               Load sample data"
	@echo ""
	@echo "Pipelines:"
	@echo "  make pipeline           Run the legal ingestion pipeline (CSV source)"
	@echo "  make sec-edgar          Run the SEC EDGAR ingestion flow (real source)"
	@echo "  make gleif              Run the GLEIF ingestion flow (real LEI source)"
	@echo "  make commercial         Run the commercial ingestion flow"
	@echo ""
	@echo "Quality:"
	@echo "  make test               Run the full test suite"
	@echo "  make test-unit          Run only unit tests"
	@echo "  make test-integration   Run only integration tests (needs Postgres)"
	@echo "  make lint               Lint code with ruff + mypy"
	@echo "  make format             Format code with ruff"
	@echo ""
	@echo "Evidence:"
	@echo "  make benchmark          Run query benchmark suite"
	@echo "  make evidence           Capture env + benchmarks into docs/evidence/"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build       Build the pipeline worker image locally"
	@echo ""
	@echo "  make clean              Remove build artifacts"

install:
	pip install -e ".[dev]"

install-hooks:
	pip install pre-commit
	pre-commit install
	@echo "Pre-commit hooks installed. They'll run automatically on 'git commit'."

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	alembic upgrade head

seed:
	python scripts/seed_data.py

pipeline:
	python -m src.pipelines.orchestration.legal_ingestion_flow

sec-edgar:
	python -m src.pipelines.orchestration.sec_edgar_flow

gleif:
	python -m src.pipelines.orchestration.gleif_flow

commercial:
	python -m src.pipelines.orchestration.commercial_ingestion_flow

test:
	pytest

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

lint:
	ruff check src tests
	mypy src

format:
	ruff format src tests
	ruff check --fix src tests

benchmark:
	python scripts/benchmarks/query_benchmark.py

evidence:
	python scripts/capture_env.py > docs/evidence/env.md
	python scripts/capture_benchmarks.py > docs/evidence/benchmarks.md
	@echo "Evidence files updated. Remember to take screenshots per docs/evidence/README.md."

docker-build:
	docker build -t ldp-pipeline:local .
	@echo "Run with: docker run --rm --network=host --env-file=.env ldp-pipeline:local python -m src.pipelines.orchestration.legal_ingestion_flow"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
