CREATE TEMP TABLE source_vacancies AS
SELECT row_number() OVER () AS row_id, name, key_skills, salary_from, salary_to, currency, gross, area
FROM read_csv($source, header = true, all_varchar = true,
              delim = ',', quote = '"', escape = '"');

CREATE TEMP TABLE analyst_vacancies AS
SELECT * FROM source_vacancies
WHERE contains(unicode_casefold(coalesce(name, '')), 'аналитик')
   OR contains(unicode_casefold(coalesce(name, '')), 'analyst');

CREATE TEMP TABLE skill_aliases AS
SELECT alias, canonical FROM read_csv($aliases, header=true, all_varchar=true);

CREATE TEMP TABLE vacancy_skills AS
WITH expanded AS (
    SELECT row_id, unicode_casefold(unicode_strip(skill)) AS skill
    FROM analyst_vacancies,
         unnest(string_split(coalesce(key_skills, ''), ';')) AS tokens(skill)
)
SELECT DISTINCT e.row_id, coalesce(a.canonical, e.skill) AS skill
FROM expanded e LEFT JOIN skill_aliases a ON e.skill = a.alias
WHERE e.skill <> '';
