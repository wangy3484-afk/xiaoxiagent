"""Structured operations-report assembly tests."""

from datetime import UTC, date, datetime

import pytest
from ops_agent.domain.intake import (
    BriefField,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.domain.report import (
    ActionPlan,
    Diagnosis,
    GoalRelationship,
    MeasurementPlan,
    ReportDeliveryStatus,
    ResourceBudgetRiskSummary,
    StrategyOption,
    StrategyPriority,
)
from ops_agent.domain.research import (
    CaseMechanism,
    Claim,
    ClaimEvidenceLink,
    ClaimType,
    CredibilityAssessment,
    CredibilityLevel,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceSupportType,
    EvidenceVerificationStatus,
    PublicationDateStatus,
    SourceType,
)
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.confirmation import ConfirmedBriefBaseline
from ops_agent.workflows.reporting import build_operations_report


def _brief_and_classification() -> tuple[OperationsBrief, SceneClassification]:
    brief = OperationsBrief(
        business_context=BriefField[str].from_user("社区团购小程序", "社区团购小程序"),
        current_problem=BriefField[str].from_user("新客首单转化低", "新客首单转化低"),
        operation_goal=BriefField[str].from_user("提高首单转化", "提高首单转化"),
        target_users=BriefField[str].from_user("新注册家庭用户", "新注册家庭用户"),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
    )
    classification = SceneClassification(
        primary_scene=OperationsScene.ACQUISITION,
        rationale=["核心目标是提高新客首单转化"],
        confidence=0.9,
    )
    return brief, classification


def _evidence_bundle() -> tuple[EvidenceBundle, Claim, EvidenceRecord]:
    fact = Claim(
        claim_id="fact-1",
        text="官方材料确认使用社群承接新客",
        claim_type=ClaimType.FACT,
        evidence_ids=["ev-1"],
        reasoning="官方材料直接陈述运营动作",
        verification_status=EvidenceVerificationStatus.VERIFIED,
    )
    evidence = EvidenceRecord.model_validate(
        {
            "evidence_id": "ev-1",
            "title": "官方运营说明",
            "publisher": "示例公司",
            "source_type": SourceType.OFFICIAL_PRIMARY,
            "url": "https://example.com/operations",
            "publication_date": date(2025, 1, 1),
            "publication_date_status": PublicationDateStatus.KNOWN,
            "accessed_at": datetime(2026, 9, 30, tzinfo=UTC),
            "supporting_excerpt": "官方材料确认使用社群承接新客。",
            "context_summary": "仅证明实施了运营动作，不单独证明转化效果。",
            "supported_claim_ids": [fact.claim_id],
            "credibility": CredibilityAssessment(
                level=CredibilityLevel.HIGH,
                rationale="企业官方材料可以直接核验运营动作。",
                independence_notes="效果仍需通过当前场景实验验证。",
            ),
            "verification_status": EvidenceVerificationStatus.VERIFIED,
            "source_accessible": True,
            "content_hash": "a" * 64,
        }
    )
    bundle = EvidenceBundle(
        claims=[fact],
        evidence=[evidence],
        links=[
            ClaimEvidenceLink(
                claim_id=fact.claim_id,
                evidence_id=evidence.evidence_id,
                support_type=EvidenceSupportType.DIRECT,
                rationale="原始材料直接支持该动作事实",
            )
        ],
    )
    return bundle, fact, evidence


def _strategy() -> StrategyOption:
    return StrategyOption(
        strategy_id="strategy-1",
        scene=OperationsScene.ACQUISITION,
        title="社群首单承接实验",
        target_segment="新注册家庭用户",
        strategy_logic="通过小范围社群实验验证信任背书与首单承接关系。",
        evidence_ids=["ev-1"],
        assumption_claim_ids=["hyp-1"],
        applicability_conditions=["社群触达和首单行为可归因"],
        scene_differences=["当前团队资源少于案例企业"],
        adaptations=["先在2个社区开展最小实验"],
        impact_path=["建立信任", "降低首单决策门槛"],
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
                    "strategy_id": "strategy-1",
                    "phase": "0-30天",
                    "goal": "验证社群首单承接",
                    "target_audience": "新注册家庭用户",
                    "action": "在2个社区上线社群首单承接实验",
                    "touchpoint": "微信群与小程序落地页",
                    "owner_role": "增长运营",
                    "prerequisites": ["渠道可归因"],
                    "resources": ["2名运营"],
                    "deliverable": "实验复盘表",
                    "timeline": "第1-30天",
                    "acceptance_criteria": ["完成实验与数据记录"],
                }
            ],
        }
    )


