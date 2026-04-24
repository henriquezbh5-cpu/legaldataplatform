-- Application roles with least-privilege separation
-- Run once at initialization

-- Read-only role for BI / analysts
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ldp_readonly') THEN
        CREATE ROLE ldp_readonly;
    END IF;
END $$;

-- ETL role — can write to staging/dim/fact but cannot drop objects
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ldp_etl') THEN
        CREATE ROLE ldp_etl;
    END IF;
END $$;

-- Grant connect on the current DB
GRANT CONNECT ON DATABASE legaldata TO ldp_readonly, ldp_etl;
GRANT USAGE ON SCHEMA public TO ldp_readonly, ldp_etl;

-- Default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO ldp_readonly;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ldp_etl;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ldp_etl;
