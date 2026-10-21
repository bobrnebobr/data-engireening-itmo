import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.intermediate import IntermediateStore
from app.models import Counts, PairCount, TripleCount
from app.settings import S3Settings


class IntermediateTests(unittest.TestCase):
    def setUp(self):
        self.store = IntermediateStore(S3Settings(
            s3_endpoint="http://rustfs:9000", s3_access_key="example", s3_secret_key="example",
        ))

    def test_jsonl_round_trip_and_retry_overwrites_same_chunk(self):
        counts = Counts(
            singles={"анализ, данных": 2, 'sql\n"quoted"': 1},
            pairs=[PairCount(skills=("python", "sql"), count=2)],
            triples=[TripleCount(skills=("git", "python", "sql"), count=1)],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"chunk.jsonl")
            with patch.object(self.store, "path", return_value=path):
                self.store.write(counts, "run", 0)
                first = Path(path).read_bytes()
                self.store.write(counts, "run", 0)
                self.assertEqual(Path(path).read_bytes(), first)
                self.assertEqual(list(self.store.read(path)), list(self.store.rows(counts)))

    def test_empty_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"empty.jsonl")
            with patch.object(self.store, "path", return_value=path):
                self.store.write(Counts(), "run", 0)
                self.assertEqual(list(self.store.read(path)), [])

    def test_paths_are_scoped_by_run_and_chunk(self):
        self.assertEqual(self.store.path("run", 3), "s3://hh-lake/intermediate/run/chunk-000003.jsonl")
        for run_id in ["", "..", "a/b", "a\\b"]:
            with self.assertRaises(ValueError): self.store.path(run_id, 0)
        with self.assertRaises(ValueError): self.store.path("run", -1)
