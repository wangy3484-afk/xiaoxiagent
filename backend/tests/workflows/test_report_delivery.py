"""Formal, directional, and failure delivery-status tests."""

import pytest
from ops_agent.domain.intake import BriefField
from ops_agent.domain.quality import QualityRouteDecision, QualityRouteStatus
from ops_agent.domain.report import ReportDeliveryStatus
from ops_agent.domain.research import EvidenceCoverageResult, EvidenceCoverageStatus
from ops_agent.workflows.delivery import finalize_report_delivery

from .test_deterministic_quality import _valid_report
from .test_report_assembly import _evidence_bundle


def _coverage(status: EvidenceCoverageStatus) -> EvidenceCoverageResult:
    bundle, _, _ = _evidence_bundle()
    return EvidenceCoverageResult(
        status=status,
        evidence_bundle=bundle,
        independent_source_count=(3 if status is EvidenceCoverageStatus.SUFFICIENT else 1),
        has_high_credibility_source=True,
        insufficiencies=([] if status is EvidenceCoverageStatus.SUFFICIENT else ["独立来源不足"]),
        disclosure=(
            "证据覆盖满足正式结论要求。"
            if status is EvidenceCoverageStatus.SUFFICIENT
            else "目前只有一个可核验来源，需要补充独立来源。"
        ),
    )


def _passed_route() -> QualityRouteDecision:
    return QualityRouteDecision(
        status=QualityRouteStatus.PASSED,
        revision_round=1,
        rationale="两类质量审查均无阻断项。",
    )


@pytest.mark.asyncio
async def test_only_sufficient_evidence_and_passed_quality_becomes_formal() -> None:
    report = await _valid_report()

    finalized = finalize_report_delivery(
        report,
        _coverage(EvidenceCoverageStatus.SUFFICIENT),
        _passed_route(),
    )

    assert finalized.delivery_status is ReportDeliveryStatus.FORMAL


@pytest.mark.asyncio
async def test_insufficient_evidence_cannot_become_formal() -> None:
    report = await _valid_report()

    finalized = finalize_report_delivery(
        report,
        _coverage(EvidenceCoverageStatus.INSUFFICIENT),
        _passed_route(),
    )

    assert finalized.delivery_status is ReportDeliveryStatus.DIRECTIONAL_DRAFT
    assert any("公开证据覆盖不足" in item for item in finalized.limitations)


@pytest.mark.asyncio
async def test_missing_key_input_becomes_failure_explanation() -> None:
    report = await _valid_report()
    brief = report.brief.model_copy(
        update={"operation_goal": BriefField[str].unknown()}
    )
    report = report.model_copy(update={"brief": brief})

    finalized = finalize_report_delivery(
        report,
        _coverage(EvidenceCoverageStatus.SUFFICIENT),
        _passed_route(),
    )

    assert finalized.delivery_status is ReportDeliveryStatus.FAILURE_EXPLANATION
    assert any("核心运营目标" in item for item in finalized.limitations)
