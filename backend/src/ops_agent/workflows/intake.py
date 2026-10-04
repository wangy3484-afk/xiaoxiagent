"""Natural-language intake parsing with strict source-span provenance."""

import re

from pydantic import BaseModel, ConfigDict, Field

from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.providers.contracts import ModelMessage, ModelProvider, ModelRequest


class _ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _ExtractedText(_ExtractionModel):
    value: str = Field(min_length=1, max_length=2_000)
    source_excerpt: str = Field(min_length=1, max_length=500)


class _ExtractedList(_ExtractionModel):
    value: list[str] = Field(min_length=1, max_length=30)
    source_excerpt: str = Field(min_length=1, max_length=500)


class IntakeExtraction(_ExtractionModel):
    """Model output uses exact input spans; omitted values remain unknown."""

    business_context: _ExtractedText | None = None
    current_problem: _ExtractedText | None = None
    operation_goal: _ExtractedText | None = None
    target_users: _ExtractedText | None = None
    business_stage: _ExtractedText | None = None
    execution_period: _ExtractedText | None = None
    budget_and_resources: _ExtractedText | None = None
    existing_channels: _ExtractedList | None = None
    current_baseline: _ExtractedText | None = None
    constraints: _ExtractedList | None = None
    preferred_benchmark_companies: _ExtractedList | None = None


async def parse_intake(raw_input: str, model: ModelProvider) -> OperationsBrief:
    """Extract only user-supported facts and explicitly preserve every gap."""
    normalized_input = raw_input.strip()
    if not normalized_input:
        raise ValueError("operations scenario input cannot be empty")
    if len(normalized_input) > 20_000:
        raise ValueError("operations scenario input cannot exceed 20000 characters")

    response = await model.generate_structured(
        ModelRequest(
            purpose="parse_intake",
            messages=(
                ModelMessage(role="system", content=_SYSTEM_PROMPT),
                ModelMessage(role="user", content=normalized_input),
            ),
            max_output_tokens=3_000,
            temperature=0,
        ),
        IntakeExtraction,
    )
    extracted = response.output
    return OperationsBrief(
        business_context=_confirmed_text(extracted.business_context, normalized_input),
        current_problem=_confirmed_text(extracted.current_problem, normalized_input),
        operation_goal=_confirmed_text(extracted.operation_goal, normalized_input),
        target_users=_confirmed_text(extracted.target_users, normalized_input),
        business_stage=_confirmed_text(extracted.business_stage, normalized_input),
        execution_period=_confirmed_text(extracted.execution_period, normalized_input),
        budget_and_resources=_confirmed_text(
            extracted.budget_and_resources, normalized_input
        ),
        existing_channels=_confirmed_list(extracted.existing_channels, normalized_input),
        current_baseline=_confirmed_text(extracted.current_baseline, normalized_input),
        constraints=_confirmed_list(extracted.constraints, normalized_input),
        preferred_benchmark_companies=_confirmed_list(
            extracted.preferred_benchmark_companies, normalized_input
        ),
    )


def _confirmed_text(
    extracted: _ExtractedText | None,
    raw_input: str,
) -> BriefField[str]:
    if extracted is None or not _supported_excerpt(extracted.source_excerpt, raw_input):
        return BriefField[str].unknown()
    if not _supported_excerpt(extracted.value, extracted.source_excerpt):
        return BriefField[str].unknown()
    return BriefField[str].from_user(extracted.value, extracted.source_excerpt)


def _confirmed_list(
    extracted: _ExtractedList | None,
    raw_input: str,
) -> BriefField[list[str]]:
    if extracted is None or not _supported_excerpt(extracted.source_excerpt, raw_input):
        return BriefField[list[str]].unknown()
    values = list(dict.fromkeys(value.strip() for value in extracted.value if value.strip()))
    if not values or any(
        not _supported_excerpt(value, extracted.source_excerpt) for value in values
    ):
        return BriefField[list[str]].unknown()
    return BriefField[list[str]].from_user(values, extracted.source_excerpt)


def _supported_excerpt(candidate: str, source: str) -> bool:
    return _normalize_span(candidate) in _normalize_span(source)


def _normalize_span(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


_SYSTEM_PROMPT = "\n".join(
    (
        "你是运营需求提取器。只提取用户明确写出的事实，不得推测、补全、改写数字或默认行业信息。",
        "每个非空字段都必须：",
        "1. value 使用用户原文中的连续文字；列表中的每个值也必须逐字出现在 source_excerpt 中；",
        "2. source_excerpt 逐字复制用户输入中能够支持该字段的最短片段；",
        "3. 无法确认的字段返回 null；不要用‘未知’‘无’‘待确认’等占位文本。",
        "字段含义：business_context 业务与产品背景；current_problem 当前问题；",
        "operation_goal 运营目标；target_users 目标用户；business_stage 业务阶段；",
        "execution_period 执行周期；budget_and_resources 预算与人员/工具资源；",
        "existing_channels 已有运营渠道；current_baseline 当前汇总基线；",
        "constraints 明确限制；preferred_benchmark_companies 用户点名的参考企业。",
    )
)
