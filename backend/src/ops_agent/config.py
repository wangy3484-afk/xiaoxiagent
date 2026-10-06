"""Typed application configuration with production safety checks."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for API, worker, research, and storage settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OPS_AGENT_",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://ops_agent:ops_agent@localhost:5432/ops_agent"
    )
    checkpoint_database_url: SecretStr = SecretStr(
        "postgresql://ops_agent:ops_agent@localhost:5432/ops_agent"
    )
    checkpoint_schema: str = Field(
        default="langgraph_checkpoint",
        pattern=r"^[a-z_][a-z0-9_]{0,62}$",
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    session_secret: SecretStr = SecretStr("development-only-change-me")
    session_cookie_name: str = "ops_agent_session"
    session_ttl_minutes: int = Field(default=480, ge=15, le=43_200)
    session_cookie_secure: bool = False
    session_cookie_same_site: Literal["lax", "strict"] = "lax"

    model_provider: Literal["openai", "openai-compatible"] = "openai-compatible"
    model_name: str = "gpt-4.1-mini"
    model_base_url: HttpUrl = HttpUrl("https://api.openai.com/v1")
    model_health_url: HttpUrl | None = Field(default=None, repr=False)
    model_api_key: SecretStr | None = None
    model_timeout_seconds: float = Field(default=90.0, gt=0, le=600)
    model_max_retries: int = Field(default=2, ge=0, le=2)
    model_structured_output_mode: Literal["json_schema", "json_object"] = "json_schema"
    model_thinking_mode: Literal["provider_default", "enabled", "disabled"] = (
        "provider_default"
    )
    model_input_cost_per_million_tokens: float = Field(default=0.0, ge=0)
    model_output_cost_per_million_tokens: float = Field(default=0.0, ge=0)

    search_provider: Literal["tavily", "brave", "serpapi"] = "tavily"
    search_base_url: HttpUrl = HttpUrl("https://api.tavily.com")
    search_api_key: SecretStr | None = None
    search_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    fetch_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    fetch_max_bytes: int = Field(default=2_000_000, ge=10_000, le=20_000_000)
    fetch_max_redirects: int = Field(default=5, ge=0, le=20)
    fetch_concurrency: int = Field(default=8, ge=1, le=50)

    report_max_search_queries: int = Field(default=16, ge=1, le=100)
    report_max_sources_per_query: int = Field(default=8, ge=1, le=20)
    report_max_evidence_items: int = Field(default=80, ge=4, le=500)
    report_token_budget: int = Field(default=32_000, ge=4_000, le=250_000)
    report_timeout_seconds: int = Field(default=900, ge=60, le=7_200)

    artifact_storage_path: Path = Path("artifacts")
    report_brand_title: str | None = Field(default=None, max_length=120)
    report_brand_header: str | None = Field(default=None, max_length=200)
    report_brand_logo_path: Path | None = None
    report_retention_days: int = Field(default=180, ge=1, le=3_650)
    source_snapshot_retention_days: int = Field(default=30, ge=1, le=365)
    job_event_retention_days: int = Field(default=90, ge=1, le=3_650)
    temporary_artifact_retention_days: int = Field(default=7, ge=1, le=365)
    monitor_interval_seconds: int = Field(default=15, ge=2, le=300)
    monitor_failure_threshold: int = Field(default=2, ge=1, le=10)
    monitor_queue_backlog_threshold: int = Field(default=20, ge=0, le=100_000)

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        """Reject placeholder or missing credentials in production."""
        if self.environment != "production":
            return self

        session_secret = self.session_secret.get_secret_value().strip()
        if (
            session_secret == "development-only-change-me"
            or len(session_secret) < 32
        ):
            raise ValueError(
                "OPS_AGENT_SESSION_SECRET must be at least 32 characters in production"
            )
        if self.model_api_key is None or not self.model_api_key.get_secret_value().strip():
            raise ValueError("OPS_AGENT_MODEL_API_KEY is required in production")
        if self.search_api_key is None or not self.search_api_key.get_secret_value().strip():
            raise ValueError("OPS_AGENT_SEARCH_API_KEY is required in production")
        if not self.session_cookie_secure:
            raise ValueError("OPS_AGENT_SESSION_COOKIE_SECURE must be true in production")
        return self

    def safe_for_logging(self) -> dict[str, object]:
        """Return settings metadata without credentials or connection strings."""
        data: dict[str, object] = self.model_dump(mode="json")
        for field_name in (
            "database_url",
            "checkpoint_database_url",
            "redis_url",
            "session_secret",
            "model_api_key",
            "model_health_url",
            "search_api_key",
        ):
            data[field_name] = "[REDACTED]"
        return data


@lru_cache
def get_settings() -> Settings:
    """Load and cache process-level settings."""
    return Settings()