def _measurement_plan() -> MeasurementPlan:
    common = {
        "definition": "符合条件用户的统一指标计算口径",
        "formula": "符合条件用户数 / 总用户数",
        "data_source": "小程序埋点",
        "observation_period": "实验后7天",
        "decision_rule": "达到判断标准且风险不恶化时继续",
    }
    return MeasurementPlan.model_validate(
        {
            "plan_id": "measurement-plan-1",
            "metrics": [
                {
                    "metric_id": "metric-outcome",
                    "name": "首单转化率",
                    "metric_type": "outcome",
                    **common,
                },
                {
                    "metric_id": "metric-process",
                    "name": "社群触达率",
                    "metric_type": "process",
                    **common,
                },
                {
                    "metric_id": "metric-risk",
                    "name": "退款投诉率",
                    "metric_type": "risk",
                    **common,
                },
            ],
            "experiments": [
                {
                    "experiment_id": "experiment-1",
                    "hypothesis_claim_id": "hyp-1",
                    "linked_strategy_ids": ["strategy-1"],
                    "target_segment": "新注册家庭用户",
                    "design": "选择2个社区开展小范围对照实验。",
                    "comparison": "社群实验组与自然流量组",
                    "duration": "2周",
                    "primary_metric_ids": ["metric-outcome", "metric-risk"],
                    "success_criteria": ["完成有效基线记录"],
                    "sample_size_method": "覆盖完整周期内符合条件的用户",
                    "stop_conditions": ["退款投诉率恶化"],
                }
            ],
        }
    )


