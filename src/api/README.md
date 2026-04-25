# Self-service ingestion API

A web UI + REST API on top of the pipeline. The user uploads a CSV, the
API detects the target schema, runs the pipeline, and reports the result.

## Why it exists

The pipeline runs from the terminal (`make pipeline`). Useful for engineers,
not for everyone else. This API exposes the same pipeline through a
browser-friendly interface so that:

- Business users can drop a file and see "5000 loaded" without touching CLI.
- A reviewer evaluating the project gets an interactive demo, not just code.
- The detection layer demonstrates schema-aware ingestion: the same code
  path serves CSVs from different sources without manual configuration.

## How it works

```
  Browser                       FastAPI                Pipeline
  -------                       -------                --------
   drag CSV  ----POST /upload-->
                                read headers
                                detect_schema()
                                |
                                | (writes to data/inbox/)
                                |
                                ----subprocess run----> legal_ingestion_flow
                                                       (extract, validate,
                                                        load to Postgres)
                                <--exit code, log----
                                |
              <--JSON result-----  parse Flow summary
   render UI
```

1. CSV lands at `data/inbox/{uuid}_{filename}` (immutable copy).
2. Headers are read and compared against `KNOWN_SCHEMAS` in
   `src/api/schema_detector.py`.
3. If confidence >= 50% and the schema is `legal_documents`, a subprocess
   spawns `python -m src.api._run_flow <csv_path>`.
4. The subprocess runs the standard `legal_ingestion_flow` against the
   uploaded file. Same Pydantic, same DQ rules, same Bronze/Silver/Gold.
5. The HTTP response includes the run summary plus a link to the Prefect
   UI for full traceability.

## Run it locally

```bash
# Pre-requisites: docker compose stack is up + alembic migrations applied
make api
```

That's `uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload`.

Open http://localhost:8000 in your browser.

The auto-generated OpenAPI docs are at http://localhost:8000/docs.

## Try it

Use the seeded sample as input:

```bash
python scripts/seed_data.py        # generates data/samples/legal_documents.csv
```

Drag `data/samples/legal_documents.csv` into the upload page and click
"Run pipeline". After ~15s the result panel shows the summary and a link
to the Prefect run.

## Currently supported

| Schema | Status | Pipeline behind |
|---|---|---|
| `legal_documents` | + Wired up | `legal_ingestion_flow` |
| `counterparties` | Detected, not yet wired | `commercial_ingestion_flow` |
| `transactions` | Detected, not yet wired | `commercial_ingestion_flow` |

## Security note

This API has **no authentication**. It is built for local demos and
intra-team use behind a VPN or reverse proxy with auth (Caddy basicauth,
Cognito, etc.). Do not expose it publicly without adding auth, request
size limits, and rate limiting.
