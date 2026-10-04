"""Mock-server tests for the OpenAI-compatible structured model adapter."""

import json

import httpx
import pytest
from ops_agent.providers import ModelMessage, ModelRequest, OpenAICompatibleModelProvider
from ops_agent.providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderSchemaError,
    ProviderTimeoutError,
)
from pydantic import BaseModel, SecretStr


class SceneOutput(BaseModel):
    primary_scene: str
    rationale: str


def _request() -> ModelRequest:
    return ModelRequest(
        purpose="classify_scene",
        messages=(ModelMessage(role="user", content="希望提高新用户次日留存"),),
        max_output_tokens=500,
    )


def _provider(
    handler: httpx.MockTransport,
    *,
    schema_retries: int = 2,
    api_key: str = "test-model-secret",
) -> OpenAICompatibleModelProvider:
    return OpenAICompatibleModelProvider(
        base_url="https://models.example/v1/",
        api_key=SecretStr(api_key),
        model="example-model",
        timeout_seconds=3,
        schema_retries=schema_retries,
        transport=handler,
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"x-request-id": "request-123"},
        json={
            "id": "completion-123",
            "model": "example-model-2026-09-30",
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 9},
        },
    )


@pytest.mark.asyncio
async def test_structured_success_records_schema_usage_and_request_id() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://models.example/v1/chat/completions"
        captured.append(json.loads(request.content))
        return _chat_response(
            json.dumps(
                {
                    "primary_scene": "retention",
                    "rationale": "核心目标是次日留存。",
                },
                ensure_ascii=False,
            )
        )

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.generate_structured(_request(), SceneOutput)

    assert result.output.primary_scene == "retention"
    assert result.model == "example-model-2026-09-30"
    assert result.request_id == "request-123"
    assert result.usage.input_tokens == 21
    assert result.usage.output_tokens == 9
    response_format = captured[0]["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_schema_validation_retries_at_most_twice_then_succeeds() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return _chat_response('{"primary_scene":"retention"}')
        return _chat_response(
            '{"primary_scene":"retention","rationale":"留存目标明确"}'
        )

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.generate_structured(_request(), SceneOutput)

    assert result.output.primary_scene == "retention"
    assert calls == 3


@pytest.mark.asyncio
async def test_schema_validation_failure_is_safe_after_retry_budget() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _chat_response("not-json-and-must-not-be-leaked")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderSchemaError) as captured:
        await provider.generate_structured(_request(), SceneOutput)

    assert calls == 3
    assert captured.value.attempts == 3
    assert "not-json" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type", "retryable"),
    [
        (401, ProviderAuthenticationError, False),
        (429, ProviderRateLimitError, True),
    ],
)
async def test_authentication_and_rate_limit_errors_are_classified(
    status_code: int,
    error_type: type[ProviderError],
    retryable: bool,
) -> None:
    secret = "must-never-appear-in-errors"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(
            status_code,
            headers={"x-request-id": "failed-request"},
            json={"error": {"message": f"unsafe {secret}"}},
        )

    provider = _provider(httpx.MockTransport(handler), api_key=secret)
    with pytest.raises(error_type) as captured:
        await provider.generate_structured(_request(), SceneOutput)

    error = captured.value
    assert error.retryable is retryable
    assert error.request_id == "failed-request"
    assert secret not in str(error)
    assert secret not in repr(provider.__dict__)


@pytest.mark.asyncio
async def test_timeout_is_classified_without_retrying_schema() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("unsafe raw timeout", request=request)

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderTimeoutError) as captured:
        await provider.generate_structured(_request(), SceneOutput)

    assert calls == 1
    assert captured.value.retryable is True
    assert "unsafe raw timeout" not in str(captured.value)


def test_schema_retry_budget_cannot_exceed_two() -> None:
    with pytest.raises(ValueError, match="between 0 and 2"):
        _provider(httpx.MockTransport(lambda _request: _chat_response("{}")), schema_retries=3)
