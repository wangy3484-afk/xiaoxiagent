"""Final report delivery status and limitation disclosure."""

from typing import NotRequired, TypedDict

from ops_agent.domain.intake import FieldStatus
from ops_agent.domain.quality import QualityRouteDecision, QualityRouteStatus
from ops_agent.domain.report import OperationsReport, ReportDeliveryStatus
from ops_agent.domain.research import EvidenceCoverageResult, EvidenceCoverageStatus


class ReportDeliveryState(TypedDict):
    report: OperationsReport
    evidence_coverage: EvidenceCoverageResult
    quality_route: QualityRouteDecision
    finalized_report: NotRequired[OperationsReport | None]


def finalize_report_delivery_state(
    state: ReportDeliveryState,
) -> ReportDeliveryState:
    """LangGraph-compatible node for the final delivery classification."""
    finalized = finalize_report_delivery(
        state["report"],
        state["evidence_coverage"],
        state["quality_route"],
    )
    return {**state, "finalized_report": finalized}


def finalize_report_delivery(
    report: OperationsReport,
    evidence_coverage: EvidenceCoverageResult,
    quality_route: QualityRouteDecision,
) -> OperationsReport:
    """Apply formal, directional-draft, or failure-explanation status."""
    missing_inputs = _missing_delivery_inputs(report)
    limitations = list(report.limitations)

    if missing_inputs:
        status = ReportDeliveryStatus.FAILURE_EXPLANATION
        limitations.append(
            "关键输入缺失，无法形成可负责的策略结论："
            + "、".join(missing_inputs)
            + "。请补充并重新生成报告。"
        )
    elif (
        evidence_coverage.status is EvidenceCoverageStatus.SUFFICIENT
        and quality_route.status is QualityRouteStatus.PASSED
    ):
        status = ReportDeliveryStatus.FORMAL
    else:
        status = ReportDeliveryStatus.DIRECTIONAL_DRAFT
        if evidence_coverage.status is not EvidenceCoverageStatus.SUFFICIENT:
            limitations.append(
                "公开证据覆盖不足或存在冲突，相关结论仅作为待验证方向："
                + evidence_coverage.disclosure
            )
        if quality_route.status is not QualityRouteStatus.PASSED:
            limitations.append(
                "质量阻断项尚未全部解决，受影响问题："
                + "、".join(quality_route.issue_ids)
                + "。"
            )

    return report.model_copy(
        update={
            "delivery_status": status,
            "limitations": _unique(limitations),
        }
    )


def _missing_delivery_inputs(report: OperationsReport) -> list[str]:
    required = {
        "核心运营目标": report.brief.operation_goal,
        "目标用户": report.brief.target_users,
    }
    return [
        label
        for label, field in required.items()
        if field.status is not FieldStatus.CONFIRMED
    ]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
