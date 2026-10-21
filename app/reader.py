import polars as pl

from collections.abc import Iterator

from app.models import Chunk, Vacancy
from app.settings import S3Settings
from app.storage import storage_options


class Reader:
    def __init__(self, s3_settings: S3Settings) -> None:
        self.s3_settings = s3_settings
        self.bucket = s3_settings.s3_bucket
        self.input_key = s3_settings.s3_input_key

    def read_chunks(self, chunk_size: int) -> Iterator[Chunk]:
        options = storage_options(self.s3_settings)
        query = pl.scan_csv(
            f"s3://{self.bucket}/{self.input_key}",
            storage_options=options,
        ).select("vacancy_id", "name", "key_skills")

        for chunk_id, batch in enumerate(query.collect_batches(chunk_size=chunk_size)):
            vacancies = []

            for row in batch.iter_rows(named=True):
                skills = (row["key_skills"] or "").split(";")
                row["key_skills"] = tuple(skill.strip() for skill in skills if skill.strip())
                row["vacancy_id"] = int(row["vacancy_id"])
                vacancies.append(Vacancy(**row))

            yield Chunk(chunk_id=chunk_id, vacancies=vacancies)
