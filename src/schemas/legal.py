"""Pydantic schemas for the legal domain.

Validators enforce normalization rules at ingestion time so invalid data
never reaches the silver/gold layer. This is the first quality gate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

TaxID = Annotated[str, StringConstraints(min_length=5, max_length=50, strip_whitespace=True)]
Jurisdiction = Annotated[
    str, StringConstraints(min_length=2, max_length=100, strip_whitespace=True)
]


class LegalEntitySchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    tax_id: TaxID
    legal_name: Annotated[str, Field(min_length=1, max_length=500)]
    entity_type: Annotated[str, Field(min_length=1, max_length=50)]
    jurisdiction: Jurisdiction
    registration_date: date | None = None
    status: str = "ACTIVE"
    metadata_: dict = Field(default_factory=dict, alias="metadata")

    @field_validator("legal_name")
    @classmethod
    def _normalize_name(cls, v: str) -> str:
        # Uppercase for deterministic deduplication; keep original in metadata
        return " ".join(v.upper().split())

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        allowed = {"ACTIVE", "INACTIVE", "DISSOLVED", "SUSPENDED"}
        up = v.upper()
        if up not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return up


class LegalDocumentSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    document_date: date
    source_system: Annotated[str, Field(min_length=1, max_length=50)]
    source_id: Annotated[str, Field(min_length=1, max_length=200)]
    source_hash: Annotated[str, Field(min_length=64, max_length=64)]
    document_type: Annotated[str, Field(min_length=1, max_length=50)]
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    content: str | None = None
    jurisdiction: Jurisdiction
    entity_tax_id: str | None = None  # Resolved to entity_id during transform
    tags: list[str] = Field(default_factory=list)
    metadata_: dict = Field(default_factory=dict, alias="metadata")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("document_type")
    @classmethod
    def _upper_type(cls, v: str) -> str:
        return v.upper()

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, tags: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in tags:
            normalized = t.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
        return out


class RegulationSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    code: Annotated[str, Field(min_length=1, max_length=100)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    jurisdiction: Jurisdiction
    effective_from: date
    effective_to: date | None = None
    category: Annotated[str, Field(min_length=1, max_length=100)]
    content: str | None = None
    metadata_: dict = Field(default_factory=dict, alias="metadata")

    @field_validator("effective_to")
    @classmethod
    def _check_range(cls, v: date | None, info: object) -> date | None:
        # Pydantic v2 provides values via info.data
        data = getattr(info, "data", {})
        if v and data.get("effective_from") and v < data["effective_from"]:
            raise ValueError("effective_to must be >= effective_from")
        return v
