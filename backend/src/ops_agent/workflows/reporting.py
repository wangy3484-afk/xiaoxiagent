"""Deterministic assembly of the structured operations report."""

import json
from datetime import UTC, datetime
from hashlib import sha256
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
from ops_agent.domain.research import (
    CaseMechanism,
    Claim,
    ClaimType,
    EvidenceBundle,
    EvidenceVerificationStatus,
)
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
    """Assemble upstream artifacts, downgrading references that cannot be verified."""
    strategies, downgraded_strategy_ids = _reconcile_strategy_evidence_references(
        strategies, evidence_bundle
    )
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
    strategies, measurement_plan, remapped_assumption_ids = (
        _remap_conflicting_assumption_ids(key_claims, strategies, measurement_plan)
    )
    key_claims, inferred_assumption_ids = _ensure_referenced_hypotheses(
        key_claims, strategies, measurement_plan
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
            *(
                ["部分策略或实验的假设主张由作用路径补全，具体表述仍需人工核实。"]
                if inferred_assumption_ids
                else []
            ),
            *(
                ["部分假设编号与其他主张冲突，报告已为待验证假设重新编号并保留原主张。"]
                if remapped_assumption_ids
                else []
            ),
            *(
                ["部分策略引用的证据未出现在已核验附录中；无效引用已移除，相关作用路径降级为待验证假设。"]
                if downgraded_strategy_ids
                else []
            ),
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
                            "required_hypothesis_claim_ids": sorted(
                                {
                                    *(
                                        claim_id
                                        for strategy in strategies
                                        for claim_id in strategy.assumption_claim_ids
                                    ),
                                    *(
                                        experiment.hypothesis_claim_id
                                        for experiment in measurement_plan.experiments
                                    ),
                                }
                            ),
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


def _reconcile_strategy_evidence_references(
    strategies: list[StrategyOption],
    evidence_bundle: EvidenceBundle,
) -> tuple[list[StrategyOption], set[str]]:
    """Never carry an unresolvable strategy citation into a delivered report."""
    known_evidence_ids = {item.evidence_id for item in evidence_bundle.evidence}
    adjusted: list[StrategyOption] = []
    downgraded_strategy_ids: set[str] = set()
    for strategy in strategies:
        supported_ids = [
            evidence_id
            for evidence_id in strategy.evidence_ids
            if evidence_id in known_evidence_ids
        ]
        if len(supported_ids) == len(strategy.evidence_ids):
            adjusted.append(strategy)
            continue
        hypothesis_id = (
            "hyp_strategy_"
            + sha256(strategy.strategy_id.encode("utf-8")).hexdigest()[:12]
        )
        adjusted.append(
            strategy.model_copy(
                update={
                    "evidence_ids": supported_ids,
                    "assumption_claim_ids": list(
                        dict.fromkeys([*strategy.assumption_claim_ids, hypothesis_id])
                    ),
                }
            )
        )
        downgraded_strategy_ids.add(strategy.strategy_id)
    return adjusted, downgraded_strategy_ids


def _remap_conflicting_assumption_ids(
    claims: list[Claim],
    strategies: list[StrategyOption],
    measurement_plan: MeasurementPlan,
) -> tuple[list[StrategyOption], MeasurementPlan, set[str]]:
    """Keep non-hypothesis claims intact when a model reuses their IDs."""
    non_hypothesis_ids = {
        claim.claim_id for claim in claims if claim.claim_type is not ClaimType.HYPOTHESIS
    }
    referenced_ids = {
        *(claim_id for strategy in strategies for claim_id in strategy.assumption_claim_ids),
        *(experiment.hypothesis_claim_id for experiment in measurement_plan.experiments),
    }
    reserved_ids = {claim.claim_id for claim in claims} | referenced_ids
    remapped: dict[str, str] = {}
    for claim_id in sorted(referenced_ids & non_hypothesis_ids):
        digest = sha256(claim_id.encode("utf-8")).hexdigest()[:12]
        candidate = f"hyp_{digest}"
        suffix = 2
        while candidate in reserved_ids:
            candidate = f"hyp_{digest}_{suffix}"
            suffix += 1
        remapped[claim_id] = candidate
        reserved_ids.add(candidate)

    if not remapped:
        return strategies, measurement_plan, set()
    adjusted_strategies = [
        strategy.model_copy(
            update={
                "assumption_claim_ids": [
                    remapped.get(claim_id, claim_id)
                    for claim_id in strategy.assumption_claim_ids
                ]
            }
        )
        for strategy in strategies
    ]
    adjusted_experiments = [
        experiment.model_copy(
            update={
                "hypothesis_claim_id": remapped.get(
                    experiment.hypothesis_claim_id, experiment.hypothesis_claim_id
                )
            }
        )
        for experiment in measurement_plan.experiments
    ]
    return (
        adjusted_strategies,
        measurement_plan.model_copy(update={"experiments": adjusted_experiments}),
        set(remapped),
    )


def _ensure_referenced_hypotheses(
    claims: list[Claim],
    strategies: list[StrategyOption],
    measurement_plan: MeasurementPlan,
) -> tuple[list[Claim], set[str]]:
    """Preserve upstream hypothesis references even when narrative IDs drift."""
    by_id = {claim.claim_id: claim for claim in claims}
    inferred_ids: set[str] = set()
    strategy_by_id = {strategy.strategy_id: strategy for strategy in strategies}
    source_strategy: dict[str, StrategyOption] = {}
    for strategy in strategies:
        for claim_id in strategy.assumption_claim_ids:
            source_strategy.setdefault(claim_id, strategy)
    for experiment in measurement_plan.experiments:
        for strategy_id in experiment.linked_strategy_ids:
            linked_strategy = strategy_by_id.get(strategy_id)
            if linked_strategy is not None:
                source_strategy.setdefault(experiment.hypothesis_claim_id, linked_strategy)
                break

    for claim_id, strategy in source_strategy.items():
        existing = by_id.get(claim_id)
        if existing is not None:
            if existing.claim_type is not ClaimType.HYPOTHESIS:
                raise ValueError("referenced assumption claim must be a hypothesis")
            continue
        impact_path = " → ".join(strategy.impact_path)
        claim = Claim(
            claim_id=claim_id,
            text=f"待验证：{strategy.title}的预期作用路径为{impact_path}"[:2000],
            claim_type=ClaimType.HYPOTHESIS,
            evidence_ids=[],
            reasoning="上游策略或实验引用了该待验证假设；当前场景尚无直接验证结果。",
            verification_status=EvidenceVerificationStatus.UNVERIFIED,
        )
        claims.append(claim)
        by_id[claim_id] = claim
        inferred_ids.add(claim_id)
    return claims, inferred_ids


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


_REPORT_ASSEMBLY_SYSTEM_PROMPT = "\n".join(
    (
        "你是专业运营报告组装模块，只输出结构化 ReportNarrative。",
        "只生成标题、执行摘要、用户分析、限制说明、决策支持声明和补充主张；不得改写上游结构化章节。",
        "外部事实只能来自输入中的已核验证据，补充主张不得新增 fact 类型。",
        "补充主张必须分别标记 inference、recommendation 和 hypothesis，并说明推理或验证依据。",
        "hypothesis 主张必须覆盖 required_hypothesis_claim_ids 中的每个精确编号，不得改名或遗漏。",
        "执行摘要必须说明核心问题、优先策略、首阶段动作、验证指标、资源取舍和主要风险。",
        "报告仅用于运营决策支持，不得承诺效果或允许自动执行外部投放。",
    )
)
