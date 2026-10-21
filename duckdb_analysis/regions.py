import argparse
from hashlib import sha256
import json
import os
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import duckdb

from app.settings import S3Settings, get_s3_settings
from app.storage import validate_run_id
from duckdb_analysis.check import ALIASES_PATH, calculate_frequencies, configure_s3, prepare_data
from duckdb_analysis.salary import calculate_salary, records


DEFAULT_REGIONS = ['Москва', 'Санкт-Петербург', 'Екатеринбург']

REGION_QUERIES = {
    'overview': """
        SELECT count(*) AS vacancies,
            count(k.row_id) AS vacancies_with_skills,
            count(*) FILTER (WHERE q.raw_from IS NOT NULL OR q.raw_to IS NOT NULL) AS declared_salary_vacancies,
            100.0 * count(*) FILTER (WHERE q.raw_from IS NOT NULL OR q.raw_to IS NOT NULL)
                / nullif(count(*),0) AS declared_salary_percent,
            count(s.row_id) AS ruble_salary_vacancies,
            100.0 * count(s.row_id) / nullif(count(*),0) AS ruble_salary_percent,
            count(*) FILTER (WHERE s.pay_basis='net') AS net_salary_samples,
            median(s.salary) FILTER (WHERE s.pay_basis='net') AS net_median_salary,
            count(*) FILTER (WHERE s.pay_basis='gross') AS gross_salary_samples,
            median(s.salary) FILTER (WHERE s.pay_basis='gross') AS gross_median_salary,
            count(*) FILTER (WHERE s.pay_basis='unknown') AS unknown_basis_samples,
            median(s.salary) FILTER (WHERE s.pay_basis='unknown') AS unknown_basis_median_salary
        FROM analyst_vacancies a
        LEFT JOIN (SELECT DISTINCT row_id FROM vacancy_skills) k USING(row_id)
        LEFT JOIN salary_quality q USING(row_id)
        LEFT JOIN salary_vacancies s USING(row_id)
    """,
    'frequencies': """
        WITH counts AS (
            SELECT 1 AS arity, skill AS skill_1, NULL::VARCHAR AS skill_2,
                   NULL::VARCHAR AS skill_3, count AS frequency FROM singles
            UNION ALL SELECT 2, skill_1, skill_2, NULL::VARCHAR, count FROM pairs
            UNION ALL SELECT 3, skill_1, skill_2, skill_3, count FROM triples
        )
        SELECT *, (SELECT count(*) FROM analyst_vacancies) AS region_vacancies,
               100.0 * frequency / nullif((SELECT count(*) FROM analyst_vacancies),0) AS share_percent
        FROM counts
    """,
    'salary_singles': """
        SELECT s.skills[1] AS skill, s.pay_basis, f.count AS frequency,
               s.salary_samples, s.median_salary
        FROM salary_statistics s JOIN singles f ON f.skill=s.skills[1]
        WHERE len(s.skills)=1
    """,
    'salary_effects': 'SELECT * FROM salary_effects_flat',
    'salary_increases': 'SELECT * FROM salary_increases',
    'salary_decreases': 'SELECT * FROM salary_decreases',
    'salary_coverage': """
        SELECT status,pay_basis,count(*) AS vacancies
        FROM salary_quality GROUP BY status,pay_basis
    """,
}


def calculate_regions(connection, regions: list[str], min_samples: int = 20) -> None:
    if len(regions) != 3 or any(not region.strip() for region in regions):
        raise ValueError('Exactly three nonempty regions are required')
    if len({region.strip().casefold() for region in regions}) != 3:
        raise ValueError('Regions must be distinct')
    if min_samples < 1:
        raise ValueError('min_samples must be positive')
    # Preserve the full normalized input; all subsequent counts use the current city.
    connection.execute('ALTER TABLE analyst_vacancies RENAME TO all_analyst_vacancies').fetchall()
    connection.execute('ALTER TABLE vacancy_skills RENAME TO all_vacancy_skills').fetchall()
    for index, region in enumerate(regions):
        connection.execute("""
            CREATE OR REPLACE TEMP TABLE analyst_vacancies AS
            SELECT * FROM all_analyst_vacancies
            WHERE unicode_casefold(unicode_strip(coalesce(area,''))) =
                  unicode_casefold(unicode_strip($region))
        """, {'region': region}).fetchall()
        connection.execute("""
            CREATE OR REPLACE TEMP TABLE vacancy_skills AS
            SELECT s.* FROM all_vacancy_skills s JOIN analyst_vacancies a USING(row_id)
        """).fetchall()
        calculate_frequencies(connection)
        calculate_salary(connection, min_samples)
        for name, query in REGION_QUERIES.items():
            select = f'SELECT $region AS region, * FROM ({query})'
            statement = (f'CREATE TEMP TABLE regional_{name} AS {select}' if index == 0
                         else f'INSERT INTO regional_{name} {select}')
            connection.execute(statement, {'region': region}).fetchall()

    connection.execute("""
        CREATE TEMP VIEW regional_top_frequency AS
        SELECT * EXCLUDE(rank_position) FROM (
            SELECT *,row_number() OVER (
                PARTITION BY region,arity ORDER BY frequency DESC,skill_1,skill_2,skill_3
            ) AS rank_position FROM regional_frequencies
        ) WHERE rank_position<=10
    """).fetchall()
    connection.execute("""
        CREATE TEMP VIEW regional_frequency_comparison AS
        WITH keys AS (
            SELECT DISTINCT arity,skill_1,skill_2,skill_3 FROM regional_top_frequency
        )
        SELECT r.region,k.*,coalesce(f.frequency,0) AS frequency,
               r.vacancies AS region_vacancies,
               100.0*coalesce(f.frequency,0)/nullif(r.vacancies,0) AS share_percent
        FROM regional_overview r CROSS JOIN keys k
        LEFT JOIN regional_frequencies f ON f.region=r.region AND f.arity=k.arity
            AND f.skill_1=k.skill_1
            AND f.skill_2 IS NOT DISTINCT FROM k.skill_2
            AND f.skill_3 IS NOT DISTINCT FROM k.skill_3
    """).fetchall()


