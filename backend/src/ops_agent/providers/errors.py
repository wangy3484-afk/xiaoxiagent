"""Safe provider failures that never retain credentials or raw response bodies."""

from typing import Literal

ProviderErrorCategory = Literal[
    "transient",
    "quota",
    "authentication",
    "content",
    "provider",
]


class ProviderError(RuntimeError):
    code = "PROVIDER_ERROR"
    category: ProviderErrorCategory = "provider"

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.request_id = request_id


class ProviderAuthenticationError(ProviderError):
    code = "PROVIDER_AUTHENTICATION_ERROR"
    category: ProviderErrorCategory = "authentication"


class ProviderRateLimitError(ProviderError):
    code = "PROVIDER_RATE_LIMITED"
    category: ProviderErrorCategory = "transient"


class ProviderQuotaError(ProviderError):
    code = "PROVIDER_QUOTA_EXHAUSTED"
    category: ProviderErrorCategory = "quota"


class ProviderTimeoutError(ProviderError):
    code = "PROVIDER_TIMEOUT"
    category: ProviderErrorCategory = "transient"


class ProviderResponseError(ProviderError):
    code = "PROVIDER_RESPONSE_ERROR"

    @property
    def category(self) -> ProviderErrorCategory:  # type: ignore[override]
        return "transient" if self.retryable else "content"


class UnsafeUrlError(ProviderError):
    code = "UNSAFE_URL"
    category: ProviderErrorCategory = "content"


class ContentRejectedError(ProviderError):
    code = "CONTENT_REJECTED"
    category: ProviderErrorCategory = "content"


class ContentExtractionError(ProviderError):
    code = "CONTENT_EXTRACTION_FAILED"
    category: ProviderErrorCategory = "content"


class ProviderSchemaError(ProviderError):
    code = "PROVIDER_SCHEMA_ERROR"
    category: ProviderErrorCategory = "content"

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        attempts: int,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            retryable=False,
            request_id=request_id,
        )
        self.attempts = attempts
