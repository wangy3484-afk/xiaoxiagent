"""Failure and passing fixtures for every deterministic quality gate."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from ops_agent.domain.quality import QualityRuleCode, QualitySeverity
from ops_agent.domain.report import (
    Diagnosis,
    GoalRelationship,
    OperationsReport,
    ResourceBudgetItem,
)
from ops_agent.domain.research import CaseMechanism
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.confirmation import ConfirmedBriefBaseline
from ops_agent.workflows.quality import check_operations_report
from ops_agent.workflows.reporting import build_operations_report

from .test_report_assembly import (
    _action_plan,
    _brief_and_classification,
    _evidence_bundle,
    _measurement_plan,
    _narrative_response,
    _resource_summary,
    _strategy,
)


async def _valid_report() -> OperationsReport:
    brief, classification = _brief_and_classification()
    evidence_bundle, fact, evidence = _evidence_bundle()
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
    return await build_operations_report(
        report_id="report-quality",
        confirmed_baseline=ConfirmedBriefBaseline(
            brief=brief,
            classification=classification,
            fingerprint_sha256="e" * 64,
        ),
        scene_classification=classification,
        diagnosis=diagnosis,
        evidence_bundle=evidence_bundle,
        case_mechanisms=[case],
        strategies=[_strategy()],
        action_plan=_action_plan(),
        measurement_plan=_measurement_plan(),
        resource_budget_risk_summary=_resource_summary(),
        model=DeterministicModelProvider(
            {"assemble_operations_report": _narrative_response()}
        ),
        generated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def _missing_section(report: OperationsReport) -> OperationsReport:
    return report.model_copy(update={"limitations": []})


def _broken_reference(report: OperationsReport) -> OperationsReport:
    diagnosis = report.diagnosis.model_copy(
        update={"supporting_claim_ids": ["missing-claim"]}
    )
    return report.model_copy(update={"diagnosis": diagnosis})


def _uncited_fact(report: OperationsReport) -> OperationsReport:
    evidence = report.evidence_appendix[0].model_copy(
        update={"supported_claim_ids": []}
    )
    return report.model_copy(update={"evidence_appendix": [evidence]})


def _open_action_loop(report: OperationsReport) -> OperationsReport:
    action = report.actions[0].model_copy(update={"resources": []})
    return report.model_copy(update={"actions": [action]})


def _undefined_metric(report: OperationsReport) -> OperationsReport:
    metric = report.metrics[0].model_copy(update={"formula": ""})
    return report.model_copy(update={"metrics": [metric, *report.metrics[1:]]})


def _unconfirmed_precise_budget(report: OperationsReport) -> OperationsReport:
    precise_budget = ResourceBudgetItem(
        item="[budget] 实验预算",
        estimate="50000元",
        estimation_basis="无用户确认依据",
        needs_confirmation=False,
    )
    return report.model_copy(
        update={"resources_and_budget": [
            *report.resources_and_budget[:-1],
            precise_budget,
        ]}
    )


def _allows_automated_execution(report: OperationsReport) -> OperationsReport:
    return report.model_copy(update={"automated_execution_allowed": True})


@pytest.mark.asyncio
async def test_valid_report_passes_every_deterministic_rule() -> None:
    result = check_operations_report(await _valid_report())

    assert result.passed is True
    assert set(result.checks_run) == set(QualityRuleCode)
    assert result.issues == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutator", "expected_rule"),
    [
        (_missing_section, QualityRuleCode.SECTION_COMPLETENESS),
        (_broken_reference, QualityRuleCode.REFERENCE_RESOLVABILITY),
        (_uncited_fact, QualityRuleCode.FACT_CITATION_COVERAGE),
        (_open_action_loop, QualityRuleCode.ACTION_CLOSED_LOOP),
        (_undefined_metric, QualityRuleCode.METRIC_DEFINITION),
        (_unconfirmed_precise_budget, QualityRuleCode.RESOURCE_CONSTRAINTS),
        (_allows_automated_execution, QualityRuleCode.NO_AUTOMATED_EXECUTION),
    ],
)
async def test_each_deterministic_rule_has_a_blocking_failure_fixture(
    mutator: Callable[[OperationsReport], OperationsReport],
    expected_rule: QualityRuleCode,
) -> None:
    result = check_operations_report(mutator(await _valid_report()))

    assert result.passed is False
    assert any(
        issue.rule_code is expected_rule
        and issue.severity is QualitySeverity.BLOCKING
        for issue in result.issues
    )
