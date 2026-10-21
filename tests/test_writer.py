import unittest
from unittest.mock import patch

import polars as pl

from app.models import AggregatedCounts
from app.settings import S3Settings
from app.writer import Writer


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.writer = Writer(S3Settings(s3_endpoint="http://rustfs:9000", s3_access_key="example", s3_secret_key="example"))

    def test_writes_three_csv_tables_and_run_paths(self):
        captured = {}
        def capture(frame, path, *, storage_options):
            captured[path] = frame.collect()
            self.assertEqual(storage_options["aws_endpoint"], "http://rustfs:9000")
        counts = AggregatedCounts(
            singles={"sql": 1, 'анализ, "данных"\n': 2},
            pairs={("python", "sql"): 1}, triples={("git", "python", "sql"): 1},
        )
        with patch.object(pl.LazyFrame, "sink_csv", new=capture):
            paths = self.writer.write(counts, "run-001")
        self.assertEqual(paths, {name: f"s3://hh-lake/results/run-001/{name}.csv" for name in ["singles", "pairs", "triples"]})
        self.assertEqual(captured[paths["singles"]].to_dicts(), [
            {"skill": "sql", "count": 1}, {"skill": 'анализ, "данных"\n', "count": 2},
        ])
        self.assertEqual(captured[paths["pairs"]].to_dicts(), [{"skill_1": "python", "skill_2": "sql", "count": 1}])
        self.assertEqual(captured[paths["triples"]].to_dicts(), [{"skill_1": "git", "skill_2": "python", "skill_3": "sql", "count": 1}])

    def test_empty_results_keep_headers(self):
        frames = []
        def capture(frame, path, *, storage_options): frames.append(frame.collect())
        with patch.object(pl.LazyFrame, "sink_csv", new=capture): self.writer.write(AggregatedCounts(), "empty")
        self.assertEqual([f.columns for f in frames], [["skill", "count"], ["skill_1", "skill_2", "count"], ["skill_1", "skill_2", "skill_3", "count"]])
        self.assertTrue(all(f.is_empty() for f in frames))
        self.assertTrue(all(f.schema["count"] == pl.Int64 for f in frames))

    def test_upload_failure_propagates(self):
        with patch.object(pl.LazyFrame, "sink_csv", side_effect=OSError("upload failed")):
            with self.assertRaisesRegex(OSError, "upload failed"): self.writer.write(AggregatedCounts(), "failed")
