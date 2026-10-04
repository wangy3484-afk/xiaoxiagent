"""Phased action-plan generation tests."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief, OperationsScene
from ops_agent.domain.report import ActionPlan, StrategyOption, StrategyPriority
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.strategy import build_action_plan
from pydantic import ValidationError


def _brief_without_period() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("社区团购小程序", "社区团购小程序"),
        operation_goal=BriefField[str].from_user("提升新客首单转化", "提升新客首单转化"),
        target_users=BriefField[str].from_user("新注册家庭用户", "新注册家庭用户"),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        budget_and_resources=BriefField[str].from_user("2名运营", "2名运营"),
    )


def _strategy() -> StrategyOption:
    return StrategyOption(
        strategy_id="strategy-community-first-order",
        scene=OperationsScene.ACQUISITION,
        title="社群首单承接实验",
        target_segment="新注册家庭用户",
        strategy_logic="先用社群信任背书验证首单转化，再决定是否扩大。",
        evidence_ids=["ev-case"],
        assumption_claim_ids=[],
        applicability_conditions=["社群触达可归因"],
        scene_differences=["当前资源少于头部平台"],
        adaptations=["缩小到2个社区做最小实验"],
        impact_path=["提高触达信任", "降低首单门槛"],
        non_copyable_factors=["头部平台自然流量"],
        risks=["补贴吸引低质量用户"],
        priority=StrategyPriority.MUST,
    )


def _action(
    action_id: str,
    phase: str,
    timeline: str,
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "strategy_id": "strategy-community-first-order",
        "phase": phase,
        "goal": "验证社群首单承接是否可行",
        "target_audience": "新注册家庭用户",
        "action": "搭建社群首单承接链路并记录分渠道数据",
        "touchpoint": "微信群和小程序落地页",
        "owner_role": "增长运营",
        "prerequisites": ["可记录社群来源", "首单权益规则确认"],
        "resources": ["2名运营", "小程序落地页"],
        "deliverable": f"{phase}行动复盘表",
        "timeline": timeline,
        "acceptance_criteria": ["完成交付物", "记录关键漏斗数据"],
    }


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "build_action_plan": {
                "plan_id": "action-plan-1",
                "phases": ["0-30天", "31-60天", "61-90天"],
                "actions": [
                    _action("action-30", "0-30天", "第1-30天"),
                    _action("action-60", "31-60天", "第31-60天"),
                    _action("action-90", "61-90天", "第61-90天"),
                ],
            }
        }
    )


@pytest.mark.asyncio
async def test_action_plan_uses_default_30_60_90_when_period_missing() -> None:
    plan = await build_action_plan(_brief_without_period(), [_strategy()], _model())

    assert plan.phases == ["0-30天", "31-60天", "61-90天"]
    assert [action.phase for action in plan.actions] == plan.phases
    assert all(action.owner_role for action in plan.actions)
    assert all(action.prerequisites for action in plan.actions)
    assert all(action.resources for action in plan.actions)
    assert all(action.deliverable for action in plan.actions)
    assert all(action.acceptance_criteria for action in plan.actions)


def test_action_plan_rejects_action_missing_closed_loop_fields() -> None:
    incomplete_action = _action("action-missing-owner", "0-30天", "第1-30天")
    del incomplete_action["owner_role"]

    with pytest.raises(ValidationError) as exc_info:
        ActionPlan.model_validate(
            {
                "plan_id": "action-plan-invalid",
                "phases": ["0-30天"],
                "actions": [incomplete_action],
            }
        )

    assert "owner_role" in str(exc_info.value)
