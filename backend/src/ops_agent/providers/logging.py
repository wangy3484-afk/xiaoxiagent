"""Structured provider logging that deliberately excludes raw external content."""

import logging
from typing import TypedDict

from ops_agent.providers.errors import ProviderError, ProviderErrorCategory


class SafeProviderErrorContext(TypedDict):
    error_code: str
    error_category: ProviderErrorCategory
    provider: str
    retryable: bool
    request_id: str | None
    operation: str


def safe_provider_error_context(
    error: ProviderError,
    *,
    operation: str,
) -> SafeProviderErrorContext:
    """Project a provider failure into an allow-listed, serialization-safe shape."""
    return {
        "error_code": error.code,
        "error_category": error.category,
        "provider": error.provider,
        "retryable": error.retryable,
        "request_id": error.request_id,
        "operation": operation,
    }


def log_provider_error(
    logger: logging.Logger,
    error: ProviderError,
    *,
    operation: str,
) -> None:
    """Log safe metadata only; never interpolate the exception or its cause."""
    logger.warning(
        "external provider operation failed",
        extra={
            "provider_error": safe_provider_error_context(
                error,
                operation=operation,
            )
        },
    )
