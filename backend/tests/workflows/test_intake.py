"""Tests for source-grounded natural-language intake parsing."""

import pytest
from ops_agent.domain.intake import FieldStatus
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.intake import parse_intake


@pytest.mark.asyncio
async def test_complete_input_is_structured_with_user_provenance() -> None:
    raw = (
        "我们是社区生鲜电商，处于区域扩张期。当前新客首单转化偏低，"
        "目标是提升合格新客首单转化。目标用户是一二线城市的新注册家庭用户。"
        "计划未来90天执行，预算20万元、2名运营。已有微信社群和应用商店渠道，"
        "注册到首单转化率8%。限制是不使用用户个人明细、不自动投放。希望参考京东和淘宝。"
    )
    model = DeterministicModelProvider(
        {
            "parse_intake": {
                "business_context": {
                    "value": "社区生鲜电商",
                    "source_excerpt": "我们是社区生鲜电商",
                },
                "current_problem": {
                    "value": "新客首单转化偏低",
                    "source_excerpt": "当前新客首单转化偏低",
                },
                "operation_goal": {
                    "value": "提升合格新客首单转化",
                    "source_excerpt": "目标是提升合格新客首单转化",
                },
                "target_users": {
                    "value": "一二线城市的新注册家庭用户",
                    "source_excerpt": "目标用户是一二线城市的新注册家庭用户",
                },
                "business_stage": {
                    "value": "区域扩张期",
                    "source_excerpt": "处于区域扩张期",
                },
                "execution_period": {
                    "value": "未来90天",
                    "source_excerpt": "计划未来90天执行",
                },
                "budget_and_resources": {
                    "value": "预算20万元、2名运营",
                    "source_excerpt": "预算20万元、2名运营",
                },
                "existing_channels": {
                    "value": ["微信社群", "应用商店"],
                    "source_excerpt": "已有微信社群和应用商店渠道",
                },
                "current_baseline": {
                    "value": "注册到首单转化率8%",
                    "source_excerpt": "注册到首单转化率8%",
                },
                "constraints": {
                    "value": ["不使用用户个人明细", "不自动投放"],
                    "source_excerpt": "限制是不使用用户个人明细、不自动投放",
                },
                "preferred_benchmark_companies": {
                    "value": ["京东", "淘宝"],
                    "source_excerpt": "希望参考京东和淘宝",
                },
            }
        }
    )

    brief = await parse_intake(raw, model)

    assert brief.unknown_fields() == []
    assert brief.operation_goal.value == "提升合格新客首单转化"
    assert brief.operation_goal.source_excerpt == "目标是提升合格新客首单转化"
    assert brief.existing_channels.value == ["微信社群", "应用商店"]
    assert brief.current_baseline.asserted_as_fact is True


@pytest.mark.asyncio
async def test_ambiguous_idea_preserves_missing_fields_as_unknown() -> None:
    model = DeterministicModelProvider(
        {
            "parse_intake": {
                "operation_goal": {
                    "value": "提高新用户留存",
                    "source_excerpt": "想提高新用户留存",
                }
            }
        }
    )

    brief = await parse_intake("想提高新用户留存", model)

    assert brief.operation_goal.value == "提高新用户留存"
    assert brief.target_users.status is FieldStatus.UNKNOWN
    assert brief.current_baseline.status is FieldStatus.UNKNOWN
    assert "budget_and_resources" in brief.unknown_fields()


@pytest.mark.asyncio
async def test_unsupported_model_claims_are_dropped_instead_of_becoming_facts() -> None:
    model = DeterministicModelProvider(
        {
            "parse_intake": {
                "operation_goal": {
                    "value": "提升留存",
                    "source_excerpt": "目标是提升留存",
                },
                "current_baseline": {
                    "value": "次日留存20%",
                    "source_excerpt": "行业通常次日留存20%",
                },
            }
        }
    )

    brief = await parse_intake("目标是提升留存", model)

    assert brief.operation_goal.status is FieldStatus.CONFIRMED
    assert brief.current_baseline.status is FieldStatus.UNKNOWN
    assert brief.current_baseline.asserted_as_fact is False


@pytest.mark.asyncio
async def test_empty_input_is_rejected_before_model_call() -> None:
    model = DeterministicModelProvider({})

    with pytest.raises(ValueError, match="cannot be empty"):
        await parse_intake("   ", model)

    assert model.calls == []
