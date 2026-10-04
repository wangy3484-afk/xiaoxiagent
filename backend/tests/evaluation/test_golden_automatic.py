"""Golden acceptance gates reject unsafe status and structural regressions."""

import pytest
from ops_agent.domain.intake import OperationsScene
from ops_agent.domain.report import ReportDeliveryStatus
from ops_agent.evaluation import (
    GoldenScenario,
    evaluate_golden_report,
    load_default_golden_scenarios,
)
from ops_agent.workflows.research import review_evidence_coverage
from workflows.test_deterministic_quality import _valid_report
from workflows.test_report_assembly import _evidence_bundle


def _scenario(scenario_id: str) -> GoldenScenario:
    return next(
        scenario
        for scenario in load_default_golden_scenarios().scenarios
        if scenario.scenario_id == scenario_id
    )


@pytest.mark.asyncio
async def test_draft_golden_case_passes_hard_rules_without_becoming_formal() -> None:
    report = await _valid_report()
    coverage = review_evidence_coverage(_evidence_bundle()[0])

    result = evaluate_golden_report(
        _scenario("golden-acquisition-02"), report, coverage
    )

    assert report.delivery_status is ReportDeliveryStatus.DIRECTIONAL_DRAFT
    assert result.passed, result.failures


@pytest.mark.asyncio
async def test_golden_gate_rejects_wrong_delivery_status_and_open_action_loop() -> None:
    report = await _valid_report()
    coverage = review_evidence_coverage(_evidence_bundle()[0])
    altered = report.model_copy(
        update={
            "delivery_status": ReportDeliveryStatus.FORMAL,
            "actions": [
                report.actions[0].model_copy(update={"resources": []}),
                *report.actions[1:],
            ],
        }
    )

    result = evaluate_golden_report(
        _scenario("golden-acquisition-02"), altered, coverage
    )

    assert result.passed is False
    assert "draft_scenario_marked_formal" in result.failures
    assert "draft_delivery_status_mismatch" in result.failures
    assert "quality:action_closed_loop" in result.failures


@pytest.mark.asyncio
async def test_formal_golden_case_rejects_insufficient_evidence_and_metric_gap() -> None:
    report = await _valid_report()
    coverage = review_evidence_coverage(_evidence_bundle()[0])
    altered = report.model_copy(
        update={
            "metrics": [
                report.metrics[0].model_copy(update={"formula": ""}),
                *report.metrics[1:],
            ]
        }
    )

    result = evaluate_golden_report(
        _scenario("golden-acquisition-01"), altered, coverage
    )

    assert result.passed is False
    assert "formal_report_not_delivered" in result.failures
    assert "formal_report_has_insufficient_evidence" in result.failures
    assert "quality:metric_definition" in result.failures


@pytest.mark.asyncio
async def test_golden_gate_requires_exact_failure_state_and_primary_strategy() -> None:
    report = await _valid_report()
    coverage = review_evidence_coverage(_evidence_bundle()[0])
    altered = report.model_copy(
        update={
            "scene_classification": report.scene_classification.model_copy(
                update={"primary_scene": OperationsScene.CAMPAIGN}
            ),
        }
    )

    result = evaluate_golden_report(
        _scenario("golden-campaign-03"), altered, coverage
    )

    assert result.passed is False
    assert "failure_explanation_not_delivered" in result.failures
    assert "primary_scene_strategy_missing" in result.failures
