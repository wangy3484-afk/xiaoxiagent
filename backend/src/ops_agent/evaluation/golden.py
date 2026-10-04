"""Machine-checkable acceptance gates for generated golden-scenario reports."""

from dataclasses import dataclass

from ops_agent.domain.intake import FieldStatus
from ops_agent.domain.report import OperationsReport, ReportDeliveryStatus
from ops_agent.domain.research import EvidenceCoverageResult, EvidenceCoverageStatus
from ops_agent.evaluation.schema import GoldenScenario, RequiredReportSection
from ops_agent.workflows.quality import check_operations_report


@dataclass(frozen=True, slots=True)
class GoldenEvaluationResult:
    scenario_id: str
    report_id: str
    passed: bool
    failures: tuple[str, ...]


def evaluate_golden_report(
    scenario: GoldenScenario,
    report: OperationsReport,
    coverage: EvidenceCoverageResult,
) -> GoldenEvaluationResult:
    """Check sections, evidence, citations, execution, metrics, and delivery status."""
    failures: list[str] = []
    sections = {
        RequiredReportSection.EXECUTIVE_SUMMARY: report.executive_summary,
        RequiredReportSection.OPERATIONS_BRIEF: report.brief,
        RequiredReportSection.DIAGNOSIS: report.diagnosis,
        RequiredReportSection.GOALS_AND_METRICS: report.metrics,
        RequiredReportSection.AUDIENCE_ANALYSIS: report.audience_analysis,
        RequiredReportSection.CASE_EVIDENCE: report.case_mechanisms,
        RequiredReportSection.STRATEGY_DESIGN: report.strategies,
        RequiredReportSection.ACTION_PLAN: report.actions,
        RequiredReportSection.RESOURCE_AND_BUDGET: report.resources_and_budget,
        RequiredReportSection.EXPERIMENT_PLAN: report.experiments,
        RequiredReportSection.RISK_PLAN: report.risks,
        RequiredReportSection.EVIDENCE_APPENDIX: report.evidence_appendix,
    }
    for section in scenario.required_sections:
        if not sections[section]:
            failures.append(f"missing_section:{section.value}")

    if report.scene_classification.primary_scene is not scenario.scene:
        failures.append("scene_mismatch")
    if not any(strategy.scene is scenario.scene for strategy in report.strategies):
        failures.append("primary_scene_strategy_missing")
    if report.brief.current_baseline.status is not scenario.baseline_status:
        failures.append(
            "invented_baseline"
            if scenario.baseline_status is FieldStatus.UNKNOWN
            else "confirmed_baseline_missing"
        )

    quality = check_operations_report(report)
    failures.extend(f"quality:{issue.rule_code.value}" for issue in quality.issues)
    if set(item.evidence_id for item in report.evidence_appendix) != set(
        item.evidence_id for item in coverage.evidence_bundle.evidence
    ):
        failures.append("evidence_bundle_mismatch")

    if report.delivery_status is not scenario.expected_delivery_status:
        failures.append(
            {
                ReportDeliveryStatus.FORMAL: "formal_report_not_delivered",
                ReportDeliveryStatus.DIRECTIONAL_DRAFT: "draft_delivery_status_mismatch",
                ReportDeliveryStatus.FAILURE_EXPLANATION: "failure_explanation_not_delivered",
            }[scenario.expected_delivery_status]
        )

    if scenario.expected_delivery_status is ReportDeliveryStatus.FORMAL:
        if coverage.status is not EvidenceCoverageStatus.SUFFICIENT:
            failures.append("formal_report_has_insufficient_evidence")
    else:
        if report.delivery_status is ReportDeliveryStatus.FORMAL:
            failures.append("draft_scenario_marked_formal")
        if not report.limitations:
            failures.append("draft_missing_limitations")

    return GoldenEvaluationResult(
        scenario_id=scenario.scenario_id,
        report_id=report.report_id,
        passed=not failures,
        failures=tuple(dict.fromkeys(failures)),
    )
