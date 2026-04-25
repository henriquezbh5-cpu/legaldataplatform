"""Sync, in-process CSV processor for the upload API.

Mirrors the legal ingestion flow but without Prefect / asyncio so it
runs cleanly inside a FastAPI request handler on Windows. The trade-off:
no Prefect run is recorded for these uploads. That's OK for the demo
console — we still expose a 'View flow run in Prefect' link to the
catalog of background runs.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import psycopg

from src.config import get_settings
from src.data_quality import run_rules
from src.data_quality.validators.rule_engine import assert_no_errors, load_rules_yaml
from src.pipelines.transformers import normalize_legal


# ---------------------------------------------------------------------------
# Helpers reused from the flow
# ---------------------------------------------------------------------------


def _map_legal_doc_csv(row: dict[str, Any]) -> dict[str, Any]:
    src_id = row.get("doc_id") or row.get("source_id") or ""
    doc_date = row.get("date") or row.get("document_date")
    source_system = row.get("source_system", "api_upload")
    canonical = f"{source_system}|{src_id}|{doc_date}".encode()
    source_hash = hashlib.sha256(canonical).hexdigest()
    return {
        "document_date": doc_date,
        "source_system": source_system,
        "source_id": str(src_id),
        "source_hash": source_hash,
        "document_type": row.get("type") or row.get("document_type") or "NOTICE",
        "title": row.get("title", ""),
        "content": row.get("content") or row.get("body"),
        "jurisdiction": row.get("jurisdiction", "UNKNOWN"),
        "tags": row.get("tags", []) or [],
        "metadata": {"original_source_row": row},
    }


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _dsn() -> str:
    s = get_settings().postgres
    return f"host={s.host} port={s.port} user={s.user} password={s.password} dbname={s.db}"


# ---------------------------------------------------------------------------
# Pipeline stages — all sync, all in-process
# ---------------------------------------------------------------------------


def process_csv(csv_path: Path, pipeline_name: str = "api_upload") -> dict[str, Any]:
    """Read, validate, normalize, load. Return per-stage timing + counts.

    Raises RuntimeError on any unrecoverable error — caller should catch
    and turn into HTTP 500 JSON.
    """
    timeline: list[dict[str, Any]] = []

    # ---- 1) Extract ---------------------------------------------------------
    t0 = time.perf_counter()
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        raw_rows = list(reader)
    t_extract = time.perf_counter() - t0
    timeline.append({"stage": "extract_from_csv", "duration_ms": int(t_extract * 1000), "state": "Completed"})

    if not raw_rows:
        raise RuntimeError("CSV has no data rows")

    # ---- 2) Map columns to schema ------------------------------------------
    mapped = [_map_legal_doc_csv(r) for r in raw_rows]

    # ---- 3) Normalize + validate (Pydantic) --------------------------------
    t0 = time.perf_counter()
    norm_result = normalize_legal("document", mapped, pipeline=pipeline_name)
    t_normalize = time.perf_counter() - t0
    timeline.append(
        {"stage": "normalize_and_validate", "duration_ms": int(t_normalize * 1000), "state": "Completed"}
    )

    valid_records = norm_result.valid
    rejected_records = norm_result.rejected

    # ---- 4) YAML DQ rules --------------------------------------------------
    t0 = time.perf_counter()
    if valid_records:
        df = pl.DataFrame(valid_records)
        rules = load_rules_yaml("src/data_quality/rules/legal_documents.yaml")
        try:
            results = run_rules(df, rules, suite=pipeline_name)
            assert_no_errors(results)
            dq_failures: list[str] = []
        except AssertionError as e:
            dq_failures = [str(e)]
            valid_records = []
    else:
        dq_failures = []
    t_dq = time.perf_counter() - t0
    timeline.append({"stage": "dq_rules", "duration_ms": int(t_dq * 1000), "state": "Completed"})

    # ---- 5) Load to PostgreSQL via COPY + UPSERT ---------------------------
    t0 = time.perf_counter()
    loaded_count = 0
    if valid_records:
        loaded_count = _load_to_postgres(valid_records)
    t_load = time.perf_counter() - t0
    timeline.append(
        {"stage": "load_legal_documents", "duration_ms": int(t_load * 1000), "state": "Completed"}
    )

    # ---- 6) Refresh Gold (best-effort) -------------------------------------
    t0 = time.perf_counter()
    try:
        _refresh_gold()
        gold_state = "Completed"
    except Exception:  # noqa: BLE001
        gold_state = "Skipped"
    t_gold = time.perf_counter() - t0
    timeline.append({"stage": "refresh_gold", "duration_ms": int(t_gold * 1000), "state": gold_state})

    return {
        "extracted": len(raw_rows),
        "valid": len(valid_records),
        "rejected": len(rejected_records),
        "loaded": loaded_count,
        "timeline": timeline,
        "dq_failures": dq_failures,
    }


def _load_to_postgres(records: list[dict[str, Any]]) -> int:
    """COPY into staging then UPSERT into legal_documents. Returns row count."""
    now = datetime.utcnow()
    for r in records:
        r.setdefault("ingested_at", now)
        r.setdefault("tags", [])
        r.setdefault("metadata", {})

    columns = [
        "document_date",
        "source_system",
        "source_id",
        "source_hash",
        "document_type",
        "title",
        "content",
        "jurisdiction",
        "tags",
        "metadata",
        "ingested_at",
    ]
    filtered = [{k: r.get(k) for k in columns} for r in records]
    col_list = ", ".join(columns)
    set_clause = ", ".join(
        f"{c} = EXCLUDED.{c}"
        for c in columns
        if c not in ("source_system", "source_id", "document_date")
    )

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE legal_documents_stg "
            "(LIKE legal_documents INCLUDING DEFAULTS) ON COMMIT DROP"
        )

        copy_sql = f"COPY legal_documents_stg ({col_list}) FROM STDIN WITH (FORMAT csv)"
        with cur.copy(copy_sql) as cp:
            for rec in filtered:
                row = [_serialize(rec.get(c)) for c in columns]
                buf = io.StringIO()
                csv.writer(buf, quoting=csv.QUOTE_MINIMAL).writerow(row)
                cp.write(buf.getvalue().encode("utf-8"))

        cur.execute(
            f"""
            INSERT INTO legal_documents ({col_list})
            SELECT {col_list} FROM legal_documents_stg
            ON CONFLICT (source_system, source_id, document_date)
            DO UPDATE SET {set_clause}, updated_at = now()
            """
        )
        conn.commit()

    return len(records)


def _refresh_gold() -> None:
    """Refresh the materialized view (idempotent)."""
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT relispopulated FROM pg_class "
            "WHERE relname = 'mv_monthly_revenue_per_counterparty'"
        )
        row = cur.fetchone()
        if row and not row[0]:
            cur.execute("REFRESH MATERIALIZED VIEW mv_monthly_revenue_per_counterparty")
        cur.execute("CALL refresh_analytical_views()")
