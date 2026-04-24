-- Extensions required by the data model
-- Run once at database initialization

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";          -- trigram indexes for fuzzy text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";        -- composite GIN indexes
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- query performance tracking
CREATE EXTENSION IF NOT EXISTS "unaccent";         -- accent-insensitive text normalization

-- Optional but recommended if available
-- CREATE EXTENSION IF NOT EXISTS "pg_partman";     -- automated partition management
