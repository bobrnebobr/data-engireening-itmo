import logging
from dataclasses import asdict
from time import perf_counter
from uuid import uuid4

from app.reader import Reader
from app.settings import Settings
from app.skills import aliases_sha256
from app.storage import validate_run_id
from app.tasks import map_vacancies, reduce_counts


logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, reader: Reader, settings: Settings, task_timeout: float = 300) -> None:
        if task_timeout <= 0:
            raise ValueError("task_timeout must be positive")
        self.reader = reader
        self.settings = settings
        self.task_timeout = task_timeout

    def run(self, run_id: str | None = None) -> dict:
        run_id = run_id or uuid4().hex
        validate_run_id(run_id)
        started = perf_counter()
        mapped = []
        pending = []
        seen_ids = set()
        vacancies_read = 0
        iterator = self.reader.read_chunks(self.settings.chunk_size)
        try:
            for chunk in iterator:
                if chunk.chunk_id in seen_ids:
                    raise ValueError(f"Duplicate input chunk_id: {chunk.chunk_id}")
                seen_ids.add(chunk.chunk_id)
                vacancies_read += len(chunk.vacancies)
                pending.append((chunk.chunk_id, map_vacancies.delay(asdict(chunk), run_id)))
                if len(pending) >= self.settings.max_in_flight:
                    mapped.extend(self._collect_batch(pending))
                    pending.clear()
                    logger.info("Mapped %s chunks", len(mapped))
            if pending:
                mapped.extend(self._collect_batch(pending))
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()

        logger.info("Reducing %s intermediate files", len(mapped))
        task = reduce_counts.delay(mapped, run_id)
        summary = task.get(timeout=self.task_timeout)
        task.forget()
        return {
            "run_id": run_id,
            "skill_aliases_sha256": aliases_sha256(),
            "chunks": len(seen_ids),
            "vacancies_read": vacancies_read,
            **summary,
            "elapsed_seconds": round(perf_counter() - started, 3),
        }

    def _collect_batch(self, pending: list) -> list[dict]:
        mapped = []
        for chunk_id, task in pending:
            result = task.get(timeout=self.task_timeout)
            if result["chunk_id"] != chunk_id:
                raise ValueError(f"Unexpected mapper result for chunk {chunk_id}")
            mapped.append(result)
            task.forget()
        return mapped
