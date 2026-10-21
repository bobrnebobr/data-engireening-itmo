from celery import Celery

from app.settings import get_celery_settings


celery_settings = get_celery_settings()

celery_app = Celery(
    "celery_worker",
    broker=str(celery_settings.celery_broker_url),
    backend=str(celery_settings.celery_result_backend),
    include=["app.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Re-deliver unacknowledged tasks after loss of an entire worker process.
    broker_transport_options={"visibility_timeout": celery_settings.celery_visibility_timeout},
    result_backend_transport_options={"visibility_timeout": celery_settings.celery_visibility_timeout},
    visibility_timeout=celery_settings.celery_visibility_timeout,
)
