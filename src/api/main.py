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
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import traceback

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api import analytics
from src.api.processor import process_csv
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
# Global exception handlers — guarantee JSON on every error so the front-end
# never has to parse HTML. Logs the full traceback on the server side.
# ---------------------------------------------------------------------------


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        {"status": "error", "code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        {"status": "error", "code": 422, "detail": "validation failed", "errors": exc.errors()},
        status_code=422,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    print("=" * 60)
    print(f"UNHANDLED EXCEPTION on {request.method} {request.url.path}")
    print("".join(tb))
    print("=" * 60)
    return JSONResponse(
        {
            "status": "error",
            "code": 500,
            "detail": str(exc),
            "exception_type": type(exc).__name__,
        },
        status_code=500,
    )


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

    # Run the pipeline directly (sync, in-process)
    run_id = f"{datetime.utcnow():%Y%m%dT%H%M%S}_{upload_id}"
    log_path = RUNS_DIR / f"{run_id}.log"

    started = time.time()
    try:
        result = process_csv(inbox_path, pipeline_name="api_upload")
        run_status = "completed"
        run_error: str | None = None
    except Exception as e:  # noqa: BLE001
        run_status = "failed"
        run_error = str(e)
        result = {
            "extracted": row_count,
            "valid": 0,
            "rejected": 0,
            "loaded": 0,
            "timeline": [],
            "dq_failures": [run_error],
        }
    duration_seconds = round(time.time() - started, 2)

    # Persist a small log for the /runs/{id}/log page
    log_path.write_text(
        f"upload_id={upload_id}\nfilename={safe_name}\nstatus={run_status}\n"
        f"duration_seconds={duration_seconds}\n"
        f"summary={json.dumps({k: v for k, v in result.items() if k != 'timeline'}, default=str)}\n"
        + (f"error={run_error}\n" if run_error else ""),
        encoding="utf-8",
    )

    summary = {
        "extracted": result.get("extracted", 0),
        "valid": result.get("valid", 0),
        "rejected": result.get("rejected", 0),
        "loaded": result.get("loaded", 0),
    }
    timeline = result.get("timeline", [])

    # Fetch the post-load analytics snapshot
    if run_status == "completed":
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
        "status": run_status,
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
        "summary": summary,
        "timeline": timeline,
        "error": run_error,
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
    return JSONResponse(
        jsonable_encoder(response),
        status_code=200 if run_status == "completed" else 500,
    )


# Subprocess-based pipeline trigger removed in favor of in-process processor
# (src.api.processor). It avoids asyncpg + Windows event-loop issues and
# returns timing/counts directly. Older parsing helpers were here.
