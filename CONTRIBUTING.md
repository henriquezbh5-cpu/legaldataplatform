# Contributing

Thanks for considering a contribution to LegalDataPlatform. This guide covers local setup, the expected workflow and the conventions the codebase follows.

## Local setup

Prerequisites: Python 3.11+, Docker Desktop, Git.

```bash
# 1. Fork & clone
git clone https://github.com/YOUR_USER/legaldataplatform
cd legaldataplatform

# 2. Virtualenv + editable install
python -m venv .venv
source .venv/bin/activate           # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# 3. Pre-commit hooks
make install-hooks

# 4. Start the stack and seed
cp .env.example .env
docker compose up -d
alembic upgrade head
python scripts/seed_data.py
```

Verify your environment works end-to-end:

```bash
make pipeline
make test
```

## Workflow

1. Create a feature branch off `main`: `git checkout -b feat/short-description`
2. Keep commits focused and atomic; each should pass CI on its own.
3. Run the quality gates locally before pushing:
   ```bash
   make lint
   make format
   make test
   ```
4. Open a pull request against `main` describing:
   - What changed
   - Why it changed
   - Any trade-offs accepted
   - How you tested it

## Branch and commit conventions

- **Branches**: `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`, `test/`
- **Commits**: short imperative subject line (50 chars max), blank line, wrap-at-72 body explaining the *why*. Reference issues with `#123`.

Example:

```
Add rate-limited GLEIF extractor

GLEIF's public API allows unauthenticated reads but recommends
<= 60 req/min. The extractor enforces this via an asyncio semaphore
and respects JSON:API pagination headers (meta.pagination.lastPage).

Closes #42.
```

## Code style

The project uses **ruff** for linting + formatting and **mypy** for type checking. Both run on pre-commit and CI; changes that don't pass will be rejected.

- Line length: 100 characters
- Quote style: double (`"..."`)
- Import sorting: isort-compatible via ruff (I001)
- Type annotations required on all function signatures in `src/`
- Naming: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for module-level constants

## Testing expectations

| Layer | Where | Dependencies |
|---|---|---|
| Unit | `tests/unit/` | No services — mock everything |
| Integration | `tests/integration/` | Real PostgreSQL (Docker Compose or CI service container) |

- New extractors need unit tests with `httpx.MockTransport` and a deterministic-hash test.
- New loaders or transformers that touch the DB need an integration test.
- Aim for `coverage > 80%` on new code paths; avoid lowering the overall coverage.

## Data quality rules

Rules live in `src/data_quality/rules/*.yaml`. Adding a new rule is a YAML-only change — no Python needed. Each rule must specify:

```yaml
- name: descriptive_snake_case
  type: not_null | unique | regex | in_set | range | row_count_range
  column: target_column        # not needed for row_count_range
  params: { ... }              # type-specific
  severity: error | warning    # error blocks the pipeline
```

## Architecture decisions

Substantive architectural decisions should be documented as **ADRs** inside [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) (section 15) with the template:

1. **Context** — the problem and constraints
2. **Decision** — what was chosen
3. **Consequences** — positive and negative
4. **Alternatives evaluated** — with reasons for rejection

## Reporting security issues

Please don't open a public issue for security-sensitive reports. Email henriquezbh5@gmail.com with details; you will receive a response within 72 hours.

## Code of conduct

Be professional, direct and respectful. Critique ideas, not people. Assume good intent.
