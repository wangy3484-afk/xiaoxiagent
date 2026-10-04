"""User-retention strategy module tests."""

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
from ops_agent.workflows.strategy import build_retention_strategy


def _brief_without_baseline() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user(
            "本地生活会员小程序", "本地生活会员小程序"
        ),
        current_problem=BriefField[str].from_user(
            "新用户注册后首周回访低", "新用户注册后首周回访低"
        ),
        operation_goal=BriefField[str].from_user("提升新用户留存", "提升新用户留存"),
        target_users=BriefField[str].from_user(
            "注册7天内的新会员", "注册7天内的新会员"
        ),
        business_stage=BriefField[str].from_user("增长验证期", "增长验证期"),
        budget_and_resources=BriefField[str].from_user("1名运营和1名社群兼职", "1名运营"),
        existing_channels=BriefField[list[str]].from_user(
            ["站内消息", "社群"], "站内消息、社群"
        ),
        current_baseline=BriefField[str].unknown(),
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        business_stage="增长验证期",
        target_users="注册7天内的新会员",
        goal_relationships=[
            GoalRelationship(
                business_goal="提升会员持续交易规模",
                operations_goal="提升新用户留存",
                target_behavior="新用户在首周完成一次核心价值行为并在D7回访",
                metric_ids=["metric_d7_retention"],
            )
        ],
        behavior_path=["注册", "完成核心价值行为", "接收价值反馈", "D7回访"],
        core_problem="尚未确认新用户在哪个生命周期阶段流失及关键留存行为是否成立。",
        supporting_claim_ids=["hyp-retention"],
        constraints=["1名运营和1名社群兼职"],
        priority_rationale="先验证关键行为和分群，再决定触发与召回是否扩大。",
        alternative_explanations=["首次价值不清", "触达频率不合适"],
        data_needed=["D7留存率", "关键行为完成率", "触达退订投诉率"],
    )


