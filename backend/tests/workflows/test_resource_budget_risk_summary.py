"""Resource, budget, and risk consolidation tests."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief, OperationsScene
from ops_agent.domain.report import (
    ActionPlan,
    EstimateExpression,
    MeasurementPlan,
    ResourceCategory,
    StrategyOption,
    StrategyPriority,
)
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.strategy import build_resource_budget_risk_summary


def _brief(*, with_budget_ceiling: bool) -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("社区团购小程序", "社区团购小程序"),
        operation_goal=BriefField[str].from_user("提升新客首单转化", "提升新客首单转化"),
        target_users=BriefField[str].from_user("新注册家庭用户", "新注册家庭用户"),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        budget_and_resources=(
            BriefField[str].from_user(
                "预算上限5万元，现有2名运营",
                "预算上限5万元，现有2名运营",
            )
            if with_budget_ceiling
            else BriefField[str].unknown()
        ),
    )


def _strategy() -> StrategyOption:
    return StrategyOption(
        strategy_id="strategy-community-first-order",
        scene=OperationsScene.ACQUISITION,
        title="社群首单承接实验",
        target_segment="新注册家庭用户",
        strategy_logic="验证社群信任背书是否改善首单承接。",
        evidence_ids=["ev-case"],
        applicability_conditions=["社群触达可归因"],
        scene_differences=["当前资源少于头部平台"],
        adaptations=["缩小到2个社区做最小实验"],
        impact_path=["提高触达信任", "降低首单门槛"],
        non_copyable_factors=["头部平台自然流量"],
        risks=["补贴吸引低质量用户"],
        priority=StrategyPriority.MUST,
    )


def _action_plan() -> ActionPlan:
    return ActionPlan.model_validate(
        {
            "plan_id": "action-plan-1",
            "phases": ["0-30天"],
            "actions": [
                {
                    "action_id": "action-1",
                    "strategy_id": "strategy-community-first-order",
                    "phase": "0-30天",
                    "goal": "验证首单承接",
                    "target_audience": "新注册家庭用户",
                    "action": "在2个社群上线首单承接实验",
                    "touchpoint": "微信群和小程序落地页",
                    "owner_role": "增长运营",
                    "prerequisites": ["渠道可归因"],
                    "resources": ["2名运营"],
                    "deliverable": "实验复盘表",
                    "timeline": "第1-30天",
                    "acceptance_criteria": ["完成数据记录"],
                }
            ],
        }
    )


def _measurement_plan() -> MeasurementPlan:
    metric_payload = {
        "definition": "符合条件用户的统一指标计算口径",
        "formula": "符合条件用户数 / 总用户数",
        "data_source": "小程序埋点",
        "observation_period": "实验后7天",
        "decision_rule": "达到目标且风险不恶化时继续",
    }
    return MeasurementPlan.model_validate(
        {
            "plan_id": "measurement-plan-1",
            "metrics": [
                {
                    "metric_id": "metric-outcome",
                    "name": "首单转化率",
                    "metric_type": "outcome",
                    **metric_payload,
                },
                {
                    "metric_id": "metric-process",
                    "name": "社群触达率",
                    "metric_type": "process",
                    **metric_payload,
                },
                {
                    "metric_id": "metric-risk",
                    "name": "退款投诉率",
                    "metric_type": "risk",
                    **metric_payload,
                },
            ],
            "experiments": [
                {
                    "experiment_id": "experiment-1",
                    "hypothesis_claim_id": "hypothesis-1",
                    "linked_strategy_ids": ["strategy-community-first-order"],
                    "target_segment": "新注册家庭用户",
                    "design": "选择2个社区开展小范围对照实验。",
                    "comparison": "实验组与自然流量组",
                    "duration": "2周",
                    "primary_metric_ids": ["metric-outcome"],
                    "success_criteria": ["形成有效基线"],
                    "sample_size_method": "覆盖完整周期内符合条件的用户",
                    "stop_conditions": ["退款投诉率恶化"],
                }
            ],
        }
    )


def _requirement(
    requirement_id: str,
    category: str,
    item: str,
    priority: str,
) -> dict[str, object]:
    return {
        "requirement_id": requirement_id,
        "category": category,
        "item": item,
        "quantity_or_capacity": "满足最小实验需要",
        "estimate": "50000元" if category == "budget" else "按行动计划配置",
        "estimate_expression": "user_provided",
        "estimation_basis": "按预算上限和最小实验范围测算",
        "needs_confirmation": False,
        "priority": priority,
        "linked_strategy_ids": ["strategy-community-first-order"],
    }


def _summary_response() -> dict[str, object]:
    requirements = [
        _requirement("resource-personnel", "personnel", "增长运营", "must"),
        _requirement("resource-channel", "channel", "2个社区社群", "must"),
        _requirement("resource-tool", "tool", "埋点与看板", "should"),
        _requirement("resource-content", "content_capacity", "落地页与社群素材", "should"),
        _requirement("resource-time", "time", "2周实验周期", "must"),
        _requirement("resource-budget", "budget", "实验预算", "could"),
    ]
    return {
        "summary_id": "resource-summary-1",
        "has_confirmed_budget_ceiling": True,
        "budget_ceiling": "50000元",
        "requirements": requirements,
        "priority_order": [item["requirement_id"] for item in requirements],
        "trade_offs": ["优先保障社群实验，暂缓跨平台付费放量"],
        "excluded_scope": ["当前预算内不同时开展多个付费渠道"],
        "assumptions": ["现有2名运营可投入实验"],
        "risks": [
            {
                "risk": "补贴吸引低质量用户",
                "trigger": "退款投诉率持续恶化",
                "mitigation": "停止扩量并复核人群与权益门槛",
                "owner_role": "增长运营负责人",
                "monitoring_metric_ids": ["metric-risk"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_budget_ceiling_produces_priorities_and_explicit_trade_offs() -> None:
    model = DeterministicModelProvider(
        {"build_resource_budget_risk_summary": _summary_response()}
    )

    summary = await build_resource_budget_risk_summary(
        _brief(with_budget_ceiling=True),
        [_strategy()],
        _action_plan(),
        _measurement_plan(),
        model,
    )

    assert summary.has_confirmed_budget_ceiling is True
    assert summary.budget_ceiling == "预算上限5万元，现有2名运营"
    assert summary.priority_order[0] == "resource-personnel"
    assert summary.trade_offs
    assert summary.excluded_scope


@pytest.mark.asyncio
async def test_unknown_budget_removes_precise_amount_and_requires_confirmation() -> None:
    model = DeterministicModelProvider(
        {"build_resource_budget_risk_summary": _summary_response()}
    )

    summary = await build_resource_budget_risk_summary(
        _brief(with_budget_ceiling=False),
        [_strategy()],
        _action_plan(),
        _measurement_plan(),
        model,
    )

    budget = next(
        item
        for item in summary.requirements
        if item.category is ResourceCategory.BUDGET
    )
    assert summary.has_confirmed_budget_ceiling is False
    assert summary.budget_ceiling is None
    assert budget.estimate_expression is EstimateExpression.FORMULA
    assert budget.needs_confirmation is True
    assert "50000" not in budget.estimate
    assert any("未提供可用预算上限" in item for item in summary.assumptions)
