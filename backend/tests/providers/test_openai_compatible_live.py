"""Optional live smoke for an OpenAI-compatible JSON-object model provider."""

import os

import pytest
from ops_agent.providers import ModelMessage, ModelRequest, OpenAICompatibleModelProvider
from pydantic import BaseModel, SecretStr


class ArithmeticAnswer(BaseModel):
    answer: int


@pytest.mark.integration
@pytest.mark.asyncio
async def test_json_object_live_smoke_when_explicit_key_is_available() -> None:
    api_key = os.getenv("OPS_AGENT_TEST_MODEL_API_KEY")
    if not api_key:
        pytest.skip("OPS_AGENT_TEST_MODEL_API_KEY is not configured")

    provider = OpenAICompatibleModelProvider(
        base_url=os.getenv("OPS_AGENT_TEST_MODEL_BASE_URL", "https://api.deepseek.com"),
        api_key=SecretStr(api_key),
        model=os.getenv("OPS_AGENT_TEST_MODEL_NAME", "deepseek-flash"),
        timeout_seconds=60,
        schema_retries=1,
        structured_output_mode="json_object",
        thinking_mode="disabled",
    )
    result = await provider.generate_structured(
        ModelRequest(
            purpose="provider_smoke",
            messages=(ModelMessage(role="user", content="Return JSON: 1 + 1 = ?"),),
            max_output_tokens=100,
        ),
        ArithmeticAnswer,
    )

    assert result.output.answer == 2
    assert result.usage.total_tokens > 0
    assert api_key not in repr(result)
