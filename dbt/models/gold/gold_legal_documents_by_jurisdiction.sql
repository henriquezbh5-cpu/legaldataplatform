{{ config(
    materialized='table',
    indexes=[
      {'columns': ['jurisdiction', 'document_type']},
      {'columns': ['document_month']}
    ]
) }}

-- Monthly legal-document counts per jurisdiction and type. The SEC EDGAR
-- split vs other sources is preserved so the team can see how much of
-- the volume comes from real APIs vs synthetic feeds.

WITH docs AS (
    SELECT
        jurisdiction,
        document_type,
        document_month,
        is_sec_edgar,
        source_system
    FROM {{ ref('stg_legal_documents') }}
)

SELECT
    jurisdiction,
    document_type,
    document_month,
    count(*)                                       AS documents,
    count(*) FILTER (WHERE is_sec_edgar)           AS sec_edgar_documents,
    count(DISTINCT source_system)                  AS distinct_sources
FROM docs
GROUP BY jurisdiction, document_type, document_month
