"""OpenAI-compatible Chat Completions adapter with strict structured output."""

import json
import re
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from ops_agent.providers.contracts import (
    ModelRequest,
    ModelUsage,
    StructuredModelResult,
)
from ops_agent.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderSchemaError,
    ProviderTimeoutError,
)


class OpenAICompatibleModelProvider:
    """Call `/chat/completions` without leaking provider response formats upstream."""

    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float,
        schema_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 0 <= schema_retries <= 2:
            raise ValueError("schema_retries must be between 0 and 2")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = httpx.Timeout(timeout_seconds)
        self.schema_retries = schema_retries
        self.transport = transport

    async def generate_structured[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        attempts = self.schema_retries + 1
        last_request_id: str | None = None
        for attempt in range(1, attempts + 1):
            response = await self._post(
                self._request_payload(request, output_schema, is_retry=attempt > 1)
            )
            last_request_id = response.headers.get("x-request-id")
            data = self._response_json(response, last_request_id)
            last_request_id = last_request_id or _optional_string(data.get("id"))
            try:
                content = _assistant_content(data)
                output = output_schema.model_validate(json.loads(content))
            except (KeyError, TypeError, json.JSONDecodeError, ValidationError):
                if attempt == attempts:
                    raise ProviderSchemaError(
                        "model output did not match the requested schema",
                        provider=self.provider_name,
                        attempts=attempt,
                        request_id=last_request_id,
                    ) from None
                continue

            usage_payload = data.get("usage")
            usage = usage_payload if isinstance(usage_payload, Mapping) else {}
            return StructuredModelResult[OutputT](
                output=output,
                provider=self.provider_name,
                model=_optional_string(data.get("model")) or self.model,
                request_id=last_request_id,
                usage=ModelUsage(
                    input_tokens=_safe_nonnegative_int(usage.get("prompt_tokens")),
                    output_tokens=_safe_nonnegative_int(usage.get("completion_tokens")),
                ),
            )
        raise AssertionError("structured output retry loop did not terminate")

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                headers={
                    "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "model provider request timed out",
                provider=self.provider_name,
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(
                "model provider request failed",
                provider=self.provider_name,
                retryable=True,
            ) from exc

        request_id = response.headers.get("x-request-id")
        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(
                "model provider rejected authentication",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            )
        if response.status_code == 429:
            raise ProviderRateLimitError(
                "model provider rate limit exceeded",
                provider=self.provider_name,
                retryable=True,
                request_id=request_id,
            )
        if response.is_error:
            raise ProviderResponseError(
                f"model provider returned HTTP {response.status_code}",
                provider=self.provider_name,
                retryable=response.status_code >= 500,
                request_id=request_id,
            )
        return response

    def _request_payload[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_schema: type[OutputT],
        *,
        is_retry: bool,
    ) -> dict[str, Any]:
        messages = [message.model_dump(mode="json") for message in request.messages]
        if is_retry:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The previous output failed schema validation. "
                        "Return one corrected JSON object matching the schema."
                    ),
                }
            )
        return {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(output_schema.__name__),
                    "strict": True,
                    "schema": output_schema.model_json_schema(),
                },
            },
        }

    def _response_json(
        self, response: httpx.Response, request_id: str | None
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "model provider returned malformed JSON",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                "model provider returned an unexpected response shape",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            )
        return payload


def _assistant_content(payload: Mapping[str, Any]) -> str:
    choices = payload["choices"]
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices")
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise TypeError("choice")
    message = first_choice["message"]
    if not isinstance(message, Mapping):
        raise TypeError("message")
    content = message["content"]
    if not isinstance(content, str):
        raise TypeError("content")
    return content


def _schema_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]
    return sanitized or "structured_output"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
