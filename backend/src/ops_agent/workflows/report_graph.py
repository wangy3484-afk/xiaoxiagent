"""Complete, checkpointable LangGraph for one operations-report job."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from time import perf_counter
from typing import Any, NotRequired, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from ops_agent.config import Settings
from ops_agent.domain.intake import OperationsBrief, OperationsScene, SceneClassification
from ops_agent.domain.quality import (
    QualityRouteDecision,
    QualityRouteStatus,
    RevisionTarget,
)
from ops_agent.domain.report import (
    ActionPlan,
    Diagnosis,
    MeasurementPlan,
    OperationsReport,
    ResourceBudgetRiskSummary,
    StrategyOption,
)
from ops_agent.domain.research import (
    CaseMechanism,
    EvidenceBundle,
    EvidenceCoverageResult,
)
from ops_agent.observability import log_event
from ops_agent.providers.wiring import ProviderSet
from ops_agent.workflows.confirmation import freeze_confirmed_brief_baseline
from ops_agent.workflows.delivery import finalize_report_delivery
from ops_agent.workflows.diagnosis import build_diagnosis
from ops_agent.workflows.quality import (
    build_professional_quality_review,
    check_operations_report,
    route_quality_issues,
)
from ops_agent.workflows.reporting import build_operations_report
from ops_agent.workflows.research import (
    assess_collected_sources,
    build_case_mechanisms,
    build_research_plan,
    explain_named_company_substitutions,
    review_evidence_coverage,
    run_research_collection,
)
from ops_agent.workflows.strategy import (
    adapt_case_mechanisms_to_strategies,
    build_acquisition_strategy,
    build_action_plan,
    build_campaign_strategy,
    build_content_strategy,
    build_measurement_plan,
    build_resource_budget_risk_summary,
    build_retention_strategy,
)


class ReportWorkflowState(TypedDict):
    job_id: str
    brief: dict[str, Any]
    classification: dict[str, Any]
    completed_nodes: list[str]
    revision_round: int
    research_plan: NotRequired[dict[str, Any]]
    collected_sources: NotRequired[dict[str, Any]]
    evidence_assessments: NotRequired[list[dict[str, Any]]]
    case_mechanisms: NotRequired[list[dict[str, Any]]]
    evidence_bundle: NotRequired[dict[str, Any]]
    evidence_coverage: NotRequired[dict[str, Any]]
    named_company_substitutions: NotRequired[list[str]]
    diagnosis: NotRequired[dict[str, Any]]
    strategies: NotRequired[list[dict[str, Any]]]
    action_plan: NotRequired[dict[str, Any]]
    measurement_plan: NotRequired[dict[str, Any]]
    resource_summary: NotRequired[dict[str, Any]]
    report: NotRequired[dict[str, Any]]
    deterministic_quality: NotRequired[dict[str, Any]]
    professional_review: NotRequired[dict[str, Any]]
    route_decision: NotRequired[dict[str, Any]]
    revision_history: NotRequired[list[list[str]]]
    finalized_report: NotRequired[dict[str, Any]]
    node_counts: NotRequired[dict[str, int]]


StageHandler = Callable[
    [ReportWorkflowState],
    Awaitable[dict[str, object]] | dict[str, object],
]


@dataclass(frozen=True)
class ReportWorkflowNodes:
    load_context: StageHandler
    research: StageHandler
    diagnosis: StageHandler
    strategy: StageHandler
    planning: StageHandler
    assembly: StageHandler
    quality: StageHandler
    finalize: StageHandler


def instrument_report_nodes(nodes: ReportWorkflowNodes) -> ReportWorkflowNodes:
    """Log bounded node lifecycle metadata without serializing graph state."""

    def observed(name: str, handler: StageHandler) -> StageHandler:
        async def run(state: ReportWorkflowState) -> dict[str, object]:
            started = perf_counter()
            log_event(
                "graph_node_started",
                node=name,
                revision_round=state.get("revision_round", 0),
            )
            try:
                candidate = handler(state)
                result = await candidate if isawaitable(candidate) else candidate
            except Exception as exc:
                log_event(
                    "graph_node_failed",
                    node=name,
                    duration_ms=max(0, round((perf_counter() - started) * 1_000)),
                    error_type=type(exc).__name__,
                )
                raise
            log_event(
                "graph_node_completed",
                node=name,
                duration_ms=max(0, round((perf_counter() - started) * 1_000)),
                revision_round=state.get("revision_round", 0),
            )
            return result

        return run

    return ReportWorkflowNodes(
        load_context=observed("load_context", nodes.load_context),
        research=observed("research", nodes.research),
        diagnosis=observed("diagnosis", nodes.diagnosis),
        strategy=observed("strategy", nodes.strategy),
        planning=observed("planning", nodes.planning),
        assembly=observed("assembly", nodes.assembly),
        quality=observed("quality", nodes.quality),
        finalize=observed("finalize", nodes.finalize),
    )


def build_report_workflow_graph(
    nodes: ReportWorkflowNodes,
    *,
    checkpointer: Any,
) -> Any:
    """Compile the complete report pipeline with targeted quality-revision loops."""
    builder = StateGraph(ReportWorkflowState)
    for name in (
        "load_context",
        "research",
        "diagnosis",
        "strategy",
        "planning",
        "assembly",
        "quality",
        "finalize",
    ):
        builder.add_node(name, cast(Any, getattr(nodes, name)))
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "research")
    builder.add_edge("research", "diagnosis")
    builder.add_edge("diagnosis", "strategy")
    builder.add_edge("strategy", "planning")
    builder.add_edge("planning", "assembly")
    builder.add_edge("assembly", "quality")
    builder.add_conditional_edges(
        "quality",
        _quality_route,
        {
            "research": "research",
            "diagnosis": "diagnosis",
            "strategy": "strategy",
            "planning": "planning",
            "assembly": "assembly",
            "finalize": "finalize",
        },
    )
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def build_production_report_nodes(
    providers: ProviderSet,
    settings: Settings,
) -> ReportWorkflowNodes:
    """Bind real provider-backed domain stages to the durable graph."""

    async def load_context(state: ReportWorkflowState) -> dict[str, object]:
        _baseline(state)
        return _completed(state, "load_context")

    async def research(state: ReportWorkflowState) -> dict[str, object]:
        baseline = _baseline(state)
        plan = await build_research_plan(
            baseline.brief,
            baseline.classification,
            providers.model,
            settings=settings,
        )
        collected = await run_research_collection(
            plan,
            providers.search,
            providers.fetcher,
            providers.extractor,
            settings=settings,
        )
        assessments = assess_collected_sources(collected.sources, baseline.brief)
        extracted = await build_case_mechanisms(
            collected.sources,
            assessments,
            baseline.brief,
            baseline.classification,
            providers.model,
        )
        coverage = review_evidence_coverage(extracted.evidence_bundle)
        substitutions = explain_named_company_substitutions(
            plan, extracted.case_mechanisms
        )
        return _completed(
            state,
            "research",
            research_plan=plan.model_dump(mode="json"),
            collected_sources=collected.model_dump(mode="json"),
            evidence_assessments=[item.model_dump(mode="json") for item in assessments],
            case_mechanisms=[
                item.model_dump(mode="json") for item in extracted.case_mechanisms
            ],
            evidence_bundle=extracted.evidence_bundle.model_dump(mode="json"),
            evidence_coverage=coverage.model_dump(mode="json"),
            named_company_substitutions=substitutions,
        )

    async def diagnosis(state: ReportWorkflowState) -> dict[str, object]:
        baseline = _baseline(state)
        result = await build_diagnosis(
            baseline.brief,
            baseline.classification,
            EvidenceBundle.model_validate(state["evidence_bundle"]),
            providers.model,
            evidence_coverage=EvidenceCoverageResult.model_validate(
                state["evidence_coverage"]
            ),
        )
        return _completed(state, "diagnosis", diagnosis=result.model_dump(mode="json"))

    async def strategy(state: ReportWorkflowState) -> dict[str, object]:
        baseline = _baseline(state)
        diagnosis_value = Diagnosis.model_validate(state["diagnosis"])
        evidence = EvidenceBundle.model_validate(state["evidence_bundle"])
        scene = baseline.classification.primary_scene
        if scene is OperationsScene.ACQUISITION:
            candidates = (
                await build_acquisition_strategy(
                    baseline.brief, diagnosis_value, evidence, providers.model
                )
            ).strategy_options
        elif scene is OperationsScene.RETENTION:
            candidates = (
                await build_retention_strategy(
                    baseline.brief, diagnosis_value, evidence, providers.model
                )
            ).strategy_options
        elif scene is OperationsScene.CAMPAIGN:
            candidates = (
                await build_campaign_strategy(
                    baseline.brief, diagnosis_value, evidence, providers.model
                )
            ).strategy_options
        else:
            candidates = (
                await build_content_strategy(
                    baseline.brief, diagnosis_value, evidence, providers.model
                )
            ).strategy_options
        mechanisms = [
            CaseMechanism.model_validate(item) for item in state["case_mechanisms"]
        ]
        strategies = adapt_case_mechanisms_to_strategies(
            candidates,
            mechanisms,
            baseline.brief,
        )
        return _completed(
            state,
            "strategy",
            strategies=[item.model_dump(mode="json") for item in strategies],
        )

    async def planning(state: ReportWorkflowState) -> dict[str, object]:
        baseline = _baseline(state)
        strategies = [StrategyOption.model_validate(item) for item in state["strategies"]]
        action_plan = await build_action_plan(
            baseline.brief,
            strategies,
            providers.model,
        )
        measurement = await build_measurement_plan(
            baseline.brief,
            strategies,
            action_plan,
            providers.model,
        )
        resources = await build_resource_budget_risk_summary(
            baseline.brief,
            strategies,
            action_plan,
            measurement,
            providers.model,
        )
        return _completed(
            state,
            "planning",
            action_plan=action_plan.model_dump(mode="json"),
            measurement_plan=measurement.model_dump(mode="json"),
            resource_summary=resources.model_dump(mode="json"),
        )

    async def assembly(state: ReportWorkflowState) -> dict[str, object]:
        baseline = _baseline(state)
        report = await build_operations_report(
            report_id=state["job_id"],
            confirmed_baseline=baseline,
            scene_classification=baseline.classification,
            diagnosis=Diagnosis.model_validate(state["diagnosis"]),
            evidence_bundle=EvidenceBundle.model_validate(state["evidence_bundle"]),
            case_mechanisms=[
                CaseMechanism.model_validate(item) for item in state["case_mechanisms"]
            ],
            strategies=[
                StrategyOption.model_validate(item) for item in state["strategies"]
            ],
            action_plan=ActionPlan.model_validate(state["action_plan"]),
            measurement_plan=MeasurementPlan.model_validate(state["measurement_plan"]),
            resource_budget_risk_summary=ResourceBudgetRiskSummary.model_validate(
                state["resource_summary"]
            ),
            model=providers.model,
        )
        if substitutions := state.get("named_company_substitutions", []):
            report = report.model_copy(
                update={
                    "limitations": list(
                        dict.fromkeys([*report.limitations, *substitutions])
                    )
                }
            )
        return _completed(state, "assembly", report=report.model_dump(mode="json"))

    async def quality(state: ReportWorkflowState) -> dict[str, object]:
        report = OperationsReport.model_validate(state["report"])
        deterministic = check_operations_report(report)
        professional = await build_professional_quality_review(
            report,
            deterministic,
            providers.model,
        )
        routed = route_quality_issues(
            {
                "revision_round": state.get("revision_round", 0),
                "deterministic_quality": deterministic,
                "professional_review": professional,
                "revision_history": [
                    [RevisionTarget(target) for target in round_targets]
                    for round_targets in state.get("revision_history", [])
                ],
            }
        )
        decision = routed["route_decision"]
        history = routed.get("revision_history", [])
        return _completed(
            state,
            "quality",
            deterministic_quality=deterministic.model_dump(mode="json"),
            professional_review=professional.model_dump(mode="json"),
            route_decision=decision.model_dump(mode="json"),
            revision_round=decision.revision_round,
            revision_history=[
                [target.value for target in round_targets] for round_targets in history
            ],
        )

    async def finalize(state: ReportWorkflowState) -> dict[str, object]:
        report = finalize_report_delivery(
            OperationsReport.model_validate(state["report"]),
            EvidenceCoverageResult.model_validate(state["evidence_coverage"]),
            QualityRouteDecision.model_validate(state["route_decision"]),
        )
        return _completed(
            state,
            "finalize",
            finalized_report=report.model_dump(mode="json"),
        )

    return ReportWorkflowNodes(
        load_context=load_context,
        research=research,
        diagnosis=diagnosis,
        strategy=strategy,
        planning=planning,
        assembly=assembly,
        quality=quality,
        finalize=finalize,
    )


def initial_report_workflow_state(
    *,
    job_id: str,
    brief: OperationsBrief,
    classification: SceneClassification,
) -> ReportWorkflowState:
    return {
        "job_id": job_id,
        "brief": brief.model_dump(mode="json"),
        "classification": classification.model_dump(mode="json"),
        "completed_nodes": [],
        "revision_round": 0,
    }


def _baseline(state: ReportWorkflowState) -> Any:
    return freeze_confirmed_brief_baseline(
        OperationsBrief.model_validate(state["brief"]),
        SceneClassification.model_validate(state["classification"]),
    )


def _completed(
    state: ReportWorkflowState,
    node: str,
    **updates: object,
) -> dict[str, object]:
    return {
        **updates,
        "completed_nodes": [*state.get("completed_nodes", []), node],
    }


def _quality_route(state: ReportWorkflowState) -> str:
    decision = QualityRouteDecision.model_validate(state["route_decision"])
    if decision.status is not QualityRouteStatus.REVISE:
        return "finalize"
    priority = {
        RevisionTarget.RESEARCH: 0,
        RevisionTarget.DIAGNOSIS: 1,
        RevisionTarget.STRATEGY: 2,
        RevisionTarget.PLAN: 3,
        RevisionTarget.ASSEMBLY: 4,
    }
    earliest = min(decision.targets, key=priority.__getitem__)
    return {
        RevisionTarget.RESEARCH: "research",
        RevisionTarget.DIAGNOSIS: "diagnosis",
        RevisionTarget.STRATEGY: "strategy",
        RevisionTarget.PLAN: "planning",
        RevisionTarget.ASSEMBLY: "assembly",
    }[earliest]