def _evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        claims=[
            Claim(
                claim_id="hyp-retention",
                text="完成首个核心价值行为的用户可能更容易在D7回访。",
                claim_type=ClaimType.HYPOTHESIS,
                evidence_ids=[],
                reasoning="当前缺少用户行为基线，需要分群验证。",
                verification_status=EvidenceVerificationStatus.UNVERIFIED,
            )
        ],
        evidence=[],
        links=[],
    )


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "design_retention_strategy": {
                "plan_id": "retention-plan-1",
                "has_reliable_baseline": True,
                "lifecycle_stages": [
                    {
                        "stage_id": "stage-activation",
                        "name": "价值激活",
                        "entry_condition": "新用户完成注册",
                        "exit_condition": "完成首个核心价值行为",
                        "user_goal": "理解会员能带来的即时价值",
                        "operating_goal": "推动完成关键留存行为",
                    },
                    {
                        "stage_id": "stage-early-habit",
                        "name": "早期习惯形成",
                        "entry_condition": "完成首个核心价值行为",
                        "exit_condition": "D7内再次回访或交易",
                        "user_goal": "持续获得明确价值反馈",
                        "operating_goal": "降低首周沉默和流失",
                    },
                ],
                "key_behaviors": [
                    {
                        "behavior_id": "behavior-first-value",
                        "lifecycle_stage_id": "stage-activation",
                        "name": "完成首个核心价值行为",
                        "event_definition": "注册后7天内领取并使用一次会员权益",
                        "value_signal": "用户感知会员权益能降低本地生活消费成本",
                        "relationship_basis": "provided_baseline",
                        "is_hypothesis": False,
                        "supporting_claim_ids": ["hyp-retention"],
                    }
                ],
                "segments": [
                    {
                        "segment_id": "seg-not-activated",
                        "name": "未激活新会员",
                        "lifecycle_stage_id": "stage-activation",
                        "rule": "注册后3天内未完成首个核心价值行为",
                        "included_users": "注册7天内且未使用会员权益的新用户",
                        "excluded_users": ["已退款或投诉用户"],
                        "primary_churn_risk": "未理解会员价值而首周沉默",
                    }
                ],
                "churn_signals": [
                    {
                        "signal_id": "signal-no-first-value",
                        "segment_id": "seg-not-activated",
                        "signal": "注册后3天无权益使用和社群互动",
                        "observation_window": "注册后第1-3天",
                        "likely_causes": ["权益理解不足", "入口不清晰"],
                        "data_needed": ["权益曝光", "权益点击", "权益使用"],
                    }
                ],
                "trigger_plans": [
                    {
                        "trigger_id": "trigger-value-feedback",
                        "segment_id": "seg-not-activated",
                        "linked_signal_id": "signal-no-first-value",
                        "trigger_timing": "注册后第2天仍未使用权益时",
                        "channel": "站内消息和社群提醒",
                        "message": "突出本周最容易使用的一项会员权益",
                        "value_feedback": "使用后展示节省金额或服务完成反馈",
                        "frequency_control": "7天内最多2次触达，投诉或退订立即停止",
                        "guardrail_metric_ids": ["metric_contact_optout"],
                    }
                ],
                "recall_plans": [
                    {
                        "recall_id": "recall-first-value",
                        "segment_id": "seg-not-activated",
                        "linked_signal_id": "signal-no-first-value",
                        "recovery_value": "帮助用户第一次获得会员价值",
                        "offer_or_content": "权益使用教程和低门槛权益提醒",
                        "contact_path": ["站内消息", "社群答疑"],
                        "stop_conditions": ["用户完成权益使用", "用户退订或投诉"],
                        "success_metric_id": "metric_d7_retention",
                    }
                ],
                "cohort_metrics": [
                    {
                        "metric_id": "metric_d7_retention",
                        "name": "新会员D7分群留存率",
                        "segment_id": "seg-not-activated",
                        "cohort_entry_event": "用户完成注册",
                        "retention_event": "D7内再次访问小程序或完成交易",
                        "observation_window": "注册后第7天",
                        "formula": "D7内完成留存事件用户数 / 该分群注册用户数",
                        "data_source": "用户行为埋点",
                        "decision_rule": "D7留存率提升15%则扩大",
                        "target_basis": "provided_baseline",
                        "is_target_hypothesis": False,
                    }
                ],
                "segment_validation_plans": [
                    {
                        "validation_id": "validation-not-activated",
                        "segment_id": "seg-not-activated",
                        "hypothesis": "未激活新会员完成首个价值行为后更可能D7回访",
                        "method": "按是否完成首个核心价值行为分组观察D7留存。",
                        "primary_metric_id": "metric_d7_retention",
                        "sample_or_duration": "至少观察一个完整7天窗口",
                        "success_criteria": ["D7留存率提升15%"],
                        "expected_outcome_basis": "provided_baseline",
                        "is_success_target_hypothesis": False,
                    }
                ],
                "strategy_options": [
                    {
                        "strategy_id": "strategy-first-value-retention",
                        "scene": "retention",
                        "title": "首个价值行为激活与D7回访验证",
                        "target_segment": "注册7天内的新会员",
                        "strategy_logic": "先验证关键行为与D7回访关系，再扩大触达。",
                        "evidence_ids": [],
                        "assumption_claim_ids": ["hyp-retention"],
                        "applicability_conditions": ["可以记录注册和权益使用事件"],
                        "scene_differences": ["当前缺少成熟留存基线"],
                        "adaptations": ["仅对一个新会员分群做最小验证"],
                        "impact_path": ["完成价值行为", "获得价值反馈", "提升D7回访可能性"],
                        "non_copyable_factors": ["头部平台成熟会员数据资产"],
                        "risks": ["过度触达导致退订投诉"],
                        "priority": "must",
                    }
                ],
                "limitations": ["模型草案假设已有留存基线"],
            }
        }
    )


@pytest.mark.asyncio
async def test_retention_strategy_golden_sample_has_complete_validation() -> None:
    plan = await build_retention_strategy(
        _brief_without_baseline(),
        _diagnosis(),
        _evidence_bundle(),
        _model(),
    )

    assert len(plan.lifecycle_stages) >= 2
    assert plan.key_behaviors[0].event_definition
    assert plan.segments[0].rule
    assert plan.churn_signals[0].data_needed
    assert plan.trigger_plans[0].frequency_control
    assert plan.recall_plans[0].contact_path
    metric = plan.cohort_metrics[0]
    assert metric.cohort_entry_event
    assert metric.retention_event
    assert metric.observation_window
    assert metric.formula
    assert plan.segment_validation_plans
    assert plan.has_reliable_baseline is False
    assert all(
        behavior.relationship_basis is TargetBasis.TO_BE_VALIDATED
        and behavior.is_hypothesis
        for behavior in plan.key_behaviors
    )
    assert all(
        metric.target_basis is TargetBasis.TO_BE_VALIDATED
        and metric.is_target_hypothesis
        for metric in plan.cohort_metrics
    )
    assert all(
        validation.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
        and validation.is_success_target_hypothesis
        for validation in plan.segment_validation_plans
    )
    criteria_text = " ".join(
        criterion
        for validation in plan.segment_validation_plans
        for criterion in validation.success_criteria
    )
    assert "提升15%" not in criteria_text
    assert "基线记录" in criteria_text
