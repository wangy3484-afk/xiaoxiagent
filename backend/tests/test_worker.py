from ops_agent.worker import celery_app


def test_worker_uses_json_messages() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
