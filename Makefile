.PHONY: help install up down logs migrate seed test lint format pipeline benchmark clean

help:
	@echo "LegalDataPlatform — Available commands"
	@echo ""
	@echo "  make install       Install Python dependencies"
	@echo "  make up            Start local stack (Postgres, MinIO, Prefect, Grafana)"
	@echo "  make down          Stop local stack"
	@echo "  make logs          Tail all container logs"
	@echo "  make migrate       Apply Alembic migrations"
	@echo "  make seed          Load sample data"
	@echo "  make pipeline      Run the legal ingestion pipeline end-to-end"
	@echo "  make test          Run test suite"
	@echo "  make lint          Lint code with ruff + mypy"
	@echo "  make format        Format code with ruff"
	@echo "  make benchmark     Run query benchmark suite"
	@echo "  make clean         Remove build artifacts"

install:
	pip install -e ".[dev]"

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

test:
	pytest

lint:
	ruff check src tests
	mypy src

format:
	ruff format src tests
	ruff check --fix src tests

benchmark:
	python scripts/benchmarks/query_benchmark.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
