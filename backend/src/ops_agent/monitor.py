"""Small service monitor that emits transition alerts as structured logs."""

import json
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import redis

from ops_agent.config import Settings
from ops_agent.worker import celery_app

_HEARTBEAT_PATH = Path("/tmp/ops-agent-monitor-heartbeat")
_STOP = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _emit(component: str, state: str, detail: str) -> None:
    print(
        json.dumps(
            {
                "event": "ops_health_alert",
                "component": component,
                "state": state,
                "detail": detail,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _redis_and_queue(settings: Settings) -> tuple[bool, int | None]:
    client = redis.Redis.from_url(
        settings.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
    )
    try:
        client.ping()
        backlog = client.llen("report-jobs")
        if not isinstance(backlog, int):
            raise TypeError("Redis queue length is not an integer")
        return True, backlog
    except redis.RedisError:
        return False, None
    finally:
        client.close()


def _worker_alive() -> bool:
    try:
        replies = celery_app.control.inspect(destination=["worker@worker"], timeout=3).ping()
    except Exception:
        return False
    return bool(replies and replies.get("worker@worker", {}).get("ok") == "pong")


def _model_alive(settings: Settings) -> bool:
    if settings.model_health_url is None:
        return True
    headers = {}
    if settings.model_api_key is not None:
        headers["Authorization"] = f"Bearer {settings.model_api_key.get_secret_value()}"
    try:
        response = httpx.get(str(settings.model_health_url), headers=headers, timeout=3)
        return response.status_code < 400
    except httpx.HTTPError:
        return False


def run_monitor(
    settings: Settings,
    *,
    redis_probe: Callable[[Settings], tuple[bool, int | None]] = _redis_and_queue,
    worker_probe: Callable[[], bool] = _worker_alive,
    model_probe: Callable[[Settings], bool] = _model_alive,
) -> None:
    failures: dict[str, int] = {}
    firing: set[str] = set()

    while not _STOP:
        redis_ok, backlog = redis_probe(settings)
        checks: dict[str, bool | None] = {
            "redis": redis_ok,
            "worker": worker_probe() if redis_ok else None,
            "model": model_probe(settings),
            "queue_backlog": (
                backlog is not None and backlog <= settings.monitor_queue_backlog_threshold
            ) if redis_ok else None,
        }
        for component, healthy in checks.items():
            if healthy is None:
                continue
            if healthy:
                failures[component] = 0
                if component in firing:
                    firing.remove(component)
                    _emit(component, "resolved", "probe_recovered")
                continue
            failures[component] = failures.get(component, 0) + 1
            if (
                failures[component] >= settings.monitor_failure_threshold
                and component not in firing
            ):
                firing.add(component)
                detail = (
                    f"pending={backlog}; threshold={settings.monitor_queue_backlog_threshold}"
                    if component == "queue_backlog"
                    else "probe_failed"
                )
                _emit(component, "firing", detail)

        _HEARTBEAT_PATH.touch()
        time.sleep(settings.monitor_interval_seconds)


def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    run_monitor(Settings())


if __name__ == "__main__":
    main()
