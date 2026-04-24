-- Staging view over legal_documents, unifying CSV seed and real SEC EDGAR
-- filings under a consistent interface.

WITH src AS (
    SELECT
        id                   AS document_uuid,
        document_date,
        source_system,
        source_id,
        source_hash,
        document_type,
        title,
        jurisdiction,
        tags,
        metadata,
        ingested_at
    FROM {{ source('public', 'legal_documents') }}
)

SELECT
    document_uuid,
    document_date,
    source_system,
    source_id,
    source_hash,
    document_type,
    title,
    jurisdiction,
    tags,
    metadata,
    ingested_at,
    (source_system = 'sec_edgar') AS is_sec_edgar,
    date_trunc('month', document_date)::date AS document_month
FROM src
