"""FastAPI app for self-service ingestion.

Endpoints:
    GET  /                  -> upload page (HTML)
    POST /upload            -> accept CSV, detect schema, run pipeline
    GET  /runs/{run_id}     -> status of a run (returns JSON)
    GET  /health            -> liveness probe
    GET  /docs              -> OpenAPI Swagger UI (auto-generated)

Design notes:
- The upload writes the file to data/inbox/<uuid>.csv first, so we have a
  permanent copy before any processing. Same Bronze pattern at the API edge.
- We call the legal_ingestion_flow directly via a subprocess to avoid
  blocking the HTTP request thread on Prefect's async machinery and to
  isolate any flow crash from the API.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.schema_detector import detect_schema

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

API_DIR = Path(__file__).parent
TEMPLATES_DIR = API_DIR / "templates"
STATIC_DIR = API_DIR / "static"

PROJECT_ROOT = API_DIR.parent.parent
INBOX_DIR = PROJECT_ROOT / "data" / "inbox"
RUNS_DIR = PROJECT_ROOT / "data" / "runs"
INBOX_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

PREFECT_UI_BASE = "http://localhost:4200"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LegalDataPlatform - Ingestion API",
    description="Self-service CSV upload that detects schema and triggers the pipeline.",
    version="0.1.0",
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {})


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only .csv files are supported in this version. "
            "JSON / Parquet / Excel are roadmap.",
        )

    # 1. Land the upload in data/inbox/<uuid>.csv
    upload_id = uuid.uuid4().hex[:12]
    safe_name = Path(file.filename).name
    inbox_path = INBOX_DIR / f"{upload_id}_{safe_name}"
    contents = await file.read()
    inbox_path.write_bytes(contents)

    # 2. Read headers and detect schema
    try:
        with inbox_path.open("r", encoding="utf-8", newline="") as fh:
            sample = fh.read(8192)
            reader = csv.reader(sample.splitlines())
            headers = next(reader, [])
            row_estimate = sum(1 for _ in reader)  # rows in the 8KB sample
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File is not UTF-8. Save as UTF-8 CSV and re-upload.",
        ) from None

    if not headers:
        raise HTTPException(status_code=400, detail="CSV appears to have no header row.")

    match = detect_schema(headers)

    if not match.is_confident:
        return JSONResponse({
            "status": "needs_mapping",
            "upload_id": upload_id,
            "filename": safe_name,
            "headers": headers,
            "match": {
                "best_guess": match.schema,
                "confidence": round(match.score, 2),
                "matched_headers": match.matched_headers,
                "unknown_headers": match.unknown_headers,
            },
            "message": (
                "Could not confidently detect schema. "
                "Best guess was '{best}' with {score:.0%} confidence. "
                "Review your column names and try again."
            ).format(best=match.schema, score=match.score),
        }, status_code=422)

    # 3. Dispatch to the right pipeline (today: legal_documents only)
    if match.schema != "legal_documents":
        return JSONResponse({
            "status": "schema_not_implemented",
            "upload_id": upload_id,
            "detected_schema": match.schema,
            "message": (
                f"Detected schema '{match.schema}' but only 'legal_documents' "
                "is wired up to the API in this version. The flow exists "
                "(commercial_ingestion_flow) but isn't exposed via upload yet."
            ),
        }, status_code=501)

    # 4. Run the legal pipeline against this specific file
    run_id = f"{datetime.utcnow():%Y%m%dT%H%M%S}_{upload_id}"
    log_path = RUNS_DIR / f"{run_id}.log"

    try:
        completed = _run_pipeline_against(inbox_path, log_path)
    except subprocess.TimeoutExpired:
        return JSONResponse({
            "status": "timeout",
            "upload_id": upload_id,
            "run_id": run_id,
            "message": "Pipeline took longer than 5 minutes; assumed hung.",
        }, status_code=504)

    summary = _parse_flow_summary(log_path)

    response = {
        "status": "completed" if completed.returncode == 0 else "failed",
        "upload_id": upload_id,
        "run_id": run_id,
        "filename": safe_name,
        "headers_detected": headers,
        "schema_detected": match.schema,
        "schema_confidence": round(match.score, 2),
        "rows_in_sample": row_estimate,
        "exit_code": completed.returncode,
        "summary": summary,
        "prefect_ui": f"{PREFECT_UI_BASE}/flow-runs",
        "logs_url": f"/runs/{run_id}/log",
    }
    return JSONResponse(response, status_code=200 if completed.returncode == 0 else 500)


@app.get("/runs/{run_id}/log", response_class=HTMLResponse)
def run_log(request: Request, run_id: str) -> HTMLResponse:
    log_path = RUNS_DIR / f"{run_id}.log"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Run log not found")
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    return templates.TemplateResponse(
        request,
        "log.html",
        {"run_id": run_id, "log_text": log_text},
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _run_pipeline_against(csv_path: Path, log_path: Path) -> subprocess.CompletedProcess:
    """Run the legal_ingestion_flow as a subprocess pointing at a custom CSV.

    We pass the absolute CSV path via env var; the flow reads that to know
    which file to ingest. Subprocess isolates any flow crash from the API
    and lets us capture stdout+stderr cleanly.
    """
    cmd = [sys.executable, "-m", "src.api._run_flow", str(csv_path)]
    with log_path.open("w", encoding="utf-8") as log_fh:
        return subprocess.run(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            timeout=300,
            cwd=str(PROJECT_ROOT),
            check=False,
        )


def _parse_flow_summary(log_path: Path) -> dict[str, Any]:
    """Find the 'Flow summary: {...}' line in the run log and return its dict."""
    summary: dict[str, Any] = {}
    if not log_path.exists():
        return summary
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        marker = "Flow summary: "
        idx = line.find(marker)
        if idx >= 0:
            try:
                summary = json.loads(line[idx + len(marker) :].replace("'", '"'))
            except json.JSONDecodeError:
                continue
    return summary
