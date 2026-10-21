import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import duckdb

from app.settings import S3Settings, get_s3_settings
from app.storage import validate_run_id


TABLES = {
    "singles": ["skill"],
    "pairs": ["skill_1", "skill_2"],
    "triples": ["skill_1", "skill_2", "skill_3"],
}
ALIASES_PATH = Path(__file__).resolve().parents[1] / "config" / "skill_aliases.csv"
SQL_PATH = Path(__file__).with_name("sql") / "frequencies.sql"


def register_text_functions(connection) -> None:
    connection.create_function("unicode_casefold", lambda value: value.casefold(), ["VARCHAR"], "VARCHAR")
    connection.create_function("unicode_strip", lambda value: value.strip(), ["VARCHAR"], "VARCHAR")


def prepare_data(connection, source: str) -> None:
    register_text_functions(connection)
    path = SQL_PATH.with_name("prepare.sql")
    for statement in connection.extract_statements(path.read_text(encoding="utf-8")):
        values = {"source": source, "aliases": str(ALIASES_PATH)}
        parameters = {key: values[key] for key in statement.named_parameters} if statement.named_parameters else None
        connection.execute(statement, parameters).fetchall()


def calculate_frequencies(connection) -> None:
    for statement in connection.extract_statements(SQL_PATH.read_text(encoding="utf-8")):
        connection.execute(statement).fetchall()


def calculate(connection, source: str) -> None:
    prepare_data(connection, source)
    calculate_frequencies(connection)


def configure_s3(connection, settings: S3Settings) -> None:
    connection.install_extension("httpfs")
    connection.load_extension("httpfs")
    endpoint = str(settings.s3_endpoint).rstrip("/").split("://", 1)[1]
    connection.execute("""
        CREATE SECRET rustfs (
            TYPE S3, KEY_ID $access_key, SECRET $secret_key,
            REGION $region, ENDPOINT $endpoint, URL_STYLE 'path', USE_SSL $use_ssl
        )
    """, {
        "access_key": settings.s3_access_key,
        "secret_key": settings.s3_secret_key.get_secret_value(),
        "region": settings.s3_region,
        "endpoint": endpoint,
        "use_ssl": settings.s3_endpoint.scheme == "https",
    }).fetchall()


def compare_table(connection, name: str, mapreduce_path: str) -> dict:
    if name not in TABLES:
        raise ValueError("Unknown frequency table")
    keys = TABLES[name]
    columns = ", ".join(keys + ["count"])
    schema = {key: "VARCHAR" for key in keys} | {"count": "BIGINT"}
    connection.execute(
        f"""CREATE TEMP TABLE mr_{name} AS
            SELECT * FROM read_csv($path, header=true, columns=$schema,
                                  delim=',', quote='"', escape='"')""",
        {"path": mapreduce_path, "schema": schema},
    ).fetchall()
    missing = f"SELECT {columns} FROM {name} EXCEPT ALL SELECT {columns} FROM mr_{name}"
    extra = f"SELECT {columns} FROM mr_{name} EXCEPT ALL SELECT {columns} FROM {name}"
    missing_count = connection.execute(f"SELECT count(*) FROM ({missing})").fetchall()[0][0]
    extra_count = connection.execute(f"SELECT count(*) FROM ({extra})").fetchall()[0][0]
    rows, frequency_sum = connection.execute(
        f"SELECT count(*), coalesce(sum(count), 0) FROM {name}"
    ).fetchall()[0]
    mr_rows = connection.execute(f"SELECT count(*) FROM mr_{name}").fetchall()[0][0]
    examples = {}
    for label, query, count in [("sql_only", missing, missing_count), ("mapreduce_only", extra, extra_count)]:
        if count:
            examples[label] = [dict(zip(keys + ["count"], row)) for row in
                               connection.execute(f"SELECT * FROM ({query}) LIMIT 5").fetchall()]
    return {
        "sql_rows": rows, "mapreduce_rows": mr_rows, "frequency_sum": int(frequency_sum),
        "sql_only_rows": missing_count, "mapreduce_only_rows": extra_count,
        "matches": missing_count == extra_count == 0, "difference_examples": examples,
    }


def run_check(settings: S3Settings, mapreduce_run_id: str, run_id: str | None = None) -> dict:
    validate_run_id(mapreduce_run_id)
    run_id = run_id or f"duckdb-{uuid4().hex}"
    validate_run_id(run_id)
    if run_id == mapreduce_run_id:
        raise ValueError("DuckDB output must not overwrite the MapReduce run")
    config = {"threads": 1, "memory_limit": "1GB"}
    if directory := os.environ.get("DUCKDB_EXTENSION_DIRECTORY"):
        config["extension_directory"] = directory
    source = f"s3://{settings.s3_bucket}/{settings.s3_input_key}"
    prefix = settings.s3_output_prefix.strip("/")
    result_root = f"s3://{settings.s3_bucket}/" + (prefix + "/" if prefix else "")
    with TemporaryDirectory(prefix="duckdb-spill-") as directory:
        config["temp_directory"] = directory
        with duckdb.connect(config=config) as connection:
            configure_s3(connection, settings)
            started = perf_counter()
            calculate(connection, source)
            calculation_seconds = perf_counter() - started
            tables = {}
            output = {}
            for name, keys in TABLES.items():
                tables[name] = compare_table(connection, name, f"{result_root}{mapreduce_run_id}/{name}.csv")
                path = f"{result_root}{run_id}/{name}.csv"
                connection.sql(f"SELECT * FROM {name} ORDER BY {', '.join(keys)}").write_csv(path, header=True)
                output[name] = path
            counts = connection.execute("""
                SELECT (SELECT count(*) FROM source_vacancies),
                       (SELECT count(*) FROM analyst_vacancies)
            """).fetchall()[0]
            return {
                "run_id": run_id, "mapreduce_run_id": mapreduce_run_id, "source": source,
                "duckdb_version": duckdb.__version__, "threads": 1, "memory_limit": "1GB",
                "source_rows": counts[0], "analyst_rows": counts[1],
                "skill_aliases_sha256": sha256(ALIASES_PATH.read_bytes()).hexdigest(),
                "calculation_seconds": round(calculation_seconds, 3),
                "calculation_verification_export_seconds": round(perf_counter() - started, 3),
                "tables": tables, "all_frequencies_match": all(t["matches"] for t in tables.values()),
                "output": output,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate frequencies in DuckDB and compare every row with MapReduce")
    parser.add_argument("--mapreduce-run-id", required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    result = run_check(get_s3_settings(), args.mapreduce_run_id, args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_frequencies_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
