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
    assert settings.artifact_storage_path.name == "artifacts"


def test_production_requires_credentials_and_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings.model_validate({"environment": "production"})


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
            "redis_url": "redis://:redis-secret@redis:6379/0",
            "session_secret": "session-secret-value",
            "model_api_key": "model-secret-value",
            "search_api_key": "search-secret-value",
        }
    )

    rendered = repr(settings)
    safe_snapshot = str(settings.safe_for_logging())
    for secret in (
        "private-pass",
        "redis-secret",
        "session-secret-value",
        "model-secret-value",
        "search-secret-value",
    ):
        assert secret not in rendered
        assert secret not in safe_snapshot
    assert safe_snapshot.count("[REDACTED]") == 5
