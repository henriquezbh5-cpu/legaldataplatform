-- Staging view over counterparties — exposes only the columns gold cares about
-- and classifies the origin (GLEIF vs seed) for downstream slicing.

WITH src AS (
    SELECT
        id                 AS counterparty_id,
        external_id,
        name,
        tax_id,
        upper(country_code) AS country_code,
        risk_score,
        CASE
            WHEN external_id LIKE 'LEI-%' THEN 'GLEIF'
            WHEN external_id LIKE 'CP-%'  THEN 'SEED'
            ELSE 'OTHER'
        END               AS source_origin,
        metadata
    FROM {{ source('public', 'counterparties') }}
)

SELECT * FROM src
