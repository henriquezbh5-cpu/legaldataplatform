"""FastAPI app for self-service ingestion + post-load analytical dashboard.

Endpoints:
    GET  /                        upload page (HTML)
    POST /upload                  accept CSV, detect schema, run pipeline
                                  + return rich summary with charts data
    GET  /api/stats               aggregate counts across all data
    GET  /api/distribution/{kind} top N by type / source / jurisdiction
    GET  /api/data/preview        sample of recently-loaded rows
    GET  /api/partitions          partition inventory + sizes
    GET  /api/indexes             index list + types
    GET  /api/dq/rules            DQ rule status
    GET  /runs/{run_id}/log       captured log of a specific run
    GET  /health                  liveness probe
    GET  /docs                    auto-generated OpenAPI Swagger UI
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api import analytics
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
MINIO_UI_BASE = "http://localhost:9001"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LegalDataPlatform - Ingestion API",
    description=(
        "Self-service CSV upload that detects schema, runs the pipeline, "
        "and returns analytics over the loaded data."
    ),
    version="0.2.0",
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {})


@app.get("/runs/{run_id}/log", response_class=HTMLResponse)
def run_log(request: Request, run_id: str) -> HTMLResponse:
    log_path = RUNS_DIR / f"{run_id}.log"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Run log not found")
    return templates.TemplateResponse(
        request,
        "log.html",
        {"run_id": run_id, "log_text": log_path.read_text(encoding="utf-8", errors="replace")},
    )


# ---------------------------------------------------------------------------
# Analytics API
# ---------------------------------------------------------------------------


@app.get("/api/stats")
def api_stats() -> dict[str, Any]:
    return analytics.fetch_overview()


@app.get("/api/distribution/{kind}")
def api_distribution(kind: str) -> list[dict[str, Any]]:
    if kind == "type":
        return analytics.fetch_distribution_by_type()
    if kind == "jurisdiction":
        return analytics.fetch_distribution_by_jurisdiction()
    if kind == "source":
        return analytics.fetch_distribution_by_source()
    raise HTTPException(status_code=400, detail=f"unknown distribution: {kind}")


@app.get("/api/data/preview")
def api_data_preview(limit: int = 20) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return analytics.fetch_data_preview(limit)


@app.get("/api/partitions")
def api_partitions() -> list[dict[str, Any]]:
    return analytics.fetch_partition_inventory()


@app.get("/api/indexes")
def api_indexes() -> list[dict[str, Any]]:
    return analytics.fetch_index_usage()


@app.get("/api/dq/rules")
def api_dq_rules() -> dict[str, Any]:
    return analytics.fetch_dq_metrics()


# ---------------------------------------------------------------------------
# Upload + run + return rich result
# ---------------------------------------------------------------------------


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only .csv files are supported in this version.",
        )

    upload_id = uuid.uuid4().hex[:12]
    safe_name = Path(file.filename).name
    inbox_path = INBOX_DIR / f"{upload_id}_{safe_name}"
    contents = await file.read()
    inbox_path.write_bytes(contents)
    file_size_kb = round(len(contents) / 1024, 1)

    try:
        with inbox_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            headers = next(reader, [])
            row_count = sum(1 for _ in reader)
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File is not UTF-8. Save as UTF-8 CSV and re-upload.",
        ) from None

    if not headers:
        raise HTTPException(status_code=400, detail="CSV appears to have no header row.")

    match = detect_schema(headers)

    if not match.is_confident:
        return JSONResponse(
            {
                "status": "needs_mapping",
                "upload_id": upload_id,
                "filename": safe_name,
                "file_size_kb": file_size_kb,
                "headers": headers,
                "row_count_in_file": row_count,
                "match": {
                    "best_guess": match.schema,
                    "confidence": round(match.score, 2),
                    "matched_headers": match.matched_headers,
                    "unknown_headers": match.unknown_headers,
                },
                "message": (
                    f"Could not confidently detect schema. Best guess was "
                    f"'{match.schema}' with {match.score:.0%} confidence."
                ),
            },
            status_code=422,
        )

    if match.schema != "legal_documents":
        return JSONResponse(
            {
                "status": "schema_not_implemented",
                "upload_id": upload_id,
                "detected_schema": match.schema,
                "message": (
                    f"Detected schema '{match.schema}' but only 'legal_documents' "
                    "is wired up to the API in this version."
                ),
            },
            status_code=501,
        )

    # Run the pipeline
    run_id = f"{datetime.utcnow():%Y%m%dT%H%M%S}_{upload_id}"
    log_path = RUNS_DIR / f"{run_id}.log"

    started = time.time()
    try:
        completed = _run_pipeline_against(inbox_path, log_path)
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {
                "status": "timeout",
                "upload_id": upload_id,
                "run_id": run_id,
                "message": "Pipeline took longer than 5 minutes; assumed hung.",
            },
            status_code=504,
        )
    duration_seconds = round(time.time() - started, 2)

    summary = _parse_flow_summary(log_path)
    timeline = _parse_stage_timeline(log_path)

    # If the load succeeded, fetch a rich snapshot from PostgreSQL
    if completed.returncode == 0:
        try:
            stats = analytics.fetch_overview()
            preview = analytics.fetch_data_preview(20)
            dist_type = analytics.fetch_distribution_by_type()
            dist_jurisdiction = analytics.fetch_distribution_by_jurisdiction()
            dist_source = analytics.fetch_distribution_by_source()
            partitions = analytics.fetch_partition_inventory()
            indexes = analytics.fetch_index_usage()
            dq = analytics.fetch_dq_metrics()
        except Exception as e:  # noqa: BLE001
            stats = {"error": str(e)}
            preview = []
            dist_type = dist_jurisdiction = dist_source = []
            partitions = []
            indexes = []
            dq = {}
    else:
        stats = {}
        preview = []
        dist_type = dist_jurisdiction = dist_source = []
        partitions = []
        indexes = []
        dq = {}

    response = {
        "status": "completed" if completed.returncode == 0 else "failed",
        "upload_id": upload_id,
        "run_id": run_id,
        "filename": safe_name,
        "file_size_kb": file_size_kb,
        "row_count_in_file": row_count,
        "headers_detected": headers,
        "schema_detected": match.schema,
        "schema_confidence": round(match.score, 2),
        "matched_headers": match.matched_headers,
        "unknown_headers": match.unknown_headers,
        "duration_seconds": duration_seconds,
        "exit_code": completed.returncode,
        "summary": summary,
        "timeline": timeline,
        "post_load_stats": stats,
        "data_preview": preview,
        "distribution": {
            "by_type": dist_type,
            "by_jurisdiction": dist_jurisdiction,
            "by_source": dist_source,
        },
        "infrastructure": {
            "partitions": partitions,
            "indexes": indexes,
        },
        "data_quality": dq,
        "links": {
            "prefect_ui": f"{PREFECT_UI_BASE}/flow-runs",
            "minio_ui": f"{MINIO_UI_BASE}/browser/bronze",
            "logs": f"/runs/{run_id}/log",
        },
    }
    return JSONResponse(response, status_code=200 if completed.returncode == 0 else 500)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _run_pipeline_against(csv_path: Path, log_path: Path) -> subprocess.CompletedProcess:
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
    if not log_path.exists():
        return {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        marker = "Flow summary: "
        idx = line.find(marker)
        if idx >= 0:
            try:
                return json.loads(line[idx + len(marker) :].replace("'", '"'))
            except json.JSONDecodeError:
                continue
    return {}


_TS_RE = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d+)")


def _parse_stage_timeline(log_path: Path) -> list[dict[str, Any]]:
    """Extract Created/Finished events per task to build a stage timeline."""
    if not log_path.exists():
        return []

    events: list[dict[str, Any]] = []
    text = log_path.read_text(encoding="utf-8", errors="replace")

    create_re = re.compile(r"Created task run '([^']+)'")
    finish_re = re.compile(r"Task run '([^']+)' - Finished in state (\w+)")

    starts: dict[str, str] = {}
    for line in text.splitlines():
        ts_m = _TS_RE.search(line)
        if not ts_m:
            continue
        ts = ts_m.group(1)
        cm = create_re.search(line)
        if cm:
            starts[cm.group(1)] = ts
            continue
        fm = finish_re.search(line)
        if fm:
            task_name = fm.group(1)
            state = fm.group(2)
            start_ts = starts.get(task_name)
            duration_ms = None
            if start_ts:
                try:
                    duration_ms = int(
                        (
                            datetime.strptime(ts, "%H:%M:%S.%f")
                            - datetime.strptime(start_ts, "%H:%M:%S.%f")
                        ).total_seconds()
                        * 1000
                    )
                except ValueError:
                    pass
            stage = task_name.rsplit("-", 1)[0]
            events.append(
                {
                    "stage": stage,
                    "start": start_ts,
                    "end": ts,
                    "duration_ms": duration_ms,
                    "state": state,
                }
            )
    return events
