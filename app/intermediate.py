from collections.abc import Iterator
from itertools import chain

import polars as pl

from app.models import Counts
from app.settings import S3Settings
from app.storage import storage_options, validate_run_id


class IntermediateStore:
    schema = {"skills": pl.List(pl.String), "count": pl.Int64}

    def __init__(self, settings: S3Settings) -> None:
        self.settings = settings
        self.options = storage_options(settings)

    def path(self, run_id: str, chunk_id: int) -> str:
        validate_run_id(run_id)
        if chunk_id < 0:
            raise ValueError("chunk_id must be nonnegative")
        prefix = self.settings.s3_intermediate_prefix.strip("/")
        key = "/".join(filter(None, [prefix, run_id, f"chunk-{chunk_id:06d}.jsonl"]))
        return f"s3://{self.settings.s3_bucket}/{key}"

    @staticmethod
    def rows(counts: Counts) -> Iterator[tuple[tuple[str, ...], int]]:
        yield from (((skill,), count) for skill, count in counts.singles.items())
        yield from ((item.skills, item.count) for item in chain(counts.pairs, counts.triples))

    def write(self, counts: Counts, run_id: str, chunk_id: int) -> str:
        path = self.path(run_id, chunk_id)
        frame = pl.DataFrame(
            ((list(skills), count) for skills, count in self.rows(counts)),
            schema=self.schema, orient="row",
        )
        frame.lazy().sink_ndjson(path, storage_options=self.options)
        return path

    def read(self, path: str) -> Iterator[tuple[tuple[str, ...], int]]:
        query = pl.scan_ndjson(path, schema=self.schema, storage_options=self.options)
        for batch in query.collect_batches(chunk_size=10000):
            for skills, count in batch.iter_rows():
                yield tuple(skills), count
