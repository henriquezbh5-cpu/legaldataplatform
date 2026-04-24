"""Slowly Changing Dimension Type 2 (SCD2) handler.

SCD2 preserves full history of changes. When an attribute of a tracked entity
changes, a new version is inserted and the previous version's `valid_to`
is set to the day before the change. `is_current = true` marks the latest row.

This implementation uses a row_hash over tracked columns to detect changes
efficiently, avoiding column-by-column comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.observability import get_logger
from src.pipelines.transformers.enrichers import compute_row_hash

logger = get_logger(__name__)


@dataclass
class Scd2Config:
    table: str                      # e.g. "dim_counterparty"
    natural_key: str                # e.g. "external_id"
    tracked_fields: list[str]       # fields that trigger a new version when changed
    insert_fields: list[str]        # all fields to insert
    hash_field: str = "row_hash"


class Scd2Handler:
    """Applies SCD2 logic for a dimension table."""

    def __init__(self, session: AsyncSession, config: Scd2Config) -> None:
        self.session = session
        self.config = config

    async def apply(
        self,
        records: list[dict[str, Any]],
        effective_date: date | None = None,
    ) -> dict[str, int]:
        """Process records, returning counts of inserted / expired / unchanged."""
        effective_date = effective_date or date.today()
        inserted = expired = unchanged = 0

        for record in records:
            natural_key_value = record[self.config.natural_key]
            new_hash = compute_row_hash(record, self.config.tracked_fields)
            record[self.config.hash_field] = new_hash

            existing = await self._fetch_current(natural_key_value)

            if existing is None:
                # New entity → insert as current
                await self._insert_current(record, effective_date)
                inserted += 1
            elif existing[self.config.hash_field] == new_hash:
                unchanged += 1
            else:
                # Change detected → expire old, insert new
                await self._expire(natural_key_value, effective_date)
                await self._insert_current(record, effective_date)
                expired += 1
                inserted += 1

        logger.info(
            "scd2.applied",
            table=self.config.table,
            inserted=inserted,
            expired=expired,
            unchanged=unchanged,
        )
        return {"inserted": inserted, "expired": expired, "unchanged": unchanged}

    async def _fetch_current(self, natural_key_value: Any) -> dict[str, Any] | None:
        sql = text(f"""
            SELECT *
              FROM {self.config.table}
             WHERE {self.config.natural_key} = :nk
               AND is_current = true
        """)  # table/col names are internal (not user input)
        row = (await self.session.execute(sql, {"nk": natural_key_value})).first()
        return dict(row._mapping) if row else None

    async def _expire(self, natural_key_value: Any, effective_date: date) -> None:
        valid_to = effective_date - timedelta(days=1)
        sql = text(f"""
            UPDATE {self.config.table}
               SET is_current = false,
                   valid_to   = :valid_to
             WHERE {self.config.natural_key} = :nk
               AND is_current = true
        """)
        await self.session.execute(sql, {"nk": natural_key_value, "valid_to": valid_to})

    async def _insert_current(self, record: dict[str, Any], effective_date: date) -> None:
        fields = self.config.insert_fields + [
            "valid_from", "valid_to", "is_current", self.config.hash_field, "loaded_at",
        ]
        placeholders = ", ".join(f":{f}" for f in fields)
        col_list = ", ".join(fields)

        params = {f: record.get(f) for f in self.config.insert_fields}
        params[self.config.hash_field] = record[self.config.hash_field]
        params["valid_from"] = effective_date
        params["valid_to"] = date(9999, 12, 31)
        params["is_current"] = True
        params["loaded_at"] = datetime.utcnow()

        sql = text(f"INSERT INTO {self.config.table} ({col_list}) VALUES ({placeholders})")
        await self.session.execute(sql, params)
