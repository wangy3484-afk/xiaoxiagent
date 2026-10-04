"""Campaign-operations strategy module tests."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.domain.report import (
    CampaignPhase,
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
from ops_agent.workflows.strategy import build_campaign_strategy


def _brief_without_baseline() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("会员电商小程序", "会员电商小程序"),
        current_problem=BriefField[str].from_user(
            "准备做7天会员日活动，但不知道机制和节奏怎么定",
            "准备做7天会员日活动",
        ),
        operation_goal=BriefField[str].from_user(
            "提升活动期会员复购", "提升活动期会员复购"
        ),
        target_users=BriefField[str].from_user("近30天访问但未复购会员", "近30天访问"),
        business_stage=BriefField[str].from_user("稳定增长期", "稳定增长期"),
        execution_period=BriefField[str].from_user("10月1日至10月7日", "10月1日至10月7日"),
        budget_and_resources=BriefField[str].from_user(
            "预算2万元，2名运营，客服资源有限", "预算2万元，2名运营"
        ),
        existing_channels=BriefField[list[str]].from_user(
            ["站内弹窗", "社群", "公众号"], "站内弹窗、社群、公众号"
        ),
        current_baseline=BriefField[str].unknown(),
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        business_stage="稳定增长期",
        target_users="近30天访问但未复购会员",
        goal_relationships=[
            GoalRelationship(
                business_goal="提升会员复购收入",
                operations_goal="提升活动期会员复购",
                target_behavior="目标会员在活动期完成一次复购",
                metric_ids=["metric_incremental_purchase"],
            )
        ],
        behavior_path=["看到活动", "理解权益", "参与活动", "完成复购"],
        core_problem="活动第一目标、权益成本和峰值承载尚未形成闭环。",
        supporting_claim_ids=["hyp-campaign"],
        constraints=["预算2万元", "客服资源有限"],
        priority_rationale="先控制活动机制和承载风险，再验证是否产生增量。",
        alternative_explanations=["自然需求搬运", "权益门槛过高"],
        data_needed=["可比基线", "活动参与漏斗", "异常和投诉率"],
    )


def _evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        claims=[
            Claim(
                claim_id="hyp-campaign",
                text="明确单一目标和五阶段节奏可能降低活动执行风险。",
                claim_type=ClaimType.HYPOTHESIS,
                evidence_ids=[],
                reasoning="当前没有历史活动基线，需要活动期记录验证。",
                verification_status=EvidenceVerificationStatus.UNVERIFIED,
            )
        ],
        evidence=[],
        links=[],
    )


def _phase(
    phase: str,
    objective: str,
    timing: str,
    criteria: list[str] | None = None,
) -> dict[str, object]:
    return {
        "phase": phase,
        "objective": objective,
        "timing": timing,
        "touchpoints": ["站内弹窗", "社群"],
        "content_or_action": "发布该阶段活动信息并检查关键链路",
        "owner_role": "活动运营",
        "resources": ["活动页面", "客服排班"],
        "deliverable": f"{objective}阶段交付物",
        "acceptance_criteria": criteria or ["阶段物料上线并完成检查"],
    }


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "design_campaign_strategy": {
                "plan_id": "campaign-plan-1",
                "has_reliable_baseline": True,
                "goals": [
                    {
                        "goal_id": "goal-repurchase",
                        "primary_goal": "提升活动期会员复购",
                        "target_behavior": "近30天访问未复购会员完成一次复购",
                        "guardrail_goals": ["投诉率不升高", "预算不超2万元"],
                        "non_priority_goals": ["品牌曝光"],
                    }
                ],
                "audiences": [
                    {
                        "audience_id": "aud-recent-members",
                        "description": "近30天访问但未复购会员",
                        "eligibility_rule": "近30天有访问且活动前未复购",
                        "motivation": "希望用更低决策成本完成一次会员复购",
                        "exclusion_rule": "排除退款投诉和高风险异常账号",
                    }
                ],
                "mechanisms": [
                    {
                        "mechanism_id": "mech-threshold-benefit",
                        "audience_id": "aud-recent-members",
                        "target_behavior": "活动期完成一次复购",
                        "participation_rule": "活动期下单并满足会员权益门槛",
                        "incentive_design": "阶梯权益引导复购但设置预算上限",
                        "cost_cap": "总权益成本不超过2万元",
                        "anti_abuse_rule": "同一设备和手机号仅可领取一次核心权益",
                        "expected_outcome_basis": "provided_baseline",
                        "is_outcome_hypothesis": False,
                    }
                ],
                "rhythm": [
                    _phase("warm_up", "完成预热", "活动前3天"),
                    _phase("launch", "完成上线", "10月1日", ["GMV提升50%"]),
                    _phase("sustain", "持续运营", "10月2日至10月6日"),
                    _phase("close", "完成收尾", "10月7日"),
                    _phase("retrospective", "完成复盘", "活动后3天内"),
                ],
                "resources": [
                    {
                        "resource_id": "res-budget",
                        "resource_type": "权益预算",
                        "requirement": "权益预算和核销记录",
                        "capacity_limit": "预算2万元封顶",
                        "owner_role": "活动运营",
                    },
                    {
                        "resource_id": "res-service",
                        "resource_type": "客服",
                        "requirement": "活动期间高峰问题响应",
                        "capacity_limit": "客服资源有限，超过阈值切换 FAQ 自助",
                        "owner_role": "客服负责人",
                    },
                ],
                "metrics": [
                    {
                        "metric_id": "metric_incremental_purchase",
                        "name": "活动增量复购",
                        "formula": "活动期复购用户数 - 可比基线复购用户数",
                        "observation_window": "10月1日至10月7日",
                        "decision_rule": "复购提升20%则复用机制",
                        "target_basis": "provided_baseline",
                        "is_target_hypothesis": False,
                    },
                    {
                        "metric_id": "metric_cost_abuse",
                        "name": "活动成本与异常率",
                        "formula": "活动总成本 / 增量复购用户数，并监控异常用户数 / 参与用户数",
                        "observation_window": "活动全周期",
                        "decision_rule": "异常或投诉达到阈值时降级",
                        "target_basis": "provided_baseline",
                        "is_target_hypothesis": False,
                    },
                ],
                "contingency_plans": [
                    {
                        "contingency_id": "contingency-budget",
                        "risk": "权益预算超支或异常领取",
                        "trigger_threshold": "权益核销达到预算80%或异常率升高",
                        "response_action": "暂停高成本权益，切换低成本内容引导",
                        "owner_role": "活动运营",
                        "monitoring_metric_id": "metric_cost_abuse",
                    },
                    {
                        "contingency_id": "contingency-service",
                        "risk": "客服峰值无法承接",
                        "trigger_threshold": "待响应咨询超过客服容量",
                        "response_action": "上线 FAQ 和社群置顶，延后非紧急问题",
                        "owner_role": "客服负责人",
                        "monitoring_metric_id": "metric_cost_abuse",
                    },
                ],
                "retrospective": {
                    "review_time": "活动后3天内",
                    "required_inputs": ["活动参与漏斗", "权益成本", "异常投诉", "可比基线"],
                    "analysis_questions": ["是否产生增量", "哪个阶段掉队", "异常是否可控"],
                    "follow_up_decisions": ["复用机制", "调整权益", "停止该机制"],
                },
                "strategy_options": [
                    {
                        "strategy_id": "strategy-member-day",
                        "scene": "campaign",
                        "title": "会员日复购活动最小验证",
                        "target_segment": "近30天访问但未复购会员",
                        "strategy_logic": "用受控权益和五阶段节奏验证复购增量。",
                        "evidence_ids": [],
                        "assumption_claim_ids": ["hyp-campaign"],
                        "applicability_conditions": ["可记录活动触达和复购"],
                        "scene_differences": ["当前没有历史活动增量基线"],
                        "adaptations": ["设置预算封顶和降级预案"],
                        "impact_path": ["降低参与门槛", "提高权益理解", "验证复购增量"],
                        "non_copyable_factors": ["头部平台成熟大促流量"],
                        "risks": ["自然需求搬运", "异常套利"],
                        "priority": "must",
                    }
                ],
                "limitations": ["模型草案假设已有活动基线"],
            }
        }
    )


@pytest.mark.asyncio
async def test_campaign_strategy_golden_sample_covers_full_rhythm() -> None:
    plan = await build_campaign_strategy(
        _brief_without_baseline(),
        _diagnosis(),
        _evidence_bundle(),
        _model(),
    )

    phases = {phase.phase for phase in plan.rhythm}
    assert phases == {
        CampaignPhase.WARM_UP,
        CampaignPhase.LAUNCH,
        CampaignPhase.SUSTAIN,
        CampaignPhase.CLOSE,
        CampaignPhase.RETROSPECTIVE,
    }
    assert plan.goals[0].primary_goal
    assert plan.audiences[0].eligibility_rule
    assert plan.mechanisms[0].incentive_design
    assert plan.resources
    assert len(plan.contingency_plans) >= 2
    assert plan.retrospective.required_inputs
    assert plan.has_reliable_baseline is False
    assert all(
        mechanism.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
        and mechanism.is_outcome_hypothesis
        for mechanism in plan.mechanisms
    )
    assert all(
        metric.target_basis is TargetBasis.TO_BE_VALIDATED
        and metric.is_target_hypothesis
        for metric in plan.metrics
    )
    criteria_text = " ".join(
        criterion for phase in plan.rhythm for criterion in phase.acceptance_criteria
    )
    assert "提升50%" not in criteria_text
    assert "交付物" in criteria_text
