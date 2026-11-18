from celery import Celery

from app.config import get_settings

s = get_settings()

celery = Celery("raw2reel", broker=s.redis_url, backend=s.redis_url, include=["app.tasks.references", "app.tasks.clips", "app.tasks.analysis", "app.tasks.styles", "app.tasks.plans", "app.tasks.renders"])
celery.conf.update(
    task_default_queue="default",
    task_routes={"app.tasks.references.*": {"queue": "media"}, "app.tasks.clips.*": {"queue": "media"}, "app.tasks.analysis.*": {"queue": "media"}, "app.tasks.renders.*": {"queue": "media"}},
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    broker_connection_retry_on_startup=True,
)

app = celery  # `celery -A app.celery_app` finds this
