"""Acquisition-growth strategy module tests."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.domain.report import (
    Diagnosis,
    GoalRelationship,
    TargetBasis,
)
from ops_agent.domain.research import (
    Claim,
    ClaimType,
    EvidenceBundle,
    EvidenceVerificationStatus,
)
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.strategy import build_acquisition_strategy


def _brief_without_baseline() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("社区团购小程序", "社区团购小程序"),
        operation_goal=BriefField[str].from_user(
            "提升新客首单转化", "提升新客首单转化"
        ),
        target_users=BriefField[str].from_user(
            "三四线城市新注册家庭用户", "三四线城市新注册家庭用户"
        ),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        budget_and_resources=BriefField[str].from_user("2名运营", "2名运营"),
        existing_channels=BriefField[list[str]].from_user(
            ["社群", "小红书"], "社群、小红书"
        ),
        current_baseline=BriefField[str].unknown(),
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        business_stage="冷启动阶段",
        target_users="三四线城市新注册家庭用户",
        goal_relationships=[
            GoalRelationship(
                business_goal="提升有效订单规模",
                operations_goal="提升新客首单转化",
                target_behavior="目标用户完成首单并留下可持续触达关系",
                metric_ids=["metric_first_order"],
            )
        ],
        behavior_path=["触达", "理解价值", "注册", "完成首单"],
        core_problem="尚未确认哪个渠道能以可接受成本带来合格新客。",
        supporting_claim_ids=["hyp-1"],
        constraints=["2名运营"],
        priority_rationale="先验证渠道质量和首单承接，再考虑放大。",
        alternative_explanations=["价值表达不清", "渠道人群不匹配"],
        data_needed=["分渠道首单转化率", "合格新客获客成本"],
    )


def _evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        claims=[
            Claim(
                claim_id="hyp-1",
                text="社群和小红书可能带来更匹配的早期新客。",
                claim_type=ClaimType.HYPOTHESIS,
                evidence_ids=[],
                reasoning="需要通过渠道实验验证。",
                verification_status=EvidenceVerificationStatus.UNVERIFIED,
            )
        ],
        evidence=[],
        links=[],
    )


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "design_acquisition_strategy": {
                "plan_id": "acq-plan-1",
                "has_reliable_baseline": True,
                "target_segments": [
                    {
                        "segment_id": "seg-family",
                        "description": "三四线城市首次使用社区团购的家庭用户",
                        "qualification_criteria": ["注册后7天内完成首单"],
                        "first_value_action": "完成首单并加入社群",
                        "excluded_segments": ["只薅补贴且不复购用户"],
                    }
                ],
                "value_propositions": [
                    {
                        "proposition_id": "vp-fresh",
                        "target_segment_id": "seg-family",
                        "pain_point": "日常生鲜购买决策时间短且信任要求高",
                        "message": "用社区邻里推荐降低首次购买决策成本",
                        "proof_needed": ["首单后复购率", "社群咨询转化"],
                    }
                ],
                "channel_mix": [
                    {
                        "channel_id": "ch-community",
                        "channel_name": "社群裂变",
                        "role": "explore",
                        "target_segment_id": "seg-family",
                        "value_proposition_id": "vp-fresh",
                        "traffic_source": "已有社区微信群和团长触达",
                        "touchpoints": ["微信群", "小程序落地页"],
                        "conversion_path": ["社群触达", "落地页注册", "完成首单"],
                        "cost_hypothesis_id": "cac-community",
                    }
                ],
                "conversion_funnel": [
                    {
                        "step_id": "step-reach",
                        "name": "触达",
                        "user_action": "看到社群首单权益",
                        "metric_id": "metric_reach_to_visit",
                        "dropoff_risk": "权益表达不清导致点击不足",
                    },
                    {
                        "step_id": "step-first-order",
                        "name": "首单",
                        "user_action": "完成首单",
                        "metric_id": "metric_first_order",
                        "dropoff_risk": "落地页信任不足或运费门槛过高",
                    },
                ],
                "cac_assumptions": [
                    {
                        "assumption_id": "cac-community",
                        "channel_id": "ch-community",
                        "formula": "可归因渠道成本 / 合格新客数",
                        "known_inputs": ["2名运营"],
                        "unknown_inputs": ["合格新客数"],
                        "estimated_cac_range": "预计合格新客成本20元以内",
                        "target_basis": "provided_baseline",
                        "is_hypothesis": False,
                        "validation_method": "用两周实验统计渠道成本和首单用户数",
                    }
                ],
                "channel_experiments": [
                    {
                        "experiment_id": "exp-community",
                        "channel_id": "ch-community",
                        "hypothesis": "社群团长背书可以降低新客首单决策成本",
                        "design": "选择2个社区进行社群首单权益实验，保留自然流量对照。",
                        "duration": "两周",
                        "primary_metric_id": "metric_first_order",
                        "success_criteria": ["首单转化率提升30%"],
                        "stop_conditions": ["投诉率上升", "无法归因渠道成本"],
                        "expected_outcome_basis": "provided_baseline",
                        "is_success_target_hypothesis": False,
                    }
                ],
                "strategy_options": [
                    {
                        "strategy_id": "strategy-community-first-order",
                        "scene": "acquisition",
                        "title": "社群首单承接实验",
                        "target_segment": "三四线城市新注册家庭用户",
                        "strategy_logic": "先用社群信任背书验证首单转化，再决定是否扩大。",
                        "evidence_ids": [],
                        "assumption_claim_ids": ["hyp-1"],
                        "applicability_conditions": ["社群触达可归因"],
                        "scene_differences": ["当前资源少于头部平台"],
                        "adaptations": ["缩小到2个社区做最小实验"],
                        "impact_path": ["提高触达信任", "降低首单门槛", "观察合格新客成本"],
                        "non_copyable_factors": ["头部平台自然流量"],
                        "risks": ["补贴吸引低质量用户"],
                        "priority": "must",
                    }
                ],
                "limitations": ["模型草案假设已有基线"],
            }
        }
    )


@pytest.mark.asyncio
async def test_acquisition_strategy_golden_sample_without_baseline_is_hypothetical() -> None:
    plan = await build_acquisition_strategy(
        _brief_without_baseline(),
        _diagnosis(),
        _evidence_bundle(),
        _model(),
    )

    assert plan.target_segments[0].qualification_criteria
    assert plan.value_propositions[0].proof_needed
    assert plan.channel_mix[0].conversion_path == ["社群触达", "落地页注册", "完成首单"]
    assert len(plan.conversion_funnel) >= 2
    assert plan.cac_assumptions
    assert plan.channel_experiments
    assert plan.has_reliable_baseline is False
    assert all(
        assumption.target_basis is TargetBasis.TO_BE_VALIDATED
        and assumption.is_hypothesis
        for assumption in plan.cac_assumptions
    )
    assert all(
        experiment.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
        and experiment.is_success_target_hypothesis
        for experiment in plan.channel_experiments
    )
    criteria_text = " ".join(
        criterion
        for experiment in plan.channel_experiments
        for criterion in experiment.success_criteria
    )
    assert "提升30%" not in criteria_text
    assert "基线记录" in criteria_text
