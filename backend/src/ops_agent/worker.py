"""Celery worker entrypoint."""

from celery import Celery

from ops_agent.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ops_strategy_agent",
    broker=settings.redis_url.get_secret_value(),
)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
)