def run_analysis(settings: S3Settings, regions: list[str], run_id: str | None = None,
                 min_samples: int = 20) -> dict:
    regions = [region.strip() for region in regions]
    if len(regions) != 3 or any(not r for r in regions) or len(set(r.casefold() for r in regions)) != 3:
        raise ValueError('Exactly three distinct nonempty regions are required')
    if min_samples < 1:
        raise ValueError('min_samples must be positive')
    run_id = run_id or f'regions-{uuid4().hex}'
    validate_run_id(run_id)
    source = f's3://{settings.s3_bucket}/{settings.s3_input_key}'
    prefix = '/'.join(filter(None,[settings.s3_output_prefix.strip('/'),run_id]))
    config = {'threads':1,'memory_limit':'1GB'}
    if directory := os.environ.get('DUCKDB_EXTENSION_DIRECTORY'):
        config['extension_directory'] = directory
    with TemporaryDirectory(prefix='regions-spill-') as directory:
        config['temp_directory'] = directory
        with duckdb.connect(config=config) as connection:
            configure_s3(connection,settings)
            started = perf_counter()
            prepare_data(connection,source)
            calculate_regions(connection,regions,min_samples)
            queries = {
                'overview':'SELECT * FROM regional_overview ORDER BY region',
                'singles':'SELECT * FROM regional_frequencies WHERE arity=1 ORDER BY region,frequency DESC,skill_1',
                'pairs':'SELECT * FROM regional_frequencies WHERE arity=2 ORDER BY region,frequency DESC,skill_1,skill_2',
                'triples':'SELECT * FROM regional_frequencies WHERE arity=3 ORDER BY region,frequency DESC,skill_1,skill_2,skill_3',
                'top_frequency':'SELECT * FROM regional_top_frequency ORDER BY region,arity,frequency DESC,skill_1,skill_2,skill_3',
                'frequency_comparison':'SELECT * FROM regional_frequency_comparison ORDER BY arity,skill_1,skill_2,skill_3,region',
                'salary_singles':'SELECT * FROM regional_salary_singles ORDER BY region,pay_basis,skill',
                'salary_effects':'SELECT * FROM regional_salary_effects ORDER BY region,arity,pay_basis,delta_percent DESC,skill_1,skill_2,skill_3',
                'salary_increases':'SELECT * FROM regional_salary_increases ORDER BY region,arity,pay_basis,delta_percent DESC,skill_1,skill_2,skill_3',
                'salary_decreases':'SELECT * FROM regional_salary_decreases ORDER BY region,arity,pay_basis,delta_percent,skill_1,skill_2,skill_3',
                'salary_coverage':'SELECT * FROM regional_salary_coverage ORDER BY region,status,pay_basis',
            }
            output = {}
            for name,query in queries.items():
                path = f's3://{settings.s3_bucket}/{prefix}/regional_{name}.csv'
                connection.sql(query).write_csv(path,header=True)
                output[name] = path
            overview = {row['region']:row for row in records(connection,queries['overview'])}
            return {
                'run_id':run_id,'source':source,'regions':regions,
                'source_rows':connection.execute('SELECT count(*) FROM source_vacancies').fetchall()[0][0],
                'analyst_rows':connection.execute('SELECT count(*) FROM all_analyst_vacancies').fetchall()[0][0],
                'skill_aliases_sha256':sha256(ALIASES_PATH.read_bytes()).hexdigest(),
                'policy':{
                    'region':'Exact area value after Unicode casefold/strip; city rather than surrounding oblast',
                    'frequency_denominator':'All analyst vacancies in each city, including those without skills or salary',
                    'salary':'RUR/RUB; midpoint or available bound; same eligibility as salary analysis',
                    'pay_basis':'net, gross and unknown are separate cohorts',
                    'min_salary_samples':min_samples,
                    'baseline':'Most frequent constituent skill/pair within the same city; medians within same city and pay basis',
                    'inference':'Descriptive associations; no adjustment for role, experience or employer',
                },
                'overview':[overview[region] for region in regions],
                'frequency_summary':records(connection,'SELECT region,arity,count(*) AS unique_combinations,sum(frequency)::BIGINT AS occurrences FROM regional_frequencies GROUP BY region,arity ORDER BY region,arity'),
                'top_frequency':records(connection,queries['top_frequency']),
                'frequency_comparison':records(connection,queries['frequency_comparison']),
                'salary_increases':records(connection,queries['salary_increases']),
                'salary_decreases':records(connection,queries['salary_decreases']),
                'qualified_combinations':records(connection,'SELECT region,arity,pay_basis,count(*) AS combinations FROM regional_salary_effects GROUP BY region,arity,pay_basis ORDER BY region,arity,pay_basis'),
                'output':output,'elapsed_seconds':round(perf_counter()-started,3),
            }


def main() -> None:
    parser = argparse.ArgumentParser(description='Compare analyst vacancies in three regions')
    parser.add_argument('--regions',nargs=3,default=DEFAULT_REGIONS)
    parser.add_argument('--run-id',default=None)
    parser.add_argument('--min-samples',type=int,default=20)
    args = parser.parse_args()
    print(json.dumps(run_analysis(get_s3_settings(),args.regions,args.run_id,args.min_samples),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
