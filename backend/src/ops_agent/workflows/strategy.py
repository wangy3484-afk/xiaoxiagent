"""Scene-specific strategy modules."""

import json
import re
from typing import NotRequired, TypedDict

from ops_agent.domain.intake import FieldStatus, OperationsBrief
from ops_agent.domain.report import (
    AcquisitionGrowthPlan,
    ActionPlan,
    CampaignMechanismDesign,
    CampaignMetricPlan,
    CampaignOperationsPlan,
    CampaignRhythmPhase,
    ChannelExperimentPlan,
    ContentMetricPlan,
    ContentOperationsPlan,
    ContentProductionCadence,
    ContentValidationPlan,
    CustomerAcquisitionCostAssumption,
    Diagnosis,
    EstimateExpression,
    ExperimentPlan,
    KeyRetentionBehavior,
    MeasurementPlan,
    MetricDefinition,
    MetricTarget,
    ResourceBudgetRiskSummary,
    ResourceCategory,
    ResourceRequirement,
    RetentionCohortMetric,
    RetentionStrategyPlan,
    SegmentValidationPlan,
    StrategyOption,
    StrategyPriority,
    TargetBasis,
)
from ops_agent.domain.research import CaseMechanism, EvidenceBundle
from ops_agent.providers.contracts import ModelMessage, ModelProvider, ModelRequest
from ops_agent.workflows.confirmation import ConfirmedBriefBaseline


class AcquisitionStrategyState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    diagnosis: Diagnosis
    evidence_bundle: EvidenceBundle
    acquisition_plan: NotRequired[AcquisitionGrowthPlan | None]


class RetentionStrategyState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    diagnosis: Diagnosis
    evidence_bundle: EvidenceBundle
    retention_plan: NotRequired[RetentionStrategyPlan | None]


class CampaignStrategyState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    diagnosis: Diagnosis
    evidence_bundle: EvidenceBundle
    campaign_plan: NotRequired[CampaignOperationsPlan | None]


class ContentStrategyState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    diagnosis: Diagnosis
    evidence_bundle: EvidenceBundle
    content_plan: NotRequired[ContentOperationsPlan | None]


class CaseMechanismMigrationState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    case_mechanisms: list[CaseMechanism]
    candidate_strategies: list[StrategyOption]
    adapted_strategies: NotRequired[list[StrategyOption]]


class ActionPlanningState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    strategies: list[StrategyOption]
    action_plan: NotRequired[ActionPlan | None]


class MeasurementPlanningState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    strategies: list[StrategyOption]
    action_plan: ActionPlan
    measurement_plan: NotRequired[MeasurementPlan | None]


class ResourceBudgetPlanningState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    strategies: list[StrategyOption]
    action_plan: ActionPlan
    measurement_plan: MeasurementPlan
    resource_budget_risk_summary: NotRequired[ResourceBudgetRiskSummary | None]


async def generate_action_plan(
    state: ActionPlanningState,
    model: ModelProvider,
) -> ActionPlanningState:
    """LangGraph-compatible node for phased action-plan generation."""
    baseline = state["confirmed_baseline"]
    plan = await build_action_plan(baseline.brief, state["strategies"], model)
    return {**state, "action_plan": plan}


