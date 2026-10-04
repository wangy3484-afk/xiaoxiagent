"""Deterministic assembly of the structured operations report."""

import json
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

from ops_agent.domain.intake import SceneClassification
from ops_agent.domain.report import (
    ActionPlan,
    Diagnosis,
    MeasurementPlan,
    OperationsReport,
    ReportDeliveryStatus,
    ReportNarrative,
    ResourceBudgetItem,
    ResourceBudgetRiskSummary,
    StrategyOption,
)
from ops_agent.domain.research import CaseMechanism, Claim, ClaimType, EvidenceBundle
from ops_agent.providers.contracts import ModelMessage, ModelProvider, ModelRequest
from ops_agent.workflows.confirmation import ConfirmedBriefBaseline


class ReportAssemblyState(TypedDict):
    report_id: str
    confirmed_baseline: ConfirmedBriefBaseline
    scene_classification: SceneClassification
    diagnosis: Diagnosis
    evidence_bundle: EvidenceBundle
    case_mechanisms: list[CaseMechanism]
    strategies: list[StrategyOption]
    action_plan: ActionPlan
    measurement_plan: MeasurementPlan
    resource_budget_risk_summary: ResourceBudgetRiskSummary
    generated_at: NotRequired[datetime]
    report: NotRequired[OperationsReport | None]


async def assemble_operations_report(
    state: ReportAssemblyState,
    model: ModelProvider,
) -> ReportAssemblyState:
    """LangGraph-compatible node that assembles every report chapter."""
    report = await build_operations_report(
        report_id=state["report_id"],
        confirmed_baseline=state["confirmed_baseline"],
        scene_classification=state["scene_classification"],
        diagnosis=state["diagnosis"],
        evidence_bundle=state["evidence_bundle"],
        case_mechanisms=state["case_mechanisms"],
        strategies=state["strategies"],
        action_plan=state["action_plan"],
        measurement_plan=state["measurement_plan"],
        resource_budget_risk_summary=state["resource_budget_risk_summary"],
        model=model,
        generated_at=state.get("generated_at"),
    )
    return {**state, "report": report}


async def build_operations_report(
    *,
    report_id: str,
    confirmed_baseline: ConfirmedBriefBaseline,
    scene_classification: SceneClassification,
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
    case_mechanisms: list[CaseMechanism],
    strategies: list[StrategyOption],
    action_plan: ActionPlan,
    measurement_plan: MeasurementPlan,
    resource_budget_risk_summary: ResourceBudgetRiskSummary,
    model: ModelProvider,
    generated_at: datetime | None = None,
) -> OperationsReport:
    """Generate narrative-only fields, then assemble upstream artifacts unchanged."""
    narrative = await _build_report_narrative(
        confirmed_baseline=confirmed_baseline,
        scene_classification=scene_classification,
        diagnosis=diagnosis,
        evidence_bundle=evidence_bundle,
        case_mechanisms=case_mechanisms,
        strategies=strategies,
        action_plan=action_plan,
        measurement_plan=measurement_plan,
        resource_budget_risk_summary=resource_budget_risk_summary,
        model=model,
    )
    key_claims = _merge_claims(
        evidence_bundle.claims,
        narrative.supplemental_claims,
    )
    assumptions = [
        claim for claim in key_claims if claim.claim_type is ClaimType.HYPOTHESIS
    ]
    resources_and_budget = [
        ResourceBudgetItem(
            item=f"[{requirement.category.value}] {requirement.item}",
            estimate=requirement.estimate,
            estimation_basis=requirement.estimation_basis,
            needs_confirmation=requirement.needs_confirmation,
        )
        for requirement in resource_budget_risk_summary.requirements
    ]
    limitations = _unique(
        [
            *narrative.limitations,
            *resource_budget_risk_summary.assumptions,
            *resource_budget_risk_summary.trade_offs,
            *resource_budget_risk_summary.excluded_scope,
        ]
    )
    return OperationsReport(
        report_id=report_id,
        title=narrative.title,
        generated_at=generated_at or datetime.now(UTC),
        delivery_status=ReportDeliveryStatus.DIRECTIONAL_DRAFT,
        executive_summary=narrative.executive_summary,
        brief=confirmed_baseline.brief,
        scene_classification=scene_classification,
        diagnosis=diagnosis,
        audience_analysis=narrative.audience_analysis,
        case_mechanisms=case_mechanisms,
        key_claims=key_claims,
        strategies=strategies,
        actions=action_plan.actions,
        metrics=measurement_plan.metrics,
        experiments=measurement_plan.experiments,
        resources_and_budget=resources_and_budget,
        risks=resource_budget_risk_summary.risks,
        assumptions=assumptions,
        limitations=limitations,
        evidence_appendix=evidence_bundle.evidence,
        decision_support_notice=narrative.decision_support_notice,
    )


async def _build_report_narrative(
    *,
    confirmed_baseline: ConfirmedBriefBaseline,
    scene_classification: SceneClassification,
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
    case_mechanisms: list[CaseMechanism],
    strategies: list[StrategyOption],
    action_plan: ActionPlan,
    measurement_plan: MeasurementPlan,
    resource_budget_risk_summary: ResourceBudgetRiskSummary,
    model: ModelProvider,
) -> ReportNarrative:
    response = await model.generate_structured(
        ModelRequest(
            purpose="assemble_operations_report",
            messages=(
                ModelMessage(role="system", content=_REPORT_ASSEMBLY_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief": confirmed_baseline.brief.model_dump(
                                mode="json"
                            ),
                            "scene_classification": scene_classification.model_dump(
                                mode="json"
                            ),
                            "diagnosis": diagnosis.model_dump(mode="json"),
                            "claims": [
                                claim.model_dump(mode="json")
                                for claim in evidence_bundle.claims
                            ],
                            "case_mechanisms": [
                                case.model_dump(mode="json")
                                for case in case_mechanisms
                            ],
                            "strategies": [
                                strategy.model_dump(mode="json")
                                for strategy in strategies
                            ],
                            "action_plan": action_plan.model_dump(mode="json"),
                            "measurement_plan": measurement_plan.model_dump(mode="json"),
                            "resource_budget_risk_summary": (
                                resource_budget_risk_summary.model_dump(mode="json")
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ),
            max_output_tokens=5_000,
            temperature=0,
        ),
        ReportNarrative,
    )
    return response.output


def _merge_claims(primary: list[Claim], supplemental: list[Claim]) -> list[Claim]:
    merged: dict[str, Claim] = {}
    for claim in [*primary, *supplemental]:
        existing = merged.get(claim.claim_id)
        if existing is not None and existing != claim:
            raise ValueError("report claims cannot reuse an ID with different content")
        merged[claim.claim_id] = claim
    return list(merged.values())


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


_REPORT_ASSEMBLY_SYSTEM_PROMPT = "\n".join(
    (
        "你是专业运营报告组装模块，只输出结构化 ReportNarrative。",
        "只生成标题、执行摘要、用户分析、限制说明、决策支持声明和补充主张；不得改写上游结构化章节。",
        "外部事实只能来自输入中的已核验证据，补充主张不得新增 fact 类型。",
        "补充主张必须分别标记 inference、recommendation 和 hypothesis，并说明推理或验证依据。",
        "执行摘要必须说明核心问题、优先策略、首阶段动作、验证指标、资源取舍和主要风险。",
        "报告仅用于运营决策支持，不得承诺效果或允许自动执行外部投放。",
    )
)
