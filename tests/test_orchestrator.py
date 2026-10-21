import os
import unittest
from unittest.mock import Mock, patch

from app.intermediate import IntermediateStore
from app.models import AggregatedCounts, Chunk, Vacancy
from app.reader import Reader
from app.settings import S3Settings, Settings

with patch.dict(os.environ, {
    "CELERY_BROKER_URL": "redis://redis:6379/0",
    "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
}):
    from app.celery_app import celery_app
    from app.orchestrator import Orchestrator
    from app.tasks import reduce_counts


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        celery_app.conf.update(broker_url="memory://", result_backend="cache+memory://",
                               task_always_eager=True, task_eager_propagates=True)

    def setUp(self):
        settings = S3Settings(s3_endpoint="http://rustfs:9000", s3_access_key="example", s3_secret_key="example")
        store = IntermediateStore(settings)
        saved = {}
        def upload(counts, run_id, chunk_id):
            path = store.path(run_id, chunk_id)
            saved[path] = list(store.rows(counts))
            return path
        for target, kwargs in [
            ("app.tasks.get_s3_settings", {"return_value": settings}),
            ("app.tasks.IntermediateStore.write", {"side_effect": upload}),
            ("app.tasks.IntermediateStore.read", {"side_effect": lambda path: iter(saved[path])}),
            ("app.tasks.Writer.write", {"return_value": {"singles": "s3://hh-lake/results/test/singles.csv"}}),
        ]:
            patcher = patch(target, **kwargs)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if target.endswith("Writer.write"): self.write = mock

    def make_pipeline(self, chunks, max_in_flight=2):
        reader = Mock(spec=Reader)
        reader.read_chunks.return_value = iter(chunks)
        return Orchestrator(reader, Settings(chunk_size=2, max_in_flight=max_in_flight)), reader

    def test_reduces_once_after_all_map_batches(self):
        chunks = [
            Chunk(0, [Vacancy(1, "Аналитик", ("Python", "SQL"))]),
            Chunk(1, [Vacancy(2, "Analyst", ("Git", "python", "sql"))]),
            Chunk(2, [Vacancy(3, "Аналитик", ("SQL",)), Vacancy(4, "Developer", ("Java",))]),
        ]
        for limit in [1, 2, 4]:
            self.write.reset_mock()
            pipeline, reader = self.make_pipeline(chunks, limit)
            with patch("app.orchestrator.reduce_counts.delay", wraps=reduce_counts.delay) as reduce:
                summary = pipeline.run("test")
                reduce.assert_called_once()
                refs, run_id = reduce.call_args.args
                self.assertEqual(len(refs), 3)
                self.assertTrue(all(set(ref) == {"chunk_id", "path"} for ref in refs))
            counts, run_id = self.write.call_args.args
            self.assertEqual(counts.singles, {"git": 1, "python": 2, "sql": 3})
            self.assertEqual(counts.triples, {("git", "python", "sql"): 1})
            self.assertEqual(run_id, "test")
            self.assertEqual(summary["chunks"], 3)
            self.assertEqual(summary["vacancies_read"], 4)
            reader.read_chunks.assert_called_once_with(2)

    def test_empty_source_writes_empty_tables(self):
        pipeline, _ = self.make_pipeline([])
        self.assertEqual(pipeline.run("empty")["chunks"], 0)
        self.write.assert_called_once_with(AggregatedCounts(), "empty")

    def test_duplicate_input_chunk_is_rejected_without_output(self):
        chunk = Chunk(0, [Vacancy(1, "Аналитик", ("SQL",))])
        pipeline, _ = self.make_pipeline([chunk, chunk])
        with self.assertRaisesRegex(ValueError, "Duplicate input chunk_id"):
            pipeline.run("duplicate")
        self.write.assert_not_called()

    def test_mapper_failure_does_not_publish_output(self):
        pipeline, _ = self.make_pipeline([Chunk(0, [])])
        failed = Mock()
        failed.get.side_effect = TimeoutError("worker timeout")
        with patch("app.orchestrator.map_vacancies.delay", return_value=failed):
            with self.assertRaisesRegex(TimeoutError, "worker timeout"): pipeline.run("failed")
        self.write.assert_not_called()

    def test_mismatched_mapper_chunk_is_rejected(self):
        pipeline, _ = self.make_pipeline([Chunk(0, [])])
        incorrect = Mock()
        incorrect.get.return_value = {"chunk_id": 5, "path": "wrong"}
        with patch("app.orchestrator.map_vacancies.delay", return_value=incorrect):
            with self.assertRaisesRegex(ValueError, "Unexpected mapper result"): pipeline.run("mismatch")
        self.write.assert_not_called()
