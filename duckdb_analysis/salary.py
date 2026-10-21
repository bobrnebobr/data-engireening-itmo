import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import duckdb

from app.settings import S3Settings, get_s3_settings
from app.storage import validate_run_id
from duckdb_analysis.check import ALIASES_PATH, calculate, configure_s3
from hashlib import sha256


SQL_PATH = Path(__file__).with_name("sql") / "salary.sql"


def prepare_salary(connection) -> None:
    path = SQL_PATH.with_name("salary_prepare.sql")
    for statement in connection.extract_statements(path.read_text(encoding="utf-8")):
        connection.execute(statement).fetchall()


def calculate_salary(connection, min_samples: int = 20) -> None:
    if min_samples < 1:
        raise ValueError("min_samples must be positive")
    prepare_salary(connection)
    for statement in connection.extract_statements(SQL_PATH.read_text(encoding="utf-8")):
        parameters = {"min_samples": min_samples} if statement.named_parameters else None
        connection.execute(statement, parameters).fetchall()
    for direction, operator, order in [("increases", ">", "DESC"), ("decreases", "<", "ASC")]:
        connection.execute(f"""
            CREATE OR REPLACE TEMP VIEW salary_{direction} AS
            SELECT * EXCLUDE (rank_position) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY arity, pay_basis
                    ORDER BY delta_percent {order}, salary_samples DESC, skill_1, skill_2, skill_3
                ) AS rank_position
                FROM salary_effects_flat WHERE delta_rub {operator} 0
            ) WHERE rank_position <= 10
        """).fetchall()


def records(connection, query: str) -> list[dict]:
    result = connection.execute(query)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def run_analysis(settings: S3Settings, run_id: str | None = None, min_samples: int = 20) -> dict:
    if min_samples < 1:
        raise ValueError("min_samples must be positive")
    run_id = run_id or f"salary-{uuid4().hex}"
    validate_run_id(run_id)
    source = f"s3://{settings.s3_bucket}/{settings.s3_input_key}"
    prefix = "/".join(filter(None, [settings.s3_output_prefix.strip("/"), run_id]))
    config = {"threads": 1, "memory_limit": "1GB"}
    if directory := os.environ.get("DUCKDB_EXTENSION_DIRECTORY"):
        config["extension_directory"] = directory
    with TemporaryDirectory(prefix="salary-spill-") as directory:
        config["temp_directory"] = directory
        with duckdb.connect(config=config) as connection:
            configure_s3(connection, settings)
            started = perf_counter()
            calculate(connection, source)
            calculate_salary(connection, min_samples)
            queries = {
                "singles": """SELECT s.skills[1] AS skill, s.pay_basis, f.count AS frequency,
                    s.salary_samples, s.median_salary FROM salary_statistics s
                    JOIN singles f ON f.skill=s.skills[1] WHERE len(s.skills)=1
                    ORDER BY s.pay_basis, skill""",
                "pairs": "SELECT * FROM salary_effects_flat WHERE arity=2 ORDER BY pay_basis, delta_percent DESC, skill_1, skill_2",
                "triples": "SELECT * FROM salary_effects_flat WHERE arity=3 ORDER BY pay_basis, delta_percent DESC, skill_1, skill_2, skill_3",
                "increases": "SELECT * FROM salary_increases ORDER BY arity, pay_basis, delta_percent DESC, skill_1, skill_2, skill_3",
                "decreases": "SELECT * FROM salary_decreases ORDER BY arity, pay_basis, delta_percent, skill_1, skill_2, skill_3",
                "coverage": "SELECT status, pay_basis, count(*) AS vacancies FROM salary_quality GROUP BY status, pay_basis ORDER BY status, pay_basis",
                "pay_groups": "SELECT pay_basis, salary_method, count(*) AS vacancies, median(salary) AS median_salary FROM salary_vacancies GROUP BY pay_basis, salary_method ORDER BY pay_basis, salary_method",
            }
            output = {}
            for name, query in queries.items():
                path = f"s3://{settings.s3_bucket}/{prefix}/salary_{name}.csv"
                connection.sql(query).write_csv(path, header=True)
                output[name] = path
            return {
                "run_id": run_id, "source": source,
                "source_rows": connection.execute("SELECT count(*) FROM source_vacancies").fetchall()[0][0],
                "analyst_rows": connection.execute("SELECT count(*) FROM analyst_vacancies").fetchall()[0][0],
                "skill_aliases_sha256": sha256(ALIASES_PATH.read_bytes()).hexdigest(),
                "aliases": records(connection, "SELECT * FROM skill_aliases ORDER BY alias"),
                "policy": {
                    "currency": "RUR/RUB only; no exchange-rate conversion",
                    "salary_proxy": "midpoint for two valid bounds; existing bound when only one is present",
                    "invalid_bounds": "exclude nonpositive, nonfinite, malformed and inverted bounds",
                    "pay_basis": "gross, net and unknown are separate cohorts; no tax conversion",
                    "min_salary_samples": min_samples,
                    "baseline_frequency_pool": "all analyst vacancies, including those without salary",
                    "pair_baseline": "most frequent constituent skill; lexical tie-break",
                    "triple_baseline": "most frequent constituent pair; also report the most frequent individual skill baseline",
                    "baseline_salary_pool": "same pay basis and salary eligibility rules as the combination",
                    "ranking": "relative median difference, separately by combination size and pay basis",
                    "interpretation": "association, not causal effect; one-sided bounds are salary proxies",
                },
                "coverage": records(connection, queries["coverage"]),
                "pay_groups": records(connection, "SELECT pay_basis, count(*) AS vacancies, median(salary) AS median_salary FROM salary_vacancies GROUP BY pay_basis ORDER BY pay_basis"),
                "qualified_combinations": records(connection, "SELECT arity,pay_basis,count(*) AS combinations FROM salary_effects GROUP BY arity,pay_basis ORDER BY arity,pay_basis"),
                "top_increases": records(connection, queries["increases"]),
                "top_decreases": records(connection, queries["decreases"]),
                "output": output,
                "elapsed_seconds": round(perf_counter() - started, 3),
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Salary association analysis for analyst skill combinations")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()
    result = run_analysis(get_s3_settings(), args.run_id, args.min_samples)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
