"""Configuration validation and redaction tests."""

import pytest
from ops_agent.config import Settings
from pydantic import ValidationError


def test_development_defaults_are_usable() -> None:
    settings = Settings.model_validate({})

    assert settings.environment == "development"
    assert settings.report_max_search_queries == 16
    assert settings.fetch_max_bytes == 2_000_000
    assert settings.report_retention_days == 180
    assert settings.job_event_retention_days == 90
    assert settings.temporary_artifact_retention_days == 7
    assert settings.artifact_storage_path.name == "artifacts"
    assert settings.checkpoint_schema == "langgraph_checkpoint"
    assert settings.model_structured_output_mode == "json_schema"
    assert settings.model_thinking_mode == "provider_default"


def test_invalid_model_structured_output_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"model_structured_output_mode": "unsupported"})


def test_invalid_model_thinking_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"model_thinking_mode": "unsupported"})


def test_production_requires_credentials_and_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings.model_validate({"environment": "production"})


def test_production_rejects_short_session_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings.model_validate(
            {
                "environment": "production",
                "session_secret": "too-short",
            }
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("fetch_max_bytes", 1),
        ("fetch_concurrency", 0),
        ("report_token_budget", 100),
        ("report_retention_days", 0),
    ],
)
def test_invalid_limits_are_rejected(field_name: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field_name: value})


def test_secrets_are_redacted_from_repr_and_log_snapshot() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://private-user:private-pass@db/ops",
            "checkpoint_database_url": "postgresql://checkpoint-user:checkpoint-pass@db/ops",
            "redis_url": "redis://:redis-secret@redis:6379/0",
            "session_secret": "session-secret-value",
            "model_api_key": "model-secret-value",
            "model_health_url": "https://model.example/health?token=health-secret-value",
            "search_api_key": "search-secret-value",
        }
    )

    rendered = repr(settings)
    safe_snapshot = str(settings.safe_for_logging())
    for secret in (
        "private-pass",
        "checkpoint-pass",
        "redis-secret",
        "session-secret-value",
        "model-secret-value",
        "health-secret-value",
        "search-secret-value",
    ):
        assert secret not in rendered
        assert secret not in safe_snapshot
    assert safe_snapshot.count("[REDACTED]") == 7


def test_invalid_checkpoint_schema_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"checkpoint_schema": "public; DROP SCHEMA public"})
