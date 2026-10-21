import csv
from tempfile import NamedTemporaryFile

import polars as pl

from app.models import AggregatedCounts
from app.settings import S3Settings
from app.storage import storage_options, validate_run_id


class Writer:
    def __init__(self, s3_settings: S3Settings) -> None:
        self.s3_settings = s3_settings

    def write(self, counts: AggregatedCounts, run_id: str) -> dict[str, str]:
        validate_run_id(run_id)
        settings = self.s3_settings
        prefix = "/".join(filter(None, [settings.s3_output_prefix.strip("/"), run_id]))
        paths = {}
        for name, values, skills_columns in [
            ("singles", counts.singles, ["skill"]),
            ("pairs", counts.pairs, ["skill_1", "skill_2"]),
            ("triples", counts.triples, ["skill_1", "skill_2", "skill_3"]),
        ]:
            schema = {column: pl.String for column in skills_columns} | {"count": pl.Int64}
            path = f"s3://{settings.s3_bucket}/{prefix}/{name}.csv"
            # Stage one CSV on disk, then stream it to S3 without a second full model.
            with NamedTemporaryFile(mode="w+", encoding="utf-8", newline="", suffix=".csv") as file:
                writer = csv.writer(file)
                writer.writerow(schema)
                for key in sorted(values):
                    skills = (key,) if name == "singles" else key
                    writer.writerow((*skills, values[key]))
                file.flush()
                pl.scan_csv(file.name, schema=schema).sink_csv(
                    path, storage_options=storage_options(settings),
                )
            paths[name] = path
        return paths
