"""Measurement and experiment planning tests."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief, OperationsScene
from ops_agent.domain.report import ActionPlan, StrategyOption, StrategyPriority, TargetBasis
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.strategy import build_measurement_plan


def _brief(*, with_baseline: bool) -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("社区团购小程序", "社区团购小程序"),
        operation_goal=BriefField[str].from_user("提升新客首单转化", "提升新客首单转化"),
        target_users=BriefField[str].from_user("新注册家庭用户", "新注册家庭用户"),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        current_baseline=(
            BriefField[str].from_user("当前首单转化率10%", "当前首单转化率10%")
            if with_baseline
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
        assumption_claim_ids=[],
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


def _metric(
    metric_id: str,
    metric_type: str,
    name: str,
) -> dict[str, object]:
    return {
        "metric_id": metric_id,
        "name": name,
        "metric_type": metric_type,
        "definition": f"{name}的统一口径",
        "formula": f"{name}用户数 / 符合条件用户数",
        "data_source": "小程序埋点",
        "observation_period": "实验后7天",
        "decision_rule": "达到目标区间且风险不恶化时进入下一轮",
        "baseline_value": 10.0,
        "baseline_source": "用户提供当前基线",
        "target": {
            "lower_bound": 12.0,
            "upper_bound": 15.0,
            "unit": "%",
            "basis": "provided_baseline",
            "rationale": "基于用户提供的当前10%基线设置小幅区间",
            "is_hypothesis": False,
        },
    }


def _measurement_response() -> dict[str, object]:
    return {
        "plan_id": "measurement-plan-1",
        "metrics": [
            _metric("metric_first_order", "outcome", "首单转化率"),
            _metric("metric_landing_click", "process", "落地页点击率"),
            _metric("metric_refund_complaint", "risk", "退款投诉率"),
        ],
        "experiments": [
            {
                "experiment_id": "experiment-baseline",
                "hypothesis_claim_id": "hyp-1",
                "linked_strategy_ids": ["strategy-community-first-order"],
                "target_segment": "新注册家庭用户",
                "design": "选择2个社群上线首单承接实验，并保留自然流量对照。",
                "comparison": "社群实验组对比自然流量组",
                "duration": "2周",
                "primary_metric_ids": ["metric_first_order"],
                "success_criteria": ["首单转化率提升30%"],
                "sample_size_method": "记录完整实验周期内所有符合条件用户",
                "stop_conditions": ["退款投诉率升高", "无法归因渠道来源"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_measurement_plan_keeps_baseline_based_targets_when_baseline_exists() -> None:
    model = DeterministicModelProvider({"build_measurement_plan": _measurement_response()})

    plan = await build_measurement_plan(
        _brief(with_baseline=True),
        [_strategy()],
        _action_plan(),
        model,
    )

    assert {metric.metric_type.value for metric in plan.metrics} == {
        "outcome",
        "process",
        "risk",
    }
    assert all(metric.target is not None for metric in plan.metrics)
    assert all(
        metric.target and metric.target.basis is TargetBasis.PROVIDED_BASELINE
        for metric in plan.metrics
    )
    assert all(metric.target and not metric.target.is_hypothesis for metric in plan.metrics)


@pytest.mark.asyncio
async def test_measurement_plan_without_baseline_creates_validation_targets() -> None:
    model = DeterministicModelProvider({"build_measurement_plan": _measurement_response()})

    plan = await build_measurement_plan(
        _brief(with_baseline=False),
        [_strategy()],
        _action_plan(),
        model,
    )

    assert all(metric.baseline_value is None for metric in plan.metrics)
    assert all(metric.baseline_source is None for metric in plan.metrics)
    assert all(metric.target is not None for metric in plan.metrics)
    assert all(
        metric.target and metric.target.basis is TargetBasis.TO_BE_VALIDATED
        for metric in plan.metrics
    )
    assert all(metric.target and metric.target.is_hypothesis for metric in plan.metrics)
    criteria_text = " ".join(
        criterion
        for experiment in plan.experiments
        for criterion in experiment.success_criteria
    )
    assert "提升30%" not in criteria_text
    assert "基线记录" in criteria_text
