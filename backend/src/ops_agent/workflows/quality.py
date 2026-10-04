"""Deterministic blocking checks for structured operations reports."""

import json
import re
from collections.abc import Callable
from typing import Any, NotRequired, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from ops_agent.domain.intake import FieldStatus
from ops_agent.domain.quality import (
    DeterministicQualityIssue,
    DeterministicQualityResult,
    ProfessionalQualityReview,
    QualityRouteDecision,
    QualityRouteStatus,
    QualityRuleCode,
    QualitySeverity,
    RevisionTarget,
)
from ops_agent.domain.report import MetricType, OperationsReport, StrategyPriority
from ops_agent.domain.research import ClaimType, EvidenceVerificationStatus
from ops_agent.providers.contracts import ModelMessage, ModelProvider, ModelRequest


class DeterministicQualityState(TypedDict):
    report: OperationsReport
    deterministic_quality: NotRequired[DeterministicQualityResult | None]


class ProfessionalReviewState(TypedDict):
    report: OperationsReport
    deterministic_quality: DeterministicQualityResult
    professional_review: NotRequired[ProfessionalQualityReview | None]


class QualityRevisionState(TypedDict):
    revision_round: int
    deterministic_quality: NotRequired[DeterministicQualityResult]
    professional_review: NotRequired[ProfessionalQualityReview]
    route_decision: NotRequired[QualityRouteDecision]
    revision_history: NotRequired[list[list[RevisionTarget]]]


def run_deterministic_quality_checks(
    state: DeterministicQualityState,
) -> DeterministicQualityState:
    """LangGraph-compatible node for hard report quality gates."""
    result = check_operations_report(state["report"])
    return {**state, "deterministic_quality": result}


def check_operations_report(report: OperationsReport) -> DeterministicQualityResult:
    """Run every stable blocking rule without model judgment."""
    issues: list[DeterministicQualityIssue] = []
    checks: tuple[
        tuple[
            QualityRuleCode,
            Callable[[OperationsReport], list[DeterministicQualityIssue]],
        ],
        ...,
    ] = (
        (QualityRuleCode.SECTION_COMPLETENESS, _check_section_completeness),
        (QualityRuleCode.REFERENCE_RESOLVABILITY, _check_reference_resolvability),
        (QualityRuleCode.FACT_CITATION_COVERAGE, _check_fact_citation_coverage),
        (QualityRuleCode.ACTION_CLOSED_LOOP, _check_action_closed_loop),
        (QualityRuleCode.METRIC_DEFINITION, _check_metric_definition),
        (QualityRuleCode.RESOURCE_CONSTRAINTS, _check_resource_constraints),
        (QualityRuleCode.NO_AUTOMATED_EXECUTION, _check_no_automated_execution),
    )
    for _, check in checks:
        issues.extend(check(report))
    return DeterministicQualityResult(
        passed=not any(
            issue.severity is QualitySeverity.BLOCKING for issue in issues
        ),
        checks_run=[code for code, _ in checks],
        issues=issues,
    )


async def review_operations_report(
    state: ProfessionalReviewState,
    model: ModelProvider,
) -> ProfessionalReviewState:
    """Run an independent seven-dimension review without rewriting the report."""
    review = await build_professional_quality_review(
        state["report"],
        state["deterministic_quality"],
        model,
    )
    return {**state, "professional_review": review}


