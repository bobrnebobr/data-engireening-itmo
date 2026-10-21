-- Keep gross, net and unknown pay bases separate; do not invent exchange rates or tax rates.
CREATE OR REPLACE TEMP TABLE salary_quality AS
WITH parsed AS (
    SELECT row_id, upper(trim(coalesce(currency, ''))) AS currency,
           nullif(trim(salary_from), '') AS raw_from,
           nullif(trim(salary_to), '') AS raw_to,
           try_cast(nullif(trim(salary_from), '') AS DOUBLE) AS low,
           try_cast(nullif(trim(salary_to), '') AS DOUBLE) AS high,
           CASE try_cast(gross AS BOOLEAN)
               WHEN true THEN 'gross' WHEN false THEN 'net' ELSE 'unknown'
           END AS pay_basis
    FROM analyst_vacancies
)
SELECT *,
       CASE
           WHEN raw_from IS NULL AND raw_to IS NULL THEN 'salary_missing'
           WHEN currency NOT IN ('RUR', 'RUB') THEN 'non_ruble_or_missing_currency'
           WHEN (raw_from IS NOT NULL AND (low IS NULL OR NOT isfinite(low) OR low <= 0))
             OR (raw_to IS NOT NULL AND (high IS NULL OR NOT isfinite(high) OR high <= 0))
               THEN 'invalid_salary_bounds'
           WHEN low IS NOT NULL AND high IS NOT NULL AND low > high THEN 'inverted_range'
           ELSE 'eligible'
       END AS status
FROM parsed;

CREATE OR REPLACE TEMP TABLE salary_vacancies AS
SELECT row_id, pay_basis,
       CASE WHEN low IS NOT NULL AND high IS NOT NULL THEN (low + high) / 2
            ELSE coalesce(low, high) END AS salary,
       CASE WHEN low IS NOT NULL AND high IS NOT NULL THEN 'range_midpoint'
            WHEN low IS NOT NULL THEN 'lower_bound_only' ELSE 'upper_bound_only' END AS salary_method
FROM salary_quality WHERE status = 'eligible';