async def build_action_plan(
    brief: OperationsBrief,
    strategies: list[StrategyOption],
    model: ModelProvider,
) -> ActionPlan:
    """Generate a phased action plan from selected strategies."""
    phases = _action_plan_phase_policy(brief)
    response = await model.generate_structured(
        ModelRequest(
            purpose="build_action_plan",
            messages=(
                ModelMessage(role="system", content=_ACTION_PLAN_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "strategies": [
                                strategy.model_dump(mode="json")
                                for strategy in strategies
                            ],
                            "phase_policy": phases,
                            "rules": [
                                "每项行动必须包含目标、人群、行动、触点、负责人角色、前置条件、资源、交付物、时间和验收方式",
                                "用户未指定周期时必须使用 0-30天、31-60天、61-90天 三阶段",
                                "早期阶段优先验证关键假设，不能直接进入不可逆放大",
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
        ActionPlan,
    )
    return _reconcile_action_plan(response.output, brief=brief)


async def generate_measurement_plan(
    state: MeasurementPlanningState,
    model: ModelProvider,
) -> MeasurementPlanningState:
    """LangGraph-compatible node for metrics and experiment planning."""
    baseline = state["confirmed_baseline"]
    plan = await build_measurement_plan(
        baseline.brief,
        state["strategies"],
        state["action_plan"],
        model,
    )
    return {**state, "measurement_plan": plan}


async def build_measurement_plan(
    brief: OperationsBrief,
    strategies: list[StrategyOption],
    action_plan: ActionPlan,
    model: ModelProvider,
) -> MeasurementPlan:
    """Generate outcome/process/risk metrics and validation experiments."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="build_measurement_plan",
            messages=(
                ModelMessage(role="system", content=_MEASUREMENT_PLAN_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "strategies": [
                                strategy.model_dump(mode="json")
                                for strategy in strategies
                            ],
                            "action_plan": action_plan.model_dump(mode="json"),
                            "has_reliable_baseline": _has_reliable_baseline(brief),
                            "rules": [
                                "必须同时包含结果指标、过程指标和风险指标",
                                "每个指标必须包含口径、公式、数据来源、观测周期和判断规则",
                                "没有可靠基线时，目标值只能是待验证假设，并优先设计建立基线的实验",
                                "实验必须绑定策略、假设、主要指标、样本或周期、成功标准和停止条件",
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
        MeasurementPlan,
    )
    return _reconcile_measurement_plan(response.output, brief=brief)


async def generate_resource_budget_risk_summary(
    state: ResourceBudgetPlanningState,
    model: ModelProvider,
) -> ResourceBudgetPlanningState:
    """LangGraph-compatible node for resource, budget, and risk consolidation."""
    baseline = state["confirmed_baseline"]
    summary = await build_resource_budget_risk_summary(
        baseline.brief,
        state["strategies"],
        state["action_plan"],
        state["measurement_plan"],
        model,
    )
    return {**state, "resource_budget_risk_summary": summary}


async def build_resource_budget_risk_summary(
    brief: OperationsBrief,
    strategies: list[StrategyOption],
    action_plan: ActionPlan,
    measurement_plan: MeasurementPlan,
    model: ModelProvider,
) -> ResourceBudgetRiskSummary:
    """Consolidate resource needs, budget assumptions, trade-offs, and risks."""
    budget_ceiling = _confirmed_budget_ceiling(brief)
    response = await model.generate_structured(
        ModelRequest(
            purpose="build_resource_budget_risk_summary",
            messages=(
                ModelMessage(role="system", content=_RESOURCE_BUDGET_RISK_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "strategies": [
                                strategy.model_dump(mode="json")
                                for strategy in strategies
                            ],
                            "action_plan": action_plan.model_dump(mode="json"),
                            "measurement_plan": measurement_plan.model_dump(mode="json"),
                            "confirmed_budget_ceiling": budget_ceiling,
                            "rules": [
                                "必须覆盖人员、渠道、工具、内容产能、时间和预算六类资源",
                                "预算有上限时必须按优先级排序，并列出不能同时执行的范围和取舍",
                                "预算未知时只能使用区间、计算公式或待确认项，不得生成精确金额",
                                "风险必须包含触发条件、缓解动作、负责人和监控指标",
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
        ResourceBudgetRiskSummary,
    )
    return _reconcile_resource_budget_risk_summary(
        response.output,
        brief=brief,
        strategies=strategies,
        measurement_plan=measurement_plan,
    )


def migrate_case_mechanisms(
    state: CaseMechanismMigrationState,
) -> CaseMechanismMigrationState:
    """LangGraph-compatible node for adapting public case mechanisms to strategies."""
    baseline = state["confirmed_baseline"]
    strategies = adapt_case_mechanisms_to_strategies(
        state["candidate_strategies"],
        state["case_mechanisms"],
        baseline.brief,
    )
    return {**state, "adapted_strategies": strategies}


def adapt_case_mechanisms_to_strategies(
    strategies: list[StrategyOption],
    case_mechanisms: list[CaseMechanism],
    brief: OperationsBrief,
) -> list[StrategyOption]:
    """Attach evidence and scenario-fit notes from case mechanisms to strategies."""
    if not case_mechanisms:
        return strategies
    return [
        _adapt_strategy_with_case(
            strategy,
            _select_case_for_strategy(strategy, case_mechanisms),
            brief,
        )
        for strategy in strategies
    ]


async def design_acquisition_strategy(
    state: AcquisitionStrategyState,
    model: ModelProvider,
) -> AcquisitionStrategyState:
    """LangGraph-compatible node for acquisition-growth strategy design."""
    baseline = state["confirmed_baseline"]
    plan = await build_acquisition_strategy(
        baseline.brief,
        state["diagnosis"],
        state["evidence_bundle"],
        model,
    )
    return {**state, "acquisition_plan": plan}


async def build_acquisition_strategy(
    brief: OperationsBrief,
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
    model: ModelProvider,
) -> AcquisitionGrowthPlan:
    """Generate and reconcile an acquisition strategy plan."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="design_acquisition_strategy",
            messages=(
                ModelMessage(role="system", content=_ACQUISITION_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "diagnosis": diagnosis.model_dump(mode="json"),
                            "claims": [
                                claim.model_dump(mode="json")
                                for claim in evidence_bundle.claims
                            ],
                            "rules": [
                                "必须覆盖目标人群、价值主张、渠道组合、触达路径、转化漏斗、CAC假设和渠道实验",
                                "没有可靠基线时，成本和效果目标必须是待验证假设",
                                "不得承诺确定获客规模、转化率提升或固定获客成本",
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
        AcquisitionGrowthPlan,
    )
    return _reconcile_acquisition_plan(response.output, brief=brief)


async def design_retention_strategy(
    state: RetentionStrategyState,
    model: ModelProvider,
) -> RetentionStrategyState:
    """LangGraph-compatible node for user-retention strategy design."""
    baseline = state["confirmed_baseline"]
    plan = await build_retention_strategy(
        baseline.brief,
        state["diagnosis"],
        state["evidence_bundle"],
        model,
    )
    return {**state, "retention_plan": plan}


async def build_retention_strategy(
    brief: OperationsBrief,
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
    model: ModelProvider,
) -> RetentionStrategyPlan:
    """Generate and reconcile a user-retention strategy plan."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="design_retention_strategy",
            messages=(
                ModelMessage(role="system", content=_RETENTION_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "diagnosis": diagnosis.model_dump(mode="json"),
                            "claims": [
                                claim.model_dump(mode="json")
                                for claim in evidence_bundle.claims
                            ],
                            "rules": [
                                "必须覆盖生命周期、关键留存行为、分层、流失信号、触发机制、召回策略和分群验证方案",
                                "留存指标必须明确起点事件、回访事件、分群、观察窗口、公式和判断规则",
                                "未验证关键行为或分群逻辑时必须标记为待验证假设",
                                "没有可靠基线时不得承诺确定留存提升、召回率或复购提升",
                            ],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ),
            max_output_tokens=8_000,
            temperature=0,
        ),
        RetentionStrategyPlan,
    )
    return _reconcile_retention_plan(response.output, brief=brief)


async def design_campaign_strategy(
    state: CampaignStrategyState,
    model: ModelProvider,
) -> CampaignStrategyState:
    """LangGraph-compatible node for campaign-operations strategy design."""
    baseline = state["confirmed_baseline"]
    plan = await build_campaign_strategy(
        baseline.brief,
        state["diagnosis"],
        state["evidence_bundle"],
        model,
    )
    return {**state, "campaign_plan": plan}


async def build_campaign_strategy(
    brief: OperationsBrief,
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
    model: ModelProvider,
) -> CampaignOperationsPlan:
    """Generate and reconcile a campaign operations plan."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="design_campaign_strategy",
            messages=(
                ModelMessage(role="system", content=_CAMPAIGN_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "diagnosis": diagnosis.model_dump(mode="json"),
                            "claims": [
                                claim.model_dump(mode="json")
                                for claim in evidence_bundle.claims
                            ],
                            "rules": [
                                "必须覆盖活动目标、目标人群、核心机制、利益设计、传播节奏、执行资源、异常预案和复盘设计",
                                "传播节奏必须包含预热、上线、持续、收尾和复盘五个阶段",
                                "权益成本、容量和作弊风险必须有上限、监控指标和降级动作",
                                "没有可靠基线时不得承诺确定增量、转化率提升或固定活动成本效率",
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
        CampaignOperationsPlan,
    )
    return _reconcile_campaign_plan(response.output, brief=brief)


async def design_content_strategy(
    state: ContentStrategyState,
    model: ModelProvider,
) -> ContentStrategyState:
    """LangGraph-compatible node for content-operations strategy design."""
    baseline = state["confirmed_baseline"]
    plan = await build_content_strategy(
        baseline.brief,
        state["diagnosis"],
        state["evidence_bundle"],
        model,
    )
    return {**state, "content_plan": plan}


async def build_content_strategy(
    brief: OperationsBrief,
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
    model: ModelProvider,
) -> ContentOperationsPlan:
    """Generate and reconcile a content operations plan."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="design_content_strategy",
            messages=(
                ModelMessage(role="system", content=_CONTENT_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "diagnosis": diagnosis.model_dump(mode="json"),
                            "claims": [
                                claim.model_dump(mode="json")
                                for claim in evidence_bundle.claims
                            ],
                            "rules": [
                                "必须覆盖内容定位、目标受众、主题矩阵、内容供给、生产节奏、分发渠道、互动机制和转化路径",
                                "每个主题必须对应明确受众问题、内容任务、供给责任和质量标准",
                                "每个分发渠道必须说明用户意图、原生形态、互动设计和回流路径",
                                "没有可靠基线时不得承诺确定触达、互动、转化或因果提升",
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
        ContentOperationsPlan,
    )
    return _reconcile_content_plan(response.output, brief=brief)


def _reconcile_acquisition_plan(
    plan: AcquisitionGrowthPlan,
    *,
    brief: OperationsBrief,
) -> AcquisitionGrowthPlan:
    has_baseline = _has_reliable_baseline(brief)
    if has_baseline:
        return plan.model_copy(update={"has_reliable_baseline": True})

    cac_assumptions = [
        _make_cac_hypothesis(assumption) for assumption in plan.cac_assumptions
    ]
    channel_experiments = [
        _make_channel_experiment_hypothesis(experiment)
        for experiment in plan.channel_experiments
    ]
    limitations = _unique(
        [
            *plan.limitations,
            "用户未提供可靠获客漏斗或成本基线，所有获客成本和效果目标均为待验证假设。",
        ]
    )
    return AcquisitionGrowthPlan(
        plan_id=plan.plan_id,
        has_reliable_baseline=False,
        target_segments=plan.target_segments,
        value_propositions=plan.value_propositions,
        channel_mix=plan.channel_mix,
        conversion_funnel=plan.conversion_funnel,
        cac_assumptions=cac_assumptions,
        channel_experiments=channel_experiments,
        strategy_options=plan.strategy_options,
        limitations=limitations,
    )


def _adapt_strategy_with_case(
    strategy: StrategyOption,
    case: CaseMechanism,
    brief: OperationsBrief,
) -> StrategyOption:
    evidence_ids = _unique([*strategy.evidence_ids, *case.evidence_ids])
    applicability_conditions = _unique(
        [
            *strategy.applicability_conditions,
            *case.execution_conditions,
        ]
    )
    scene_differences = _unique(
        [
            *strategy.scene_differences,
            f"{case.company}案例的业务目标、人群和资源条件需要与当前场景重新匹配。",
        ]
    )
    adaptations = _unique(
        [
            *strategy.adaptations,
            *[
                f"将案例中的「{element}」改造为当前资源可验证的操作。"
                for element in case.transferable_elements
            ],
        ]
    )
    impact_path = _unique(
        [
            *strategy.impact_path,
            f"借鉴{case.company}案例机制",
            "在当前场景验证后再决定是否放大",
        ]
    )
    non_copyable_factors = _unique(
        [*strategy.non_copyable_factors, *case.non_transferable_elements]
    )
    risks = _unique(
        [
            *strategy.risks,
            "公开案例只能证明机制存在或局部结果，不能直接证明当前场景必然有效。",
        ]
    )
    priority = strategy.priority

    if _has_resource_mismatch(case, brief):
        adaptations = _scaled_or_abandoned_adaptations(case, adaptations)
        applicability_conditions = _unique(
            [
                *applicability_conditions,
                "仅在小范围资源、渠道和数据口径验证通过后再扩大。",
            ]
        )
        scene_differences = _unique(
            [
                *scene_differences,
                "资源条件不匹配：头部案例依赖的品牌、流量、数据或组织能力当前不具备。",
            ]
        )
        risks = _unique(
            [
                *risks,
                "禁止直接复制完整头部玩法，否则可能超出预算、团队和渠道承载能力。",
            ]
        )
        priority = (
            StrategyPriority.WONT_NOW
            if _should_abandon_due_to_no_transferable(case)
            else StrategyPriority.SHOULD
        )

    return strategy.model_copy(
        update={
            "evidence_ids": evidence_ids,
            "applicability_conditions": applicability_conditions,
            "scene_differences": scene_differences,
            "adaptations": adaptations,
            "impact_path": impact_path,
            "non_copyable_factors": non_copyable_factors,
            "risks": risks,
            "priority": priority,
        }
    )


def _reconcile_action_plan(plan: ActionPlan, *, brief: OperationsBrief) -> ActionPlan:
    if brief.execution_period.status is FieldStatus.CONFIRMED:
        return plan
    return ActionPlan(plan_id=plan.plan_id, phases=_DEFAULT_ACTION_PHASES, actions=plan.actions)


def _reconcile_measurement_plan(
    plan: MeasurementPlan,
    *,
    brief: OperationsBrief,
) -> MeasurementPlan:
    if _has_reliable_baseline(brief):
        return plan
    return MeasurementPlan(
        plan_id=plan.plan_id,
        metrics=[_make_measurement_metric_hypothesis(metric) for metric in plan.metrics],
        experiments=[
            _make_baseline_experiment_hypothesis(experiment)
            for experiment in plan.experiments
        ],
    )


def _reconcile_resource_budget_risk_summary(
    summary: ResourceBudgetRiskSummary,
    *,
    brief: OperationsBrief,
    strategies: list[StrategyOption],
    measurement_plan: MeasurementPlan,
) -> ResourceBudgetRiskSummary:
    _validate_resource_summary_references(summary, strategies, measurement_plan)
    budget_ceiling = _confirmed_budget_ceiling(brief)
    requirements = list(summary.requirements)
    assumptions = list(summary.assumptions)
    excluded_scope = list(summary.excluded_scope)

    if budget_ceiling is None:
        requirements = [
            _make_unknown_budget_requirement(requirement)
            for requirement in requirements
        ]
        assumptions = _unique(
            [
                *assumptions,
                "用户未提供可用预算上限，所有金额与付费资源规模均需确认后才能承诺。",
            ]
        )
        excluded_scope = _unique(
            [
                *excluded_scope,
                "预算确认前不承诺付费渠道规模、采购金额或可同时推进的策略数量。",
            ]
        )

    priority_order = [
        requirement.requirement_id
        for requirement in sorted(
            requirements,
            key=lambda requirement: _STRATEGY_PRIORITY_RANK[requirement.priority],
        )
    ]
    return ResourceBudgetRiskSummary(
        summary_id=summary.summary_id,
        has_confirmed_budget_ceiling=budget_ceiling is not None,
        budget_ceiling=budget_ceiling,
        requirements=requirements,
        priority_order=priority_order,
        trade_offs=summary.trade_offs,
        excluded_scope=excluded_scope,
        assumptions=assumptions,
        risks=summary.risks,
    )


def _validate_resource_summary_references(
    summary: ResourceBudgetRiskSummary,
    strategies: list[StrategyOption],
    measurement_plan: MeasurementPlan,
) -> None:
    strategy_ids = {strategy.strategy_id for strategy in strategies}
    metric_ids = {metric.metric_id for metric in measurement_plan.metrics}
    for requirement in summary.requirements:
        if not set(requirement.linked_strategy_ids) <= strategy_ids:
            raise ValueError("resource requirements must reference known strategies")
    for risk in summary.risks:
        if not set(risk.monitoring_metric_ids) <= metric_ids:
            raise ValueError("resource risks must reference known measurement metrics")


def _make_unknown_budget_requirement(
    requirement: ResourceRequirement,
) -> ResourceRequirement:
    if requirement.category is not ResourceCategory.BUDGET:
        return requirement
    return requirement.model_copy(
        update={
            "estimate": "待用户确认：渠道投入 + 工具费用 + 内容产能费用 + 人力时间成本",
            "estimate_expression": EstimateExpression.FORMULA,
            "estimation_basis": "用户未提供预算上限，先按资源数量、单位成本和执行周期测算。",
            "needs_confirmation": True,
        }
    )


def _confirmed_budget_ceiling(brief: OperationsBrief) -> str | None:
    field = brief.budget_and_resources
    if field.status is not FieldStatus.CONFIRMED or not isinstance(field.value, str):
        return None
    value = field.value.strip()
    if re.search(r"(待定|待确认|未知|未提供|不清楚)", value):
        return None
    if re.search(r"(无预算|零预算)", value):
        return value
    if re.search(r"(?:预算|上限|封顶|不超过|以内).{0,20}\d", value):
        return value
    if re.search(r"\d+(?:\.\d+)?\s*(?:元|万元|万)", value):
        return value
    return None


def _select_case_for_strategy(
    strategy: StrategyOption,
    case_mechanisms: list[CaseMechanism],
) -> CaseMechanism:
    strategy_evidence = set(strategy.evidence_ids)
    for case in case_mechanisms:
        if strategy_evidence.intersection(case.evidence_ids):
            return case
    return case_mechanisms[0]


def _has_resource_mismatch(case: CaseMechanism, brief: OperationsBrief) -> bool:
    case_text = " ".join([*case.execution_conditions, *case.non_transferable_elements])
    brief_text = _brief_resource_text(brief)
    return bool(
        _HEAD_COMPANY_RESOURCE_PATTERN.search(case_text)
        and _LIMITED_RESOURCE_PATTERN.search(brief_text)
    )


def _brief_resource_text(brief: OperationsBrief) -> str:
    values: list[str] = []
    for field in (
        brief.business_context,
        brief.business_stage,
        brief.budget_and_resources,
        brief.existing_channels,
        brief.constraints,
    ):
        if field.status is FieldStatus.CONFIRMED and field.value is not None:
            value = field.value
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            else:
                values.append(str(value))
    return " ".join(values)


def _scaled_or_abandoned_adaptations(
    case: CaseMechanism,
    adaptations: list[str],
) -> list[str]:
    safe_existing = [
        adaptation
        for adaptation in adaptations
        if not _DIRECT_COPY_PATTERN.search(adaptation)
    ]
    if _should_abandon_due_to_no_transferable(case):
        return _unique(
            [
                *safe_existing,
                f"放弃直接采用：{case.company}案例缺少当前可复用的核心机制。",
            ]
        )
    transferable = "、".join(case.transferable_elements)
    return _unique(
        [
            *safe_existing,
            f"缩小为最小实验：仅验证「{transferable}」中的关键环节，先不复制完整头部玩法。",
        ]
    )


def _should_abandon_due_to_no_transferable(case: CaseMechanism) -> bool:
    return not any(element.strip() for element in case.transferable_elements)


def _reconcile_retention_plan(
    plan: RetentionStrategyPlan,
    *,
    brief: OperationsBrief,
) -> RetentionStrategyPlan:
    has_baseline = _has_reliable_baseline(brief)
    if has_baseline:
        return plan.model_copy(update={"has_reliable_baseline": True})

    key_behaviors = [
        _make_key_retention_behavior_hypothesis(behavior)
        for behavior in plan.key_behaviors
    ]
    cohort_metrics = [
        _make_retention_metric_hypothesis(metric) for metric in plan.cohort_metrics
    ]
    segment_validation_plans = [
        _make_segment_validation_hypothesis(validation)
        for validation in plan.segment_validation_plans
    ]
    limitations = _unique(
        [
            *plan.limitations,
            "用户未提供可靠留存基线，留存目标、召回效果和分群有效性均为待验证假设。",
        ]
    )
    return RetentionStrategyPlan(
        plan_id=plan.plan_id,
        has_reliable_baseline=False,
        lifecycle_stages=plan.lifecycle_stages,
        key_behaviors=key_behaviors,
        segments=plan.segments,
        churn_signals=plan.churn_signals,
        trigger_plans=plan.trigger_plans,
        recall_plans=plan.recall_plans,
        cohort_metrics=cohort_metrics,
        segment_validation_plans=segment_validation_plans,
        strategy_options=plan.strategy_options,
        limitations=limitations,
    )


def _reconcile_campaign_plan(
    plan: CampaignOperationsPlan,
    *,
    brief: OperationsBrief,
) -> CampaignOperationsPlan:
    has_baseline = _has_reliable_baseline(brief)
    if has_baseline:
        return plan.model_copy(update={"has_reliable_baseline": True})

    mechanisms = [
        _make_campaign_mechanism_hypothesis(mechanism)
        for mechanism in plan.mechanisms
    ]
    rhythm = [_make_campaign_phase_hypothesis(phase) for phase in plan.rhythm]
    metrics = [_make_campaign_metric_hypothesis(metric) for metric in plan.metrics]
    limitations = _unique(
        [
            *plan.limitations,
            "用户未提供可靠活动基线，活动增量、转化和成本效率均为待验证假设。",
        ]
    )
    return CampaignOperationsPlan(
        plan_id=plan.plan_id,
        has_reliable_baseline=False,
        goals=plan.goals,
        audiences=plan.audiences,
        mechanisms=mechanisms,
        rhythm=rhythm,
        resources=plan.resources,
        metrics=metrics,
        contingency_plans=plan.contingency_plans,
        retrospective=plan.retrospective,
        strategy_options=plan.strategy_options,
        limitations=limitations,
    )


def _reconcile_content_plan(
    plan: ContentOperationsPlan,
    *,
    brief: OperationsBrief,
) -> ContentOperationsPlan:
    has_baseline = _has_reliable_baseline(brief)
    if has_baseline:
        return plan.model_copy(update={"has_reliable_baseline": True})

    production_cadence = [
        _make_content_cadence_hypothesis(cadence)
        for cadence in plan.production_cadence
    ]
    metrics = [_make_content_metric_hypothesis(metric) for metric in plan.metrics]
    validation_plans = [
        _make_content_validation_hypothesis(validation)
        for validation in plan.validation_plans
    ]
    limitations = _unique(
        [
            *plan.limitations,
            "用户未提供可靠内容运营基线，触达、互动、转化和因果关系均为待验证假设。",
        ]
    )
    return ContentOperationsPlan(
        plan_id=plan.plan_id,
        has_reliable_baseline=False,
        positioning=plan.positioning,
        audiences=plan.audiences,
        theme_matrix=plan.theme_matrix,
        supply_plans=plan.supply_plans,
        production_cadence=production_cadence,
        distribution_plans=plan.distribution_plans,
        conversion_paths=plan.conversion_paths,
        metrics=metrics,
        validation_plans=validation_plans,
        strategy_options=plan.strategy_options,
        limitations=limitations,
    )


def _make_cac_hypothesis(
    assumption: CustomerAcquisitionCostAssumption,
) -> CustomerAcquisitionCostAssumption:
    unknown_inputs = _unique(
        [
            *assumption.unknown_inputs,
            "当前分渠道曝光、到达、注册和首个有效行为基线",
            "渠道可归因成本与合格新客数",
        ]
    )
    return assumption.model_copy(
        update={
            "unknown_inputs": unknown_inputs,
            "estimated_cac_range": "待通过最小渠道实验测算，不作为确定获客成本承诺",
            "target_basis": TargetBasis.TO_BE_VALIDATED,
            "is_hypothesis": True,
            "validation_method": (
                "先记录分渠道曝光、到达、注册、首个有效行为和可归因成本，"
                "再计算合格新客获客成本区间。"
            ),
        }
    )


def _make_channel_experiment_hypothesis(
    experiment: ChannelExperimentPlan,
) -> ChannelExperimentPlan:
    criteria = [
        criterion
        for criterion in experiment.success_criteria
        if not _DEFINITE_EFFECT_PATTERN.search(criterion)
    ]
    criteria = _unique(
        [
            *criteria,
            "完成该渠道曝光、到达、注册、首个有效行为和可归因成本的基线记录",
            "仅在风险指标不恶化且数据可归因时进入下一轮验证",
        ]
    )
    return experiment.model_copy(
        update={
            "success_criteria": criteria,
            "expected_outcome_basis": TargetBasis.TO_BE_VALIDATED,
            "is_success_target_hypothesis": True,
        }
    )


def _make_campaign_mechanism_hypothesis(
    mechanism: CampaignMechanismDesign,
) -> CampaignMechanismDesign:
    return mechanism.model_copy(
        update={
            "expected_outcome_basis": TargetBasis.TO_BE_VALIDATED,
            "is_outcome_hypothesis": True,
        }
    )


def _make_campaign_phase_hypothesis(
    phase: CampaignRhythmPhase,
) -> CampaignRhythmPhase:
    criteria = [
        criterion
        for criterion in phase.acceptance_criteria
        if not _DEFINITE_EFFECT_PATTERN.search(criterion)
    ]
    criteria = _unique(
        [
            *criteria,
            "完成该阶段交付物、埋点记录和继续/停止判断，不作为确定效果承诺",
        ]
    )
    return phase.model_copy(update={"acceptance_criteria": criteria})


def _make_campaign_metric_hypothesis(
    metric: CampaignMetricPlan,
) -> CampaignMetricPlan:
    return metric.model_copy(
        update={
            "decision_rule": (
                "先记录可比基线或对照组，再判断活动是否产生可归因增量。"
            ),
            "target_basis": TargetBasis.TO_BE_VALIDATED,
            "is_target_hypothesis": True,
        }
    )


def _make_content_cadence_hypothesis(
    cadence: ContentProductionCadence,
) -> ContentProductionCadence:
    criteria = [
        criterion
        for criterion in cadence.acceptance_criteria
        if not _DEFINITE_EFFECT_PATTERN.search(criterion)
    ]
    criteria = _unique(
        [
            *criteria,
            "完成选题、生产、审核、发布和数据记录，不作为确定增长承诺",
        ]
    )
    return cadence.model_copy(update={"acceptance_criteria": criteria})


def _make_content_metric_hypothesis(metric: ContentMetricPlan) -> ContentMetricPlan:
    return metric.model_copy(
        update={
            "decision_rule": (
                "先记录有效触达、互动质量和内容后续行为基线，再判断是否扩大主题或渠道。"
            ),
            "target_basis": TargetBasis.TO_BE_VALIDATED,
            "is_target_hypothesis": True,
        }
    )


def _make_content_validation_hypothesis(
    validation: ContentValidationPlan,
) -> ContentValidationPlan:
    criteria = [
        criterion
        for criterion in validation.success_criteria
        if not _DEFINITE_EFFECT_PATTERN.search(criterion)
    ]
    criteria = _unique(
        [
            *criteria,
            "完成同一主题、同一渠道和同一转化窗口的基线记录",
            "仅在互动质量、回流行为和风险指标可归因时进入下一轮验证",
        ]
    )
    return validation.model_copy(
        update={
            "success_criteria": criteria,
            "expected_outcome_basis": TargetBasis.TO_BE_VALIDATED,
            "is_success_target_hypothesis": True,
        }
    )


def _make_measurement_metric_hypothesis(
    metric: MetricDefinition,
) -> MetricDefinition:
    if metric.target is None:
        return metric.model_copy(update={"baseline_value": None, "baseline_source": None})
    target = MetricTarget(
        lower_bound=metric.target.lower_bound,
        upper_bound=metric.target.upper_bound,
        unit=metric.target.unit,
        basis=TargetBasis.TO_BE_VALIDATED,
        rationale="待通过基线实验验证，不作为确定目标承诺。",
        is_hypothesis=True,
    )
    return metric.model_copy(
        update={
            "baseline_value": None,
            "baseline_source": None,
            "target": target,
        }
    )


def _make_baseline_experiment_hypothesis(
    experiment: ExperimentPlan,
) -> ExperimentPlan:
    criteria = [
        criterion
        for criterion in experiment.success_criteria
        if not _DEFINITE_EFFECT_PATTERN.search(criterion)
    ]
    criteria = _unique(
        [
            *criteria,
            "完成当前口径的基线记录，并形成待验证目标区间",
            "仅在风险指标不恶化且数据可归因时进入下一轮策略验证",
        ]
    )
    return experiment.model_copy(update={"success_criteria": criteria})


def _make_key_retention_behavior_hypothesis(
    behavior: KeyRetentionBehavior,
) -> KeyRetentionBehavior:
    return behavior.model_copy(
        update={
            "relationship_basis": TargetBasis.TO_BE_VALIDATED,
            "is_hypothesis": True,
        }
    )


def _make_retention_metric_hypothesis(
    metric: RetentionCohortMetric,
) -> RetentionCohortMetric:
    return metric.model_copy(
        update={
            "data_source": (
                "待按同一 cohort 口径记录起点事件、回访事件、分群和观察窗口"
            ),
            "decision_rule": (
                "先建立至少一个完整观察窗口的基线，再判断触发或召回方案是否进入放大。"
            ),
            "target_basis": TargetBasis.TO_BE_VALIDATED,
            "is_target_hypothesis": True,
        }
    )


def _make_segment_validation_hypothesis(
    validation: SegmentValidationPlan,
) -> SegmentValidationPlan:
    criteria = [
        criterion
        for criterion in validation.success_criteria
        if not _DEFINITE_EFFECT_PATTERN.search(criterion)
    ]
    criteria = _unique(
        [
            *criteria,
            "完成同一分群、同一起点事件、同一回访事件和同一观察窗口的基线记录",
            "仅在风险指标不恶化且分群口径可复现时进入下一轮验证",
        ]
    )
    return validation.model_copy(
        update={
            "success_criteria": criteria,
            "expected_outcome_basis": TargetBasis.TO_BE_VALIDATED,
            "is_success_target_hypothesis": True,
        }
    )


def _has_reliable_baseline(brief: OperationsBrief) -> bool:
    return brief.current_baseline.status is FieldStatus.CONFIRMED


def _confirmed_brief_payload(brief: OperationsBrief) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field_name in type(brief).model_fields:
        field = getattr(brief, field_name)
        if field.status is FieldStatus.CONFIRMED:
            payload[field_name] = field.model_dump(mode="json")
    return payload


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _action_plan_phase_policy(brief: OperationsBrief) -> dict[str, object]:
    if brief.execution_period.status is FieldStatus.CONFIRMED and brief.execution_period.value:
        return {
            "mode": "user_defined",
            "user_period": brief.execution_period.value,
            "phases": "由模型按用户指定周期拆分，但每项行动必须保留时间节点。",
        }
    return {"mode": "default_30_60_90", "phases": _DEFAULT_ACTION_PHASES}


_DEFAULT_ACTION_PHASES = ["0-30天", "31-60天", "61-90天"]

_STRATEGY_PRIORITY_RANK = {
    StrategyPriority.MUST: 0,
    StrategyPriority.SHOULD: 1,
    StrategyPriority.COULD: 2,
    StrategyPriority.WONT_NOW: 3,
}

_DEFINITE_EFFECT_PATTERN = re.compile(
    r"(保证|确定|必然|承诺|提升\s*\d|增长\s*\d|降低\s*\d|\d+(?:\.\d+)?%)"
)
_DIRECT_COPY_PATTERN = re.compile(r"(直接复制|完整复制|照搬|原样采用)")
_HEAD_COMPANY_RESOURCE_PATTERN = re.compile(
    r"(头部|大规模|海量|自然流量|品牌|成熟数据|推荐系统|算法|大促|高预算|多团队|平台级)"
)
_LIMITED_RESOURCE_PATTERN = re.compile(
    r"(冷启动|预算有限|资源有限|小团队|1名|2名|一名|两名|低预算|无预算|没有|缺少)"
)

_ACQUISITION_SYSTEM_PROMPT = "\n".join(
    (
        "你是拉新增长策略模块，只输出结构化 AcquisitionGrowthPlan。",
        "方案必须形成拉新专项关键决策：目标人群、价值主张、渠道组合、触达路径、转化漏斗、CAC假设和渠道实验。",
        "渠道建议必须说明人群匹配、承接路径、成功指标和停止条件。",
        "如果没有可靠基线，只能输出待验证假设和最小实验，不得承诺确定获客成本、规模或转化提升。",
        "策略只用于运营决策支持，不调用任何外部渠道执行投放。",
    )
)

_RETENTION_SYSTEM_PROMPT = "\n".join(
    (
        "你是用户留存策略模块，只输出结构化 RetentionStrategyPlan。",
        "方案必须形成留存专项关键决策：生命周期、关键留存行为、用户分层、流失信号、触发机制、召回策略和分群验证。",
        "留存指标必须明确 cohort 起点事件、回访事件、分群、观察窗口、公式和判断规则。",
        "激活问题不能只用消息召回解决；召回权益不能替代产品核心价值。",
        "如果没有可靠基线，只能输出待验证假设和最小实验，不得承诺确定留存、复购或召回提升。",
        "每个 strategy_options 条目必须有非空 evidence_ids 或 assumption_claim_ids。",
        "每个 strategy_options.impact_path 至少两步。",
        "策略只用于运营决策支持，不调用任何外部渠道执行投放。",
    )
)

_CAMPAIGN_SYSTEM_PROMPT = "\n".join(
    (
        "你是活动运营策略模块，只输出结构化 CampaignOperationsPlan。",
        "方案必须形成活动专项关键决策：单一第一目标、目标人群、核心机制、利益设计、传播节奏、资源、异常预案和复盘。",
        "传播节奏必须覆盖预热、上线、持续、收尾和复盘，每阶段都要有负责人、交付物和验收方式。",
        "涉及权益、库存、流量峰值或客服压力时，必须提供触发阈值、监控指标和降级动作。",
        "如果没有可靠基线，只能输出待验证假设和增量验证方法，不得承诺确定成交、转化或活动增量。",
        "每个 strategy_options 条目必须有非空 evidence_ids 或 assumption_claim_ids。",
        "每个 strategy_options.impact_path 至少两步。",
        "策略只用于运营决策支持，不调用任何外部渠道执行投放。",
    )
)

_CONTENT_SYSTEM_PROMPT = "\n".join(
    (
        "你是内容运营策略模块，只输出结构化 ContentOperationsPlan。",
        "方案必须形成内容专项关键决策：内容定位、目标受众、主题矩阵、供给机制、生产节奏、分发渠道、互动机制和转化路径。",
        "每个主题必须绑定受众问题、内容任务、供给责任和质量标准，不能只是通用栏目标题。",
        "每个渠道必须说明用户意图、原生内容形态、互动设计和回流路径。",
        "如果没有可靠基线，只能输出待验证假设和内容实验，不得承诺确定触达、互动或转化提升。",
        "策略只用于运营决策支持，不调用任何外部渠道执行投放。",
    )
)

_ACTION_PLAN_SYSTEM_PROMPT = "\n".join(
    (
        "你是阶段行动计划生成模块，只输出结构化 ActionPlan。",
        "每个 ActionItem 必须形成闭环：目标、目标人群、行动、触点、"
        "负责人角色、前置条件、资源、交付物、时间节点和验收方式。",
        "用户未指定周期时使用 0-30天、31-60天、61-90天 三阶段，并把早期阶段用于验证关键假设。",
        "用户指定周期时按该周期拆分阶段，但不得省略交付物和验收。",
        "计划只用于运营决策支持，不调用任何外部平台执行。",
    )
)

_MEASUREMENT_PLAN_SYSTEM_PROMPT = "\n".join(
    (
        "你是指标与实验计划生成模块，只输出结构化 MeasurementPlan。",
        "必须同时设计结果指标、过程指标和风险指标，并写清口径、公式、数据来源、观测周期和判断规则。",
        "必须为核心策略提供实验计划，说明假设、关联策略、目标人群、设计、对照、周期、主要指标、样本方法、成功标准和停止条件。",
        "如果存在可靠基线，可以基于基线给出有依据的目标区间；没有基线时只能输出待验证区间或建立基线的实验。",
        "每项 metric 的 baseline_value 与 baseline_source 必须同时存在或同时为 null。",
        "无基线的 target 必须标记 is_hypothesis=true，basis 不得为 provided_baseline。",
        "不得把缺少依据的提升幅度表述为确定目标或效果承诺。",
    )
)

_RESOURCE_BUDGET_RISK_SYSTEM_PROMPT = "\n".join(
    (
        "你是资源、预算与风险汇总模块，只输出结构化 ResourceBudgetRiskSummary。",
        "必须汇总人员角色、渠道、工具、内容产能、执行时间和预算六类资源，并绑定对应策略。",
        "priority_order 必须恰好包含 requirements 中每个 requirement_id 一次，不得遗漏或重复。",
        "每个 requirement.linked_strategy_ids 至少包含一个已有策略编号。",
        "用户提供预算上限时，必须按 MUST、SHOULD、COULD、WONT_NOW 排序，明确取舍和本期排除范围。",
        "用户未提供预算时，只能给出成本区间、测算公式或待确认项，不得生成伪精确金额。",
        "每项风险必须说明触发条件、缓解动作、负责人角色和可观测的风险指标。",
        "所有估算均用于决策支持，不能表述为已经发生的事实或确定承诺。",
    )
)