async def build_professional_quality_review(
    report: OperationsReport,
    deterministic_quality: DeterministicQualityResult,
    model: ModelProvider,
) -> ProfessionalQualityReview:
    """Ask an independent reviewer for findings and targeted revision nodes only."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="professional_quality_review",
            messages=(
                ModelMessage(role="system", content=_PROFESSIONAL_REVIEW_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "report": report.model_dump(mode="json"),
                            "deterministic_quality": deterministic_quality.model_dump(
                                mode="json"
                            ),
                            "rules": [
                                "必须逐项覆盖七个质量维度并给出结论、依据和关联对象",
                                "识别相关性冒充因果、单一案例泛化、资源冲突和虚假精确",
                                "每个问题只能指定 research、diagnosis、strategy、plan "
                                "或 assembly 返工节点",
                                "只输出审查结果，禁止改写报告正文或静默修复问题",
                            ],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ),
            max_output_tokens=5_000,
            temperature=0,
        ),
        ProfessionalQualityReview,
    )
    return response.output


def build_quality_revision_graph(
    *,
    review_node: Callable[[QualityRevisionState], dict[str, object]],
    revision_node: Callable[[QualityRevisionState], dict[str, object]],
) -> Any:
    """Compile a bounded review-revision loop with targeted routing metadata."""
    builder = StateGraph(QualityRevisionState)
    builder.add_node("quality_review", cast(Any, review_node))
    builder.add_node("route_quality", route_quality_issues)
    builder.add_node("targeted_revision", cast(Any, revision_node))
    builder.add_edge(START, "quality_review")
    builder.add_edge("quality_review", "route_quality")
    builder.add_conditional_edges(
        "route_quality",
        _route_after_quality_decision,
        {"revise": "targeted_revision", "end": END},
    )
    builder.add_edge("targeted_revision", "quality_review")
    return builder.compile()


def route_quality_issues(state: QualityRevisionState) -> QualityRevisionState:
    """Route blockers to owning nodes and stop after at most two revision rounds."""
    deterministic = state.get("deterministic_quality")
    professional = state.get("professional_review")
    if deterministic is None or professional is None:
        raise ValueError("quality routing requires deterministic and professional reviews")

    issue_ids: list[str] = []
    targets: list[RevisionTarget] = []
    for issue in deterministic.issues:
        if issue.severity is not QualitySeverity.BLOCKING:
            continue
        issue_ids.append(issue.issue_id)
        targets.append(_DETERMINISTIC_REVISION_TARGETS[issue.rule_code])
    for finding in professional.findings:
        if not finding.blocking:
            continue
        issue_ids.append(finding.finding_id)
        targets.append(finding.revision_target)

    issue_ids = list(dict.fromkeys(issue_ids))
    targets = list(dict.fromkeys(targets))
    current_round = state.get("revision_round", 0)
    if not issue_ids:
        decision = QualityRouteDecision(
            status=QualityRouteStatus.PASSED,
            revision_round=current_round,
            rationale="确定性检查和专业审查均无阻断项，可以进入交付判定。",
        )
    elif current_round >= _MAX_QUALITY_REVISION_ROUNDS:
        decision = QualityRouteDecision(
            status=QualityRouteStatus.UNRESOLVED,
            revision_round=_MAX_QUALITY_REVISION_ROUNDS,
            issue_ids=issue_ids,
            rationale="两轮定向修订后仍存在阻断项，停止循环并转入受限交付判定。",
        )
    else:
        decision = QualityRouteDecision(
            status=QualityRouteStatus.REVISE,
            revision_round=current_round + 1,
            targets=targets,
            issue_ids=issue_ids,
            rationale="按问题归属返回目标节点进行定向修订，然后重新执行完整审查。",
        )
    return {
        **state,
        "revision_round": decision.revision_round,
        "route_decision": decision,
    }


def _route_after_quality_decision(state: QualityRevisionState) -> str:
    decision = state.get("route_decision")
    if decision is None:
        raise ValueError("quality route decision is missing")
    return "revise" if decision.status is QualityRouteStatus.REVISE else "end"


def _check_section_completeness(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    sections: dict[str, object] = {
        "executive_summary": report.executive_summary,
        "case_mechanisms": report.case_mechanisms,
        "key_claims": report.key_claims,
        "strategies": report.strategies,
        "actions": report.actions,
        "metrics": report.metrics,
        "experiments": report.experiments,
        "resources_and_budget": report.resources_and_budget,
        "risks": report.risks,
        "assumptions": report.assumptions,
        "limitations": report.limitations,
        "evidence_appendix": report.evidence_appendix,
        "decision_support_notice": report.decision_support_notice,
    }
    missing = [
        name
        for name, value in sections.items()
        if value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, list) and not value)
    ]
    if not missing:
        return []
    return [
        _issue(
            QualityRuleCode.SECTION_COMPLETENESS,
            "report.sections",
            f"报告缺少必填章节或章节内容为空：{', '.join(missing)}。",
            "补齐所有结构化章节后重新执行质量检查。",
            missing,
        )
    ]


def _check_reference_resolvability(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    evidence_ids = {item.evidence_id for item in report.evidence_appendix}
    claim_ids = {item.claim_id for item in report.key_claims}
    assumption_ids = {item.claim_id for item in report.assumptions}
    strategy_ids = {item.strategy_id for item in report.strategies}
    metric_ids = {item.metric_id for item in report.metrics}
    broken: list[str] = []

    for claim in report.key_claims:
        broken.extend(
            f"claim:{claim.claim_id}->evidence:{evidence_id}"
            for evidence_id in claim.evidence_ids
            if evidence_id not in evidence_ids
        )
    broken.extend(
        f"diagnosis->claim:{claim_id}"
        for claim_id in report.diagnosis.supporting_claim_ids
        if claim_id not in claim_ids
    )
    for strategy in report.strategies:
        broken.extend(
            f"strategy:{strategy.strategy_id}->evidence:{evidence_id}"
            for evidence_id in strategy.evidence_ids
            if evidence_id not in evidence_ids
        )
        broken.extend(
            f"strategy:{strategy.strategy_id}->assumption:{claim_id}"
            for claim_id in strategy.assumption_claim_ids
            if claim_id not in assumption_ids
        )
    broken.extend(
        f"action:{action.action_id}->strategy:{action.strategy_id}"
        for action in report.actions
        if action.strategy_id not in strategy_ids
    )
    for experiment in report.experiments:
        broken.extend(
            f"experiment:{experiment.experiment_id}->strategy:{strategy_id}"
            for strategy_id in experiment.linked_strategy_ids
            if strategy_id not in strategy_ids
        )
        broken.extend(
            f"experiment:{experiment.experiment_id}->metric:{metric_id}"
            for metric_id in experiment.primary_metric_ids
            if metric_id not in metric_ids
        )
        if experiment.hypothesis_claim_id not in assumption_ids:
            broken.append(
                f"experiment:{experiment.experiment_id}"
                f"->hypothesis:{experiment.hypothesis_claim_id}"
            )
    for risk_index, risk in enumerate(report.risks):
        broken.extend(
            f"risk:{risk_index}->metric:{metric_id}"
            for metric_id in risk.monitoring_metric_ids
            if metric_id not in metric_ids
        )
    if not broken:
        return []
    return [
        _issue(
            QualityRuleCode.REFERENCE_RESOLVABILITY,
            "report.references",
            "报告存在无法解析的结构化引用。",
            "修复引用目标或移除无效引用，确保主张、证据、策略、行动、实验和指标形成闭环。",
            broken,
        )
    ]


def _check_fact_citation_coverage(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    facts = [claim for claim in report.key_claims if claim.claim_type is ClaimType.FACT]
    if not facts:
        return [
            _issue(
                QualityRuleCode.FACT_CITATION_COVERAGE,
                "key_claims",
                "报告没有可核验的事实主张，无法形成正式证据结论。",
                "补充已核验事实及其证据，或将报告限制为方向性草案。",
            )
        ]

    evidence_by_id = {
        evidence.evidence_id: evidence for evidence in report.evidence_appendix
    }
    unsupported: list[str] = []
    for fact in facts:
        supporting = [
            evidence_by_id.get(evidence_id) for evidence_id in fact.evidence_ids
        ]
        if not supporting or any(evidence is None for evidence in supporting):
            unsupported.append(fact.claim_id)
            continue
        if not any(
            evidence is not None
            and evidence.verification_status is EvidenceVerificationStatus.VERIFIED
            and evidence.source_accessible
            and fact.claim_id in evidence.supported_claim_ids
            for evidence in supporting
        ):
            unsupported.append(fact.claim_id)
    if not unsupported:
        return []
    coverage = (len(facts) - len(unsupported)) / len(facts)
    return [
        _issue(
            QualityRuleCode.FACT_CITATION_COVERAGE,
            "key_claims",
            f"事实主张有效引用率为 {coverage:.0%}，低于正式报告要求的 100%。",
            "为每项事实补充可访问、已核验且明确支持该主张的证据，或降级主张类型。",
            unsupported,
        )
    ]


def _check_action_closed_loop(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    incomplete: list[str] = []
    for action in report.actions:
        required_strings = (
            action.goal,
            action.target_audience,
            action.action,
            action.touchpoint,
            action.owner_role,
            action.deliverable,
            action.timeline,
        )
        if any(not value.strip() for value in required_strings) or any(
            not values
            for values in (
                action.prerequisites,
                action.resources,
                action.acceptance_criteria,
            )
        ):
            incomplete.append(action.action_id)

    actionable_priorities = {StrategyPriority.MUST, StrategyPriority.SHOULD}
    action_strategy_ids = {action.strategy_id for action in report.actions}
    incomplete.extend(
        f"strategy:{strategy.strategy_id}"
        for strategy in report.strategies
        if strategy.priority in actionable_priorities
        and strategy.strategy_id not in action_strategy_ids
    )
    if not incomplete:
        return []
    return [
        _issue(
            QualityRuleCode.ACTION_CLOSED_LOOP,
            "actions",
            "核心策略缺少完整行动闭环或行动字段不完整。",
            "补齐目标、人群、动作、触点、负责人、前置条件、资源、交付物、时间和验收方式。",
            incomplete,
        )
    ]


def _check_metric_definition(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    incomplete = [
        metric.metric_id
        for metric in report.metrics
        if any(
            not value.strip()
            for value in (
                metric.definition,
                metric.formula,
                metric.data_source,
                metric.observation_period,
                metric.decision_rule,
            )
        )
    ]
    missing_types = set(MetricType) - {metric.metric_type for metric in report.metrics}
    related_ids = [*incomplete, *[f"metric_type:{item.value}" for item in missing_types]]
    if not related_ids:
        return []
    return [
        _issue(
            QualityRuleCode.METRIC_DEFINITION,
            "metrics",
            "指标口径不完整，或未同时覆盖结果、过程和风险指标。",
            "补齐指标定义、公式、数据来源、观测周期和判断规则，并覆盖三类指标。",
            related_ids,
        )
    ]


def _check_resource_constraints(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    violations: list[str] = []
    if not report.resources_and_budget:
        violations.append("resources_and_budget")
    if any(not action.resources for action in report.actions):
        violations.extend(
            action.action_id for action in report.actions if not action.resources
        )

    budget_field = report.brief.budget_and_resources
    if budget_field.status is not FieldStatus.CONFIRMED:
        violations.extend(
            item.item
            for item in report.resources_and_budget
            if _PRECISE_MONEY_PATTERN.search(item.estimate)
            and not item.needs_confirmation
        )

    deferred_ids = {
        strategy.strategy_id
        for strategy in report.strategies
        if strategy.priority is StrategyPriority.WONT_NOW
    }
    violations.extend(
        action.action_id
        for action in report.actions
        if action.strategy_id in deferred_ids
    )
    if not violations:
        return []
    return [
        _issue(
            QualityRuleCode.RESOURCE_CONSTRAINTS,
            "resources_and_budget",
            "报告存在未披露的资源冲突、未知预算精确值或仍执行本期放弃策略。",
            "将成本改为区间、公式或待确认项，并删除超出资源范围的行动或明确新增资源。",
            violations,
        )
    ]


def _check_no_automated_execution(
    report: OperationsReport,
) -> list[DeterministicQualityIssue]:
    if (
        report.automated_execution_allowed is False
        and "决策支持" in report.decision_support_notice
    ):
        return []
    return [
        _issue(
            QualityRuleCode.NO_AUTOMATED_EXECUTION,
            "decision_support_notice",
            "报告未明确禁止自动执行，或缺少运营决策支持边界说明。",
            "设置 automated_execution_allowed=false，并声明最终执行由业务负责人决定。",
        )
    ]


def _issue(
    rule_code: QualityRuleCode,
    location: str,
    message: str,
    remediation: str,
    related_ids: list[str] | None = None,
) -> DeterministicQualityIssue:
    return DeterministicQualityIssue(
        issue_id=f"{rule_code.value}:{location}",
        rule_code=rule_code,
        severity=QualitySeverity.BLOCKING,
        message=message,
        location=location,
        remediation=remediation,
        related_ids=related_ids or [],
    )


_PRECISE_MONEY_PATTERN = re.compile(r"(?:¥|￥|人民币)?\s*\d+(?:\.\d+)?\s*(?:元|万元|万)")

_MAX_QUALITY_REVISION_ROUNDS = 2

_DETERMINISTIC_REVISION_TARGETS = {
    QualityRuleCode.SECTION_COMPLETENESS: RevisionTarget.ASSEMBLY,
    QualityRuleCode.REFERENCE_RESOLVABILITY: RevisionTarget.ASSEMBLY,
    QualityRuleCode.FACT_CITATION_COVERAGE: RevisionTarget.RESEARCH,
    QualityRuleCode.ACTION_CLOSED_LOOP: RevisionTarget.PLAN,
    QualityRuleCode.METRIC_DEFINITION: RevisionTarget.PLAN,
    QualityRuleCode.RESOURCE_CONSTRAINTS: RevisionTarget.PLAN,
    QualityRuleCode.NO_AUTOMATED_EXECUTION: RevisionTarget.ASSEMBLY,
}

_PROFESSIONAL_REVIEW_SYSTEM_PROMPT = "\n".join(
    (
        "你是独立的专业运营报告审查者，只输出结构化 ProfessionalQualityReview。",
        "必须评估需求完整性、证据质量、场景适配、策略逻辑、执行可行性、指标可衡量性和风险覆盖七个维度。",
        "重点识别相关性冒充因果、单一案例泛化、资源与目标冲突、缺少依据的精确数字和效果承诺。",
        "每个发现必须说明依据、是否阻断、关联对象、修复建议和唯一目标返工节点。",
        "你不得直接改写报告，也不得把评论同时作为修订后的正文返回。",
    )
)
