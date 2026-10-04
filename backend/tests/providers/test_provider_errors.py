"""Stable provider error taxonomy and safe structured logging tests."""

import logging

import pytest
from ops_agent.providers.errors import (
    ContentExtractionError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from ops_agent.providers.logging import log_provider_error, safe_provider_error_context


@pytest.mark.parametrize(
    ("error", "code", "category", "retryable"),
    [
        (
            ProviderTimeoutError("safe", provider="model", retryable=True),
            "PROVIDER_TIMEOUT",
            "transient",
            True,
        ),
        (
            ProviderQuotaError("safe", provider="search", retryable=False),
            "PROVIDER_QUOTA_EXHAUSTED",
            "quota",
            False,
        ),
        (
            ProviderAuthenticationError("safe", provider="model", retryable=False),
            "PROVIDER_AUTHENTICATION_ERROR",
            "authentication",
            False,
        ),
        (
            ContentExtractionError("safe", provider="extractor", retryable=False),
            "CONTENT_EXTRACTION_FAILED",
            "content",
            False,
        ),
        (
            ProviderResponseError("safe", provider="search", retryable=True),
            "PROVIDER_RESPONSE_ERROR",
            "transient",
            True,
        ),
    ],
)
def test_error_codes_and_categories_are_stable(
    error: ProviderError,
    code: str,
    category: str,
    retryable: bool,
) -> None:
    assert error.code == code
    assert error.category == category
    assert error.retryable is retryable


def test_safe_log_context_has_an_explicit_allow_list() -> None:
    error = ProviderAuthenticationError(
        "authentication was rejected",
        provider="model",
        retryable=False,
        request_id="request-123",
    )

    assert safe_provider_error_context(error, operation="generate_report") == {
        "error_code": "PROVIDER_AUTHENTICATION_ERROR",
        "error_category": "authentication",
        "provider": "model",
        "retryable": False,
        "request_id": "request-123",
        "operation": "generate_report",
    }


def test_provider_logging_excludes_secret_webpage_and_model_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-secret-must-not-appear"
    webpage = "<html><body>full private page body</body></html>"
    model_response = '{"full":"model response"}'
    try:
        raise ValueError(f"{secret} {webpage} {model_response}")
    except ValueError as cause:
        error = ProviderResponseError(
            "provider returned malformed content",
            provider="model",
            retryable=False,
            request_id="request-safe",
        )
        error.__cause__ = cause

    logger = logging.getLogger("ops_agent.providers.test")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        log_provider_error(logger, error, operation="structured_generation")

    record = caplog.records[-1]
    rendered = caplog.text
    context = getattr(record, "provider_error", None)
    assert isinstance(context, dict)
    assert context["error_code"] == "PROVIDER_RESPONSE_ERROR"
    assert secret not in rendered
    assert webpage not in rendered
    assert model_response not in rendered