def _resource_summary() -> ResourceBudgetRiskSummary:
    categories = [
        ("personnel", "增长运营", "must"),
        ("channel", "2个社区社群", "must"),
        ("tool", "埋点与看板", "should"),
        ("content_capacity", "落地页与社群素材", "should"),
        ("time", "2周实验周期", "must"),
        ("budget", "实验预算", "could"),
    ]
    requirements = [
        {
            "requirement_id": f"resource-{category}",
            "category": category,
            "item": item,
            "quantity_or_capacity": "满足最小实验需要",
            "estimate": (
                "渠道投入 + 工具费用 + 内容费用 + 人力时间成本"
                if category == "budget"
                else "按最小实验范围配置"
            ),
            "estimate_expression": "formula",
            "estimation_basis": "按资源数量、单位成本和执行周期测算",
            "needs_confirmation": category == "budget",
            "priority": priority,
            "linked_strategy_ids": ["strategy-1"],
        }
        for category, item, priority in categories
    ]
    return ResourceBudgetRiskSummary.model_validate(
        {
            "summary_id": "resource-summary-1",
            "has_confirmed_budget_ceiling": False,
            "budget_ceiling": None,
            "requirements": requirements,
            "priority_order": [item["requirement_id"] for item in requirements],
            "trade_offs": ["优先保障最小实验，预算确认前不进行付费放量"],
            "excluded_scope": ["暂不同时开展多个付费渠道"],
            "assumptions": ["预算与外部采购价格待确认"],
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
    )


def _narrative_response() -> dict[str, object]:
    return {
        "title": "社区团购新客首单运营方案",
        "executive_summary": (
            "本方案优先在2个社区验证社群信任背书与首单承接关系，"
            "以首单转化率和退款投诉率决定是否扩大，并在预算确认前控制付费范围。"
        ),
        "audience_analysis": {
            "segments": ["已注册未首单", "已浏览未下单"],
            "priority_segment": "注册7天内未完成首单的家庭用户",
            "needs_and_barriers": ["缺少信任背书", "首次决策成本高"],
            "behavioral_signals": ["注册后浏览但未提交订单"],
        },
        "supplemental_claims": [
            {
                "claim_id": "inference-1",
                "text": "当前首单问题可能同时受信任和承接路径影响",
                "claim_type": "inference",
                "evidence_ids": ["ev-1"],
                "reasoning": "案例动作与当前行为路径共同支持该解释，但不能证明因果",
                "verification_status": "unverified",
            },
            {
                "claim_id": "recommendation-1",
                "text": "建议先执行2个社区的最小实验",
                "claim_type": "recommendation",
                "evidence_ids": [],
                "reasoning": "该范围符合当前资源约束并能产生可判断数据",
                "verification_status": "unverified",
            },
            {
                "claim_id": "hyp-1",
                "text": "社群信任背书可能改善新客首单承接",
                "claim_type": "hypothesis",
                "evidence_ids": [],
                "reasoning": "需要通过对照实验验证",
                "verification_status": "unverified",
            },
        ],
        "limitations": ["当前缺少可靠首单转化基线"],
        "decision_support_notice": (
            "本报告仅用于运营决策支持，目标、资源和效果假设必须结合实际数据验证，"
            "最终执行由业务负责人决定。"
        ),
    }


@pytest.mark.asyncio
async def test_assembly_contains_all_sections_and_four_claim_labels() -> None:
    brief, classification = _brief_and_classification()
    evidence_bundle, fact, evidence = _evidence_bundle()
    measurement_plan = _measurement_plan()
    diagnosis = Diagnosis(
        business_stage="冷启动阶段",
        target_users="新注册家庭用户",
        goal_relationships=[
            GoalRelationship(
                business_goal="提高有效订单规模",
                operations_goal="提高新客首单转化",
                target_behavior="完成首次下单",
                metric_ids=["metric-outcome"],
            )
        ],
        behavior_path=["注册", "浏览", "提交订单"],
        core_problem="尚未区分信任不足与承接路径摩擦的影响。",
        supporting_claim_ids=[fact.claim_id, "hyp-1"],
        constraints=["预算待确认"],
        priority_rationale="先做最小实验可以低成本区分关键解释。",
        alternative_explanations=["价格竞争力不足"],
        data_needed=["首单转化基线"],
    )
    strategy = _strategy()
    action_plan = _action_plan()
    case = CaseMechanism(
        case_id="case-1",
        company="示例公司",
        goal="承接新客首单",
        audience="新注册用户",
        touchpoints=["社群"],
        mechanism="通过社群信任与提醒承接首次决策",
        execution_conditions=["社群触达可归因"],
        observed_outcomes=[fact],
        evidence_ids=[evidence.evidence_id],
        transferable_elements=["社群信任机制"],
        non_transferable_elements=["头部平台自然流量"],
    )
    model = DeterministicModelProvider(
        {"assemble_operations_report": _narrative_response()}
    )

    report = await build_operations_report(
        report_id="report-1",
        confirmed_baseline=ConfirmedBriefBaseline(
            brief=brief,
            classification=classification,
            fingerprint_sha256="f" * 64,
        ),
        scene_classification=classification,
        diagnosis=diagnosis,
        evidence_bundle=evidence_bundle,
        case_mechanisms=[case],
        strategies=[strategy],
        action_plan=action_plan,
        measurement_plan=measurement_plan,
        resource_budget_risk_summary=_resource_summary(),
        model=model,
        generated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )

    assert report.delivery_status is ReportDeliveryStatus.DIRECTIONAL_DRAFT
    assert {claim.claim_type for claim in report.key_claims} == set(ClaimType)
    assert report.brief == brief
    assert report.diagnosis == diagnosis
    assert report.case_mechanisms == [case]
    assert report.strategies == [strategy]
    assert report.actions == action_plan.actions
    assert report.metrics == measurement_plan.metrics
    assert report.experiments == measurement_plan.experiments
    assert len(report.resources_and_budget) == 6
    assert report.risks
    assert report.evidence_appendix == [evidence]
    assert report.assumptions[0].claim_id == "hyp-1"
    assert report.automated_execution_allowed is False
