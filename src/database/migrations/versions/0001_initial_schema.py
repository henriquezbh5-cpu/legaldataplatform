"""initial schema: legal + commercial + dim + staging

Revision ID: 0001
Revises:
Create Date: 2026-04-24 00:00:00

Creates the full schema including:
- Domain tables (legal, commercial)
- Dimension tables (SCD2)
- Staging tables (UNLOGGED)
- Partitioning on high-volume tables
- Full-text and GIN indexes
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Extensions
    # -------------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gin"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "unaccent"')

    # -------------------------------------------------------------------------
    # legal_entities
    # -------------------------------------------------------------------------
    op.create_table(
        "legal_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tax_id", sa.String(50), nullable=False),
        sa.Column("legal_name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("jurisdiction", sa.String(100), nullable=False),
        sa.Column("registration_date", sa.Date),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tax_id", "jurisdiction", name="uq_entity_tax_jurisdiction"),
    )
    op.create_index("ix_legal_entities_tax_id", "legal_entities", ["tax_id"])
    op.execute(
        "CREATE INDEX ix_entity_legal_name_gin ON legal_entities "
        "USING GIN (legal_name gin_trgm_ops)"
    )

    # -------------------------------------------------------------------------
    # legal_documents (PARTITIONED)
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE legal_documents (
            id              UUID        NOT NULL DEFAULT gen_random_uuid(),
            document_date   DATE        NOT NULL,
            source_system   VARCHAR(50) NOT NULL,
            source_id       VARCHAR(200) NOT NULL,
            source_hash     VARCHAR(64) NOT NULL,
            document_type   VARCHAR(50) NOT NULL,
            title           VARCHAR(1000) NOT NULL,
            content         TEXT,
            jurisdiction    VARCHAR(100) NOT NULL,
            entity_id       UUID REFERENCES legal_entities(id),
            tags            JSONB NOT NULL DEFAULT '[]',
            metadata        JSONB NOT NULL DEFAULT '{}',
            ingested_at     TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, document_date),
            CONSTRAINT uq_legal_doc_source
                UNIQUE (source_system, source_id, document_date)
        ) PARTITION BY RANGE (document_date);
    """)
    op.execute("CREATE INDEX ix_legal_doc_date_type ON legal_documents (document_date, document_type)")
    op.execute("CREATE INDEX ix_legal_doc_hash ON legal_documents (source_hash)")
    op.execute("CREATE INDEX ix_legal_doc_entity ON legal_documents (entity_id)")
    op.execute(
        "CREATE INDEX ix_legal_doc_title_gin ON legal_documents "
        "USING GIN (title gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_legal_doc_tags_gin ON legal_documents USING GIN (tags)")
    op.execute(
        "CREATE INDEX ix_legal_doc_metadata_gin ON legal_documents "
        "USING GIN (metadata jsonb_path_ops)"
    )

    # -------------------------------------------------------------------------
    # regulations
    # -------------------------------------------------------------------------
    op.create_table(
        "regulations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("jurisdiction", sa.String(100), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("content", sa.Text),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("code", "jurisdiction", name="uq_regulation_code_jurisdiction"),
    )
    op.create_index(
        "ix_regulation_effective_range",
        "regulations",
        ["effective_from", "effective_to"],
    )

    # -------------------------------------------------------------------------
    # counterparties
    # -------------------------------------------------------------------------
    op.create_table(
        "counterparties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("tax_id", sa.String(50)),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("risk_score", sa.Numeric(5, 2)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("external_id", name="uq_counterparty_external_id"),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_counterparty_risk_range"),
    )
    op.create_index("ix_counterparties_tax_id", "counterparties", ["tax_id"])
    op.create_index(
        "ix_counterparty_country_risk",
        "counterparties",
        ["country_code", "risk_score"],
    )

    # -------------------------------------------------------------------------
    # contracts
    # -------------------------------------------------------------------------
    op.create_table(
        "contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("contract_number", sa.String(100), nullable=False),
        sa.Column("counterparty_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("counterparties.id"), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("total_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("contract_number", name="uq_contract_number"),
        sa.CheckConstraint("total_value >= 0", name="ck_contract_value_positive"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_contract_date_order",
        ),
    )
    op.create_index("ix_contracts_counterparty", "contracts", ["counterparty_id"])
    op.create_index(
        "ix_contract_status_dates",
        "contracts",
        ["status", "start_date", "end_date"],
    )
    op.execute(
        "CREATE INDEX ix_contract_active ON contracts (counterparty_id) "
        "WHERE status = 'ACTIVE'"
    )

    # -------------------------------------------------------------------------
    # transactions (PARTITIONED by month)
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE transactions (
            id                 UUID NOT NULL DEFAULT gen_random_uuid(),
            transaction_date   DATE NOT NULL,
            contract_id        UUID NOT NULL REFERENCES contracts(id),
            counterparty_id    UUID NOT NULL REFERENCES counterparties(id),
            amount             NUMERIC(18, 2) NOT NULL,
            currency           VARCHAR(3) NOT NULL,
            transaction_type   VARCHAR(30) NOT NULL,
            reference          VARCHAR(200) NOT NULL,
            source_system      VARCHAR(50) NOT NULL,
            ingested_at        TIMESTAMPTZ NOT NULL,
            metadata           JSONB NOT NULL DEFAULT '{}',
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, transaction_date),
            CONSTRAINT uq_transaction_source_ref
                UNIQUE (source_system, reference, transaction_date),
            CONSTRAINT ck_transaction_amount_nonzero CHECK (amount <> 0)
        ) PARTITION BY RANGE (transaction_date);
    """)
    op.execute("CREATE INDEX ix_txn_counterparty_date ON transactions (counterparty_id, transaction_date)")
    op.execute("CREATE INDEX ix_txn_contract_date ON transactions (contract_id, transaction_date)")
    op.execute(
        "CREATE INDEX ix_txn_date_brin ON transactions "
        "USING BRIN (transaction_date) WITH (pages_per_range = 32)"
    )

    # -------------------------------------------------------------------------
    # dim_counterparty (SCD2)
    # -------------------------------------------------------------------------
    op.create_table(
        "dim_counterparty",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("tax_id", sa.String(50)),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("risk_score", sa.Numeric(5, 2)),
        sa.Column("attributes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=False, server_default="9999-12-31"),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "external_id", "valid_from",
            name="uq_dim_counterparty_version",
        ),
    )
    op.create_index("ix_dim_counterparty_external_id", "dim_counterparty", ["external_id"])
    op.execute(
        "CREATE INDEX ix_dim_counterparty_current ON dim_counterparty "
        "(external_id) WHERE is_current = true"
    )
    op.create_index(
        "ix_dim_counterparty_valid_range",
        "dim_counterparty",
        ["external_id", "valid_from", "valid_to"],
    )

    # -------------------------------------------------------------------------
    # dim_jurisdiction
    # -------------------------------------------------------------------------
    op.create_table(
        "dim_jurisdiction",
        sa.Column("code", sa.String(10), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("legal_system", sa.String(50), nullable=False),
        sa.Column("attributes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # -------------------------------------------------------------------------
    # Staging (UNLOGGED)
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE UNLOGGED TABLE stg_legal_document (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id        VARCHAR(64) NOT NULL,
            source_system   VARCHAR(50) NOT NULL,
            source_payload  JSONB NOT NULL,
            raw_text        TEXT,
            extracted_at    TIMESTAMPTZ NOT NULL,
            processed       BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    op.create_index("ix_stg_legal_batch_processed", "stg_legal_document", ["batch_id", "processed"])

    op.execute("""
        CREATE UNLOGGED TABLE stg_transaction (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id        VARCHAR(64) NOT NULL,
            source_system   VARCHAR(50) NOT NULL,
            source_payload  JSONB NOT NULL,
            extracted_at    TIMESTAMPTZ NOT NULL,
            processed       BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    op.create_index("ix_stg_txn_batch_processed", "stg_transaction", ["batch_id", "processed"])


def downgrade() -> None:
    op.drop_table("stg_transaction")
    op.drop_table("stg_legal_document")
    op.drop_table("dim_jurisdiction")
    op.drop_table("dim_counterparty")
    op.execute("DROP TABLE IF EXISTS transactions CASCADE")
    op.drop_table("contracts")
    op.drop_table("counterparties")
    op.drop_table("regulations")
    op.execute("DROP TABLE IF EXISTS legal_documents CASCADE")
    op.drop_table("legal_entities")
