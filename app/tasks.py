from pydantic import TypeAdapter

from app.celery_app import celery_app
from app.intermediate import IntermediateStore
from app.mapper import Mapper
from app.models import Chunk
from app.reducer import Reducer
from app.settings import get_s3_settings
from app.storage import validate_run_id
from app.writer import Writer


chunk_adapter = TypeAdapter(Chunk)


@celery_app.task(name="map", queue="map", acks_late=True, reject_on_worker_lost=True)
def map_vacancies(chunk_data: dict, run_id: str) -> dict:
    validate_run_id(run_id)
    chunk = chunk_adapter.validate_python(chunk_data)
    counts = Mapper.map(chunk)
    store = IntermediateStore(get_s3_settings())
    path = store.write(counts, run_id, chunk.chunk_id)
    return {"chunk_id": chunk.chunk_id, "path": path}


@celery_app.task(name="reduce", queue="reduce", acks_late=True, reject_on_worker_lost=True)
def reduce_counts(mapped_results: list[dict], run_id: str) -> dict:
    validate_run_id(run_id)
    chunk_ids = [result["chunk_id"] for result in mapped_results]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Duplicate chunk_id in mapper results")
    settings = get_s3_settings()
    store = IntermediateStore(settings)
    for result in mapped_results:
        if result["path"] != store.path(run_id, result["chunk_id"]):
            raise ValueError("Unexpected intermediate path")
    counts = Reducer.reduce(store.read(result["path"]) for result in mapped_results)
    paths = Writer(settings).write(counts, run_id)
    return {
        "distinct_singles": len(counts.singles),
        "distinct_pairs": len(counts.pairs),
        "distinct_triples": len(counts.triples),
        "output": paths,
    }
