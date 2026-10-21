import json
import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from pydantic import ValidationError

from app.intermediate import IntermediateStore
from app.models import Chunk, Vacancy
from app.settings import S3Settings

with patch.dict(os.environ, {
    "CELERY_BROKER_URL": "redis://redis:6379/0",
    "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
}):
    from app.celery_app import celery_app
    from app.tasks import map_vacancies, reduce_counts


class TaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        celery_app.conf.update(broker_url="memory://", result_backend="cache+memory://",
                               task_always_eager=True, task_eager_propagates=True)

    def setUp(self):
        settings = S3Settings(s3_endpoint="http://rustfs:9000", s3_access_key="example", s3_secret_key="example")
        self.patch_settings = patch("app.tasks.get_s3_settings", return_value=settings)
        self.patch_settings.start()
        self.addCleanup(self.patch_settings.stop)

    def test_map_returns_only_reference_after_upload(self):
        chunk = Chunk(7, [Vacancy(1, "Аналитик", (" Python ", "SQL", "python"))])
        with patch("app.tasks.IntermediateStore.write", return_value="s3://example/partial") as upload:
            result = map_vacancies.delay(json.loads(json.dumps(asdict(chunk))), "run").get(timeout=1)
        self.assertEqual(result, {"chunk_id": 7, "path": "s3://example/partial"})
        self.assertEqual(upload.call_args.args[0].singles, {"python": 1, "sql": 1})
        self.assertNotIn("counts", json.loads(json.dumps(result)))

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValidationError):
            map_vacancies.delay({"chunk_id": 9, "vacancies": [{"vacancy_id": 1}]}, "run")

    def test_upload_failure_is_not_reported_as_success(self):
        with patch("app.tasks.IntermediateStore.write", side_effect=OSError("upload failed")):
            with self.assertRaisesRegex(OSError, "upload failed"):
                map_vacancies.delay(asdict(Chunk(0, [])), "run")

    def test_reduce_reads_references_and_writes_output_in_worker(self):
        settings = S3Settings(
            s3_endpoint="http://rustfs:9000", s3_access_key="example", s3_secret_key="example")
        store = IntermediateStore(settings)
        refs = [{"chunk_id": i, "path": store.path("run", i)} for i in [0, 1]]
        rows = [[(("sql",), 2)], [(("sql",), 3), (("python", "sql"), 1)]]
        with patch("app.tasks.IntermediateStore.read", side_effect=map(iter, rows)), \
             patch("app.tasks.Writer.write", return_value={"singles": "s3://example/output"}) as write:
            summary = reduce_counts.delay(refs, "run").get(timeout=1)
        self.assertEqual(write.call_args.args[0].singles, {"sql": 5})
        self.assertEqual(summary["distinct_pairs"], 1)
        self.assertNotIn("counts", summary)

    def test_reduce_empty_results(self):
        with patch("app.tasks.Writer.write", return_value={}):
            summary = reduce_counts.delay([], "run").get(timeout=1)
        self.assertEqual(summary["distinct_singles"], 0)

    def test_reduce_rejects_duplicate_and_wrong_run_references(self):
        for refs, message in [
            ([{"chunk_id": 0, "path": "wrong"}]*2, "Duplicate chunk_id"),
            ([{"chunk_id": 0, "path": "s3://hh-lake/intermediate/other/chunk-000000.jsonl"}], "Unexpected intermediate"),
        ]:
            with patch("app.tasks.Writer.write") as write:
                with self.assertRaisesRegex(ValueError, message): reduce_counts.delay(refs, "run")
                write.assert_not_called()
