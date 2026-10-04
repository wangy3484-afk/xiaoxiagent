"""Diagnosis, strategy, execution, measurement, and report contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ops_agent.domain.base import DomainModel
from ops_agent.domain.intake import OperationsBrief, OperationsScene, SceneClassification
from ops_agent.domain.research import CaseMechanism, Claim, ClaimType, EvidenceRecord


class GoalRelationship(DomainModel):
    business_goal: str = Field(min_length=3, max_length=1000)
    operations_goal: str = Field(min_length=3, max_length=1000)
    target_behavior: str = Field(min_length=3, max_length=1000)
    metric_ids: list[str] = Field(min_length=1)


class Diagnosis(DomainModel):
    business_stage: str = Field(min_length=2, max_length=500)
    target_users: str = Field(min_length=2, max_length=1000)
    goal_relationships: list[GoalRelationship] = Field(min_length=1)
    behavior_path: list[str] = Field(min_length=2)
    core_problem: str = Field(min_length=3, max_length=1500)
    supporting_claim_ids: list[str] = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
    priority_rationale: str = Field(min_length=3, max_length=1500)
    alternative_explanations: list[str] = Field(default_factory=list)
    data_needed: list[str] = Field(default_factory=list)


class StrategyPriority(StrEnum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"
    WONT_NOW = "wont_now"


class StrategyOption(DomainModel):
    strategy_id: str = Field(min_length=1, max_length=80)
    scene: OperationsScene
    title: str = Field(min_length=3, max_length=300)
    target_segment: str = Field(min_length=3, max_length=1000)
    strategy_logic: str = Field(min_length=10, max_length=2500)
    evidence_ids: list[str] = Field(default_factory=list)
    assumption_claim_ids: list[str] = Field(default_factory=list)
    applicability_conditions: list[str] = Field(min_length=1)
    scene_differences: list[str] = Field(min_length=1)
    adaptations: list[str] = Field(min_length=1)
    impact_path: list[str] = Field(min_length=2)
    non_copyable_factors: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    priority: StrategyPriority

    @model_validator(mode="after")
    def require_evidence_or_explicit_assumptions(self) -> Self:
        if not self.evidence_ids and not self.assumption_claim_ids:
            raise ValueError("strategies require evidence or explicit assumption claims")
        return self


class ActionItem(DomainModel):
    action_id: str = Field(min_length=1, max_length=80)
    strategy_id: str = Field(min_length=1, max_length=80)
    phase: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=3, max_length=1000)
    target_audience: str = Field(min_length=3, max_length=1000)
    action: str = Field(min_length=5, max_length=2500)
    touchpoint: str = Field(min_length=2, max_length=500)
    owner_role: str = Field(min_length=2, max_length=200)
    prerequisites: list[str] = Field(min_length=1)
    resources: list[str] = Field(min_length=1)
    deliverable: str = Field(min_length=3, max_length=1000)
    timeline: str = Field(min_length=2, max_length=500)
    acceptance_criteria: list[str] = Field(min_length=1)


class ActionPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=80)
    phases: list[str] = Field(min_length=1)
    actions: list[ActionItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_action_phase_references(self) -> Self:
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action IDs must be unique")
        phases = set(self.phases)
        for action in self.actions:
            if action.phase not in phases:
                raise ValueError("actions must reference declared phases")
        return self


class MetricType(StrEnum):
    OUTCOME = "outcome"
    PROCESS = "process"
    RISK = "risk"


class TargetBasis(StrEnum):
    PROVIDED_BASELINE = "provided_baseline"
    EXTERNAL_EVIDENCE = "external_evidence"
    TO_BE_VALIDATED = "to_be_validated"


class AcquisitionChannelRole(StrEnum):
    EXPLORE = "explore"
    SCALE = "scale"
    SUPPORT = "support"


class AcquisitionTargetSegment(DomainModel):
    segment_id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=3, max_length=1000)
    qualification_criteria: list[str] = Field(min_length=1)
    first_value_action: str = Field(min_length=3, max_length=500)
    excluded_segments: list[str] = Field(default_factory=list)


class AcquisitionValueProposition(DomainModel):
    proposition_id: str = Field(min_length=1, max_length=80)
    target_segment_id: str = Field(min_length=1, max_length=80)
    pain_point: str = Field(min_length=3, max_length=1000)
    message: str = Field(min_length=5, max_length=1000)
    proof_needed: list[str] = Field(min_length=1)


class AcquisitionChannelPlan(DomainModel):
    channel_id: str = Field(min_length=1, max_length=80)
    channel_name: str = Field(min_length=2, max_length=200)
    role: AcquisitionChannelRole
    target_segment_id: str = Field(min_length=1, max_length=80)
    value_proposition_id: str = Field(min_length=1, max_length=80)
    traffic_source: str = Field(min_length=2, max_length=500)
    touchpoints: list[str] = Field(min_length=1)
    conversion_path: list[str] = Field(min_length=2)
    cost_hypothesis_id: str = Field(min_length=1, max_length=80)


class AcquisitionFunnelStep(DomainModel):
    step_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    user_action: str = Field(min_length=3, max_length=500)
    metric_id: str = Field(min_length=1, max_length=80)
    dropoff_risk: str = Field(min_length=3, max_length=1000)


class CustomerAcquisitionCostAssumption(DomainModel):
    assumption_id: str = Field(min_length=1, max_length=80)
    channel_id: str = Field(min_length=1, max_length=80)
    formula: str = Field(min_length=3, max_length=1000)
    known_inputs: list[str] = Field(default_factory=list)
    unknown_inputs: list[str] = Field(min_length=1)
    estimated_cac_range: str = Field(min_length=2, max_length=500)
    target_basis: TargetBasis
    is_hypothesis: bool
    validation_method: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def validate_unverified_cost_targets(self) -> Self:
        if self.target_basis is TargetBasis.TO_BE_VALIDATED and not self.is_hypothesis:
            raise ValueError("unvalidated CAC assumptions must be labeled as hypotheses")
        return self


class ChannelExperimentPlan(DomainModel):
    experiment_id: str = Field(min_length=1, max_length=80)
    channel_id: str = Field(min_length=1, max_length=80)
    hypothesis: str = Field(min_length=5, max_length=1000)
    design: str = Field(min_length=10, max_length=2000)
    duration: str = Field(min_length=2, max_length=500)
    primary_metric_id: str = Field(min_length=1, max_length=80)
    success_criteria: list[str] = Field(min_length=1)
    stop_conditions: list[str] = Field(min_length=1)
    expected_outcome_basis: TargetBasis
    is_success_target_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_experiment_targets(self) -> Self:
        if (
            self.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
            and not self.is_success_target_hypothesis
        ):
            raise ValueError("unvalidated channel outcomes must be hypotheses")
        return self


class AcquisitionGrowthPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=80)
    has_reliable_baseline: bool
    target_segments: list[AcquisitionTargetSegment] = Field(min_length=1)
    value_propositions: list[AcquisitionValueProposition] = Field(min_length=1)
    channel_mix: list[AcquisitionChannelPlan] = Field(min_length=1)
    conversion_funnel: list[AcquisitionFunnelStep] = Field(min_length=2)
    cac_assumptions: list[CustomerAcquisitionCostAssumption] = Field(min_length=1)
    channel_experiments: list[ChannelExperimentPlan] = Field(min_length=1)
    strategy_options: list[StrategyOption] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_acquisition_references(self) -> Self:
        segment_ids = {item.segment_id for item in self.target_segments}
        proposition_ids = {item.proposition_id for item in self.value_propositions}
        channel_ids = {item.channel_id for item in self.channel_mix}
        cost_ids = {item.assumption_id for item in self.cac_assumptions}
        metric_ids = {item.metric_id for item in self.conversion_funnel}

        for proposition in self.value_propositions:
            if proposition.target_segment_id not in segment_ids:
                raise ValueError("value propositions must reference target segments")
        for channel in self.channel_mix:
            if channel.target_segment_id not in segment_ids:
                raise ValueError("channels must reference target segments")
            if channel.value_proposition_id not in proposition_ids:
                raise ValueError("channels must reference value propositions")
            if channel.cost_hypothesis_id not in cost_ids:
                raise ValueError("channels must reference CAC assumptions")
        for assumption in self.cac_assumptions:
            if assumption.channel_id not in channel_ids:
                raise ValueError("CAC assumptions must reference channels")
        for experiment in self.channel_experiments:
            if experiment.channel_id not in channel_ids:
                raise ValueError("channel experiments must reference channels")
            if experiment.primary_metric_id not in metric_ids:
                raise ValueError("channel experiments must reference funnel metrics")
        if not self.has_reliable_baseline:
            for assumption in self.cac_assumptions:
                if (
                    assumption.target_basis is not TargetBasis.TO_BE_VALIDATED
                    or not assumption.is_hypothesis
                ):
                    raise ValueError(
                        "plans without baselines must keep CAC assumptions unvalidated"
                    )
            for experiment in self.channel_experiments:
                if (
                    experiment.expected_outcome_basis is not TargetBasis.TO_BE_VALIDATED
                    or not experiment.is_success_target_hypothesis
                ):
                    raise ValueError(
                        "plans without baselines must keep channel outcomes unvalidated"
                    )
        return self


class RetentionLifecycleStage(DomainModel):
    stage_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    entry_condition: str = Field(min_length=3, max_length=1000)
    exit_condition: str = Field(min_length=3, max_length=1000)
    user_goal: str = Field(min_length=3, max_length=1000)
    operating_goal: str = Field(min_length=3, max_length=1000)


class KeyRetentionBehavior(DomainModel):
    behavior_id: str = Field(min_length=1, max_length=80)
    lifecycle_stage_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    event_definition: str = Field(min_length=5, max_length=1000)
    value_signal: str = Field(min_length=5, max_length=1000)
    relationship_basis: TargetBasis
    is_hypothesis: bool
    supporting_claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unverified_behavior_relationship(self) -> Self:
        if self.relationship_basis is TargetBasis.TO_BE_VALIDATED and not self.is_hypothesis:
            raise ValueError(
                "unvalidated key retention behaviors must be labeled as hypotheses"
            )
        return self


class RetentionSegmentRule(DomainModel):
    segment_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    lifecycle_stage_id: str = Field(min_length=1, max_length=80)
    rule: str = Field(min_length=5, max_length=1000)
    included_users: str = Field(min_length=3, max_length=1000)
    excluded_users: list[str] = Field(default_factory=list)
    primary_churn_risk: str = Field(min_length=3, max_length=1000)


class ChurnSignal(DomainModel):
    signal_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    signal: str = Field(min_length=3, max_length=1000)
    observation_window: str = Field(min_length=2, max_length=500)
    likely_causes: list[str] = Field(min_length=1)
    data_needed: list[str] = Field(min_length=1)


class RetentionTriggerPlan(DomainModel):
    trigger_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    linked_signal_id: str | None = Field(default=None, max_length=80)
    trigger_timing: str = Field(min_length=2, max_length=500)
    channel: str = Field(min_length=2, max_length=300)
    message: str = Field(min_length=5, max_length=1000)
    value_feedback: str = Field(min_length=5, max_length=1000)
    frequency_control: str = Field(min_length=3, max_length=1000)
    guardrail_metric_ids: list[str] = Field(min_length=1)


class RetentionRecallPlan(DomainModel):
    recall_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    linked_signal_id: str = Field(min_length=1, max_length=80)
    recovery_value: str = Field(min_length=5, max_length=1000)
    offer_or_content: str = Field(min_length=5, max_length=1000)
    contact_path: list[str] = Field(min_length=1)
    stop_conditions: list[str] = Field(min_length=1)
    success_metric_id: str = Field(min_length=1, max_length=80)


class RetentionCohortMetric(DomainModel):
    metric_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    segment_id: str = Field(min_length=1, max_length=80)
    cohort_entry_event: str = Field(min_length=3, max_length=500)
    retention_event: str = Field(min_length=3, max_length=500)
    observation_window: str = Field(min_length=2, max_length=500)
    formula: str = Field(min_length=5, max_length=1000)
    data_source: str = Field(min_length=2, max_length=500)
    decision_rule: str = Field(min_length=5, max_length=1000)
    target_basis: TargetBasis
    is_target_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_metric_targets(self) -> Self:
        if self.target_basis is TargetBasis.TO_BE_VALIDATED and not self.is_target_hypothesis:
            raise ValueError("unvalidated retention targets must be hypotheses")
        return self


class SegmentValidationPlan(DomainModel):
    validation_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    hypothesis: str = Field(min_length=5, max_length=1000)
    method: str = Field(min_length=10, max_length=2000)
    primary_metric_id: str = Field(min_length=1, max_length=80)
    sample_or_duration: str = Field(min_length=2, max_length=500)
    success_criteria: list[str] = Field(min_length=1)
    expected_outcome_basis: TargetBasis
    is_success_target_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_validation_targets(self) -> Self:
        if (
            self.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
            and not self.is_success_target_hypothesis
        ):
            raise ValueError("unvalidated segment outcomes must be hypotheses")
        return self


class RetentionStrategyPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=80)
    has_reliable_baseline: bool
    lifecycle_stages: list[RetentionLifecycleStage] = Field(min_length=2)
    key_behaviors: list[KeyRetentionBehavior] = Field(min_length=1)
    segments: list[RetentionSegmentRule] = Field(min_length=1)
    churn_signals: list[ChurnSignal] = Field(min_length=1)
    trigger_plans: list[RetentionTriggerPlan] = Field(min_length=1)
    recall_plans: list[RetentionRecallPlan] = Field(min_length=1)
    cohort_metrics: list[RetentionCohortMetric] = Field(min_length=1)
    segment_validation_plans: list[SegmentValidationPlan] = Field(min_length=1)
    strategy_options: list[StrategyOption] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_retention_references(self) -> Self:
        stage_ids = {stage.stage_id for stage in self.lifecycle_stages}
        segment_ids = {segment.segment_id for segment in self.segments}
        signal_ids = {signal.signal_id for signal in self.churn_signals}
        metric_ids = {metric.metric_id for metric in self.cohort_metrics}

        for behavior in self.key_behaviors:
            if behavior.lifecycle_stage_id not in stage_ids:
                raise ValueError("key retention behaviors must reference lifecycle stages")
        for segment in self.segments:
            if segment.lifecycle_stage_id not in stage_ids:
                raise ValueError("retention segments must reference lifecycle stages")
        for signal in self.churn_signals:
            if signal.segment_id not in segment_ids:
                raise ValueError("churn signals must reference retention segments")
        for trigger in self.trigger_plans:
            if trigger.segment_id not in segment_ids:
                raise ValueError("retention triggers must reference retention segments")
            if trigger.linked_signal_id is not None and trigger.linked_signal_id not in signal_ids:
                raise ValueError("retention triggers must reference known churn signals")
        for recall in self.recall_plans:
            if recall.segment_id not in segment_ids:
                raise ValueError("retention recalls must reference retention segments")
            if recall.linked_signal_id not in signal_ids:
                raise ValueError("retention recalls must reference churn signals")
            if recall.success_metric_id not in metric_ids:
                raise ValueError("retention recalls must reference cohort metrics")
        for metric in self.cohort_metrics:
            if metric.segment_id not in segment_ids:
                raise ValueError("retention cohort metrics must reference retention segments")
        for validation in self.segment_validation_plans:
            if validation.segment_id not in segment_ids:
                raise ValueError("segment validations must reference retention segments")
            if validation.primary_metric_id not in metric_ids:
                raise ValueError("segment validations must reference cohort metrics")
        if not self.has_reliable_baseline:
            for behavior in self.key_behaviors:
                if (
                    behavior.relationship_basis is not TargetBasis.TO_BE_VALIDATED
                    or not behavior.is_hypothesis
                ):
                    raise ValueError(
                        "retention plans without baselines must keep key behaviors unvalidated"
                    )
            for metric in self.cohort_metrics:
                if (
                    metric.target_basis is not TargetBasis.TO_BE_VALIDATED
                    or not metric.is_target_hypothesis
                ):
                    raise ValueError(
                        "retention plans without baselines must keep metric targets unvalidated"
                    )
            for validation in self.segment_validation_plans:
                if (
                    validation.expected_outcome_basis is not TargetBasis.TO_BE_VALIDATED
                    or not validation.is_success_target_hypothesis
                ):
                    raise ValueError(
                        "retention plans without baselines must keep segment outcomes unvalidated"
                    )
        return self


class CampaignPhase(StrEnum):
    WARM_UP = "warm_up"
    LAUNCH = "launch"
    SUSTAIN = "sustain"
    CLOSE = "close"
    RETROSPECTIVE = "retrospective"


class CampaignGoalDesign(DomainModel):
    goal_id: str = Field(min_length=1, max_length=80)
    primary_goal: str = Field(min_length=3, max_length=1000)
    target_behavior: str = Field(min_length=3, max_length=1000)
    guardrail_goals: list[str] = Field(min_length=1)
    non_priority_goals: list[str] = Field(default_factory=list)


class CampaignAudienceSegment(DomainModel):
    audience_id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=3, max_length=1000)
    eligibility_rule: str = Field(min_length=5, max_length=1000)
    motivation: str = Field(min_length=3, max_length=1000)
    exclusion_rule: str = Field(min_length=3, max_length=1000)


class CampaignMechanismDesign(DomainModel):
    mechanism_id: str = Field(min_length=1, max_length=80)
    audience_id: str = Field(min_length=1, max_length=80)
    target_behavior: str = Field(min_length=3, max_length=1000)
    participation_rule: str = Field(min_length=5, max_length=1000)
    incentive_design: str = Field(min_length=5, max_length=1000)
    cost_cap: str = Field(min_length=2, max_length=500)
    anti_abuse_rule: str = Field(min_length=5, max_length=1000)
    expected_outcome_basis: TargetBasis
    is_outcome_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_mechanism_outcome(self) -> Self:
        if (
            self.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
            and not self.is_outcome_hypothesis
        ):
            raise ValueError("unvalidated campaign outcomes must be hypotheses")
        return self


class CampaignRhythmPhase(DomainModel):
    phase: CampaignPhase
    objective: str = Field(min_length=3, max_length=1000)
    timing: str = Field(min_length=2, max_length=500)
    touchpoints: list[str] = Field(min_length=1)
    content_or_action: str = Field(min_length=5, max_length=1500)
    owner_role: str = Field(min_length=2, max_length=200)
    resources: list[str] = Field(min_length=1)
    deliverable: str = Field(min_length=3, max_length=1000)
    acceptance_criteria: list[str] = Field(min_length=1)


class CampaignResourcePlan(DomainModel):
    resource_id: str = Field(min_length=1, max_length=80)
    resource_type: str = Field(min_length=2, max_length=200)
    requirement: str = Field(min_length=3, max_length=1000)
    capacity_limit: str = Field(min_length=3, max_length=1000)
    owner_role: str = Field(min_length=2, max_length=200)


class CampaignMetricPlan(DomainModel):
    metric_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    formula: str = Field(min_length=5, max_length=1000)
    observation_window: str = Field(min_length=2, max_length=500)
    decision_rule: str = Field(min_length=5, max_length=1000)
    target_basis: TargetBasis
    is_target_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_campaign_metric_targets(self) -> Self:
        if self.target_basis is TargetBasis.TO_BE_VALIDATED and not self.is_target_hypothesis:
            raise ValueError("unvalidated campaign metric targets must be hypotheses")
        return self


class CampaignContingencyPlan(DomainModel):
    contingency_id: str = Field(min_length=1, max_length=80)
    risk: str = Field(min_length=3, max_length=1000)
    trigger_threshold: str = Field(min_length=3, max_length=1000)
    response_action: str = Field(min_length=5, max_length=1500)
    owner_role: str = Field(min_length=2, max_length=200)
    monitoring_metric_id: str = Field(min_length=1, max_length=80)


class CampaignRetrospectivePlan(DomainModel):
    review_time: str = Field(min_length=2, max_length=500)
    required_inputs: list[str] = Field(min_length=1)
    analysis_questions: list[str] = Field(min_length=1)
    follow_up_decisions: list[str] = Field(min_length=1)


class CampaignOperationsPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=80)
    has_reliable_baseline: bool
    goals: list[CampaignGoalDesign] = Field(min_length=1)
    audiences: list[CampaignAudienceSegment] = Field(min_length=1)
    mechanisms: list[CampaignMechanismDesign] = Field(min_length=1)
    rhythm: list[CampaignRhythmPhase] = Field(min_length=5)
    resources: list[CampaignResourcePlan] = Field(min_length=1)
    metrics: list[CampaignMetricPlan] = Field(min_length=1)
    contingency_plans: list[CampaignContingencyPlan] = Field(min_length=1)
    retrospective: CampaignRetrospectivePlan
    strategy_options: list[StrategyOption] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_campaign_references_and_rhythm(self) -> Self:
        audience_ids = {audience.audience_id for audience in self.audiences}
        metric_ids = {metric.metric_id for metric in self.metrics}
        phases = {phase.phase for phase in self.rhythm}
        expected_phases = {
            CampaignPhase.WARM_UP,
            CampaignPhase.LAUNCH,
            CampaignPhase.SUSTAIN,
            CampaignPhase.CLOSE,
            CampaignPhase.RETROSPECTIVE,
        }

        if phases != expected_phases:
            raise ValueError(
                "campaign rhythm must cover warm_up, launch, sustain, close, "
                "and retrospective"
            )
        for mechanism in self.mechanisms:
            if mechanism.audience_id not in audience_ids:
                raise ValueError("campaign mechanisms must reference audiences")
        for contingency in self.contingency_plans:
            if contingency.monitoring_metric_id not in metric_ids:
                raise ValueError("campaign contingencies must reference metrics")
        if not self.has_reliable_baseline:
            for mechanism in self.mechanisms:
                if (
                    mechanism.expected_outcome_basis is not TargetBasis.TO_BE_VALIDATED
                    or not mechanism.is_outcome_hypothesis
                ):
                    raise ValueError(
                        "campaign plans without baselines must keep mechanism outcomes unvalidated"
                    )
            for metric in self.metrics:
                if (
                    metric.target_basis is not TargetBasis.TO_BE_VALIDATED
                    or not metric.is_target_hypothesis
                ):
                    raise ValueError(
                        "campaign plans without baselines must keep metric targets unvalidated"
                    )
        return self


class ContentPositioning(DomainModel):
    positioning_id: str = Field(min_length=1, max_length=80)
    audience_job: str = Field(min_length=5, max_length=1000)
    value_promise: str = Field(min_length=5, max_length=1000)
    business_behavior: str = Field(min_length=3, max_length=1000)
    editorial_boundary: list[str] = Field(min_length=1)


class ContentAudienceSegment(DomainModel):
    audience_id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=3, max_length=1000)
    job_to_be_done: str = Field(min_length=5, max_length=1000)
    intent_signals: list[str] = Field(min_length=1)
    conversion_need: str = Field(min_length=3, max_length=1000)


class ContentThemePillar(DomainModel):
    theme_id: str = Field(min_length=1, max_length=80)
    audience_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    audience_problem: str = Field(min_length=5, max_length=1000)
    content_task: str = Field(min_length=5, max_length=1000)
    formats: list[str] = Field(min_length=1)
    supply_owner_role: str = Field(min_length=2, max_length=200)
    cadence: str = Field(min_length=2, max_length=500)
    quality_standard: str = Field(min_length=5, max_length=1000)


class ContentSupplyPlan(DomainModel):
    supply_id: str = Field(min_length=1, max_length=80)
    theme_id: str = Field(min_length=1, max_length=80)
    source_role: str = Field(min_length=2, max_length=200)
    source_material: str = Field(min_length=3, max_length=1000)
    capacity: str = Field(min_length=2, max_length=500)
    review_gate: str = Field(min_length=5, max_length=1000)
    bottleneck: str = Field(min_length=3, max_length=1000)


class ContentProductionCadence(DomainModel):
    cadence_id: str = Field(min_length=1, max_length=80)
    theme_id: str = Field(min_length=1, max_length=80)
    frequency: str = Field(min_length=2, max_length=500)
    workflow_steps: list[str] = Field(min_length=2)
    owner_role: str = Field(min_length=2, max_length=200)
    acceptance_criteria: list[str] = Field(min_length=1)


class ContentDistributionPlan(DomainModel):
    distribution_id: str = Field(min_length=1, max_length=80)
    theme_id: str = Field(min_length=1, max_length=80)
    channel: str = Field(min_length=2, max_length=200)
    user_intent: str = Field(min_length=5, max_length=1000)
    native_format: str = Field(min_length=3, max_length=1000)
    distribution_action: str = Field(min_length=5, max_length=1000)
    interaction_design: str = Field(min_length=5, max_length=1000)
    return_path: str = Field(min_length=5, max_length=1000)
    conversion_action: str = Field(min_length=5, max_length=1000)


class ContentConversionPath(DomainModel):
    path_id: str = Field(min_length=1, max_length=80)
    audience_id: str = Field(min_length=1, max_length=80)
    from_content_signal: str = Field(min_length=5, max_length=1000)
    next_step: str = Field(min_length=5, max_length=1000)
    business_behavior: str = Field(min_length=3, max_length=1000)
    measurement_metric_id: str = Field(min_length=1, max_length=80)


class ContentMetricPlan(DomainModel):
    metric_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    formula: str = Field(min_length=5, max_length=1000)
    observation_window: str = Field(min_length=2, max_length=500)
    decision_rule: str = Field(min_length=5, max_length=1000)
    target_basis: TargetBasis
    is_target_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_content_metric_targets(self) -> Self:
        if self.target_basis is TargetBasis.TO_BE_VALIDATED and not self.is_target_hypothesis:
            raise ValueError("unvalidated content metric targets must be hypotheses")
        return self


class ContentValidationPlan(DomainModel):
    validation_id: str = Field(min_length=1, max_length=80)
    linked_theme_ids: list[str] = Field(min_length=1)
    hypothesis: str = Field(min_length=5, max_length=1000)
    method: str = Field(min_length=10, max_length=2000)
    primary_metric_id: str = Field(min_length=1, max_length=80)
    success_criteria: list[str] = Field(min_length=1)
    expected_outcome_basis: TargetBasis
    is_success_target_hypothesis: bool

    @model_validator(mode="after")
    def validate_unverified_content_outcomes(self) -> Self:
        if (
            self.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
            and not self.is_success_target_hypothesis
        ):
            raise ValueError("unvalidated content outcomes must be hypotheses")
        return self


class ContentOperationsPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=80)
    has_reliable_baseline: bool
    positioning: ContentPositioning
    audiences: list[ContentAudienceSegment] = Field(min_length=1)
    theme_matrix: list[ContentThemePillar] = Field(min_length=1)
    supply_plans: list[ContentSupplyPlan] = Field(min_length=1)
    production_cadence: list[ContentProductionCadence] = Field(min_length=1)
    distribution_plans: list[ContentDistributionPlan] = Field(min_length=1)
    conversion_paths: list[ContentConversionPath] = Field(min_length=1)
    metrics: list[ContentMetricPlan] = Field(min_length=1)
    validation_plans: list[ContentValidationPlan] = Field(min_length=1)
    strategy_options: list[StrategyOption] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_content_references(self) -> Self:
        audience_ids = {audience.audience_id for audience in self.audiences}
        theme_ids = {theme.theme_id for theme in self.theme_matrix}
        metric_ids = {metric.metric_id for metric in self.metrics}

        for theme in self.theme_matrix:
            if theme.audience_id not in audience_ids:
                raise ValueError("content themes must reference audiences")
        for supply in self.supply_plans:
            if supply.theme_id not in theme_ids:
                raise ValueError("content supply plans must reference themes")
        for cadence in self.production_cadence:
            if cadence.theme_id not in theme_ids:
                raise ValueError("content cadence must reference themes")
        for distribution in self.distribution_plans:
            if distribution.theme_id not in theme_ids:
                raise ValueError("content distribution must reference themes")
        for path in self.conversion_paths:
            if path.audience_id not in audience_ids:
                raise ValueError("content conversion paths must reference audiences")
            if path.measurement_metric_id not in metric_ids:
                raise ValueError("content conversion paths must reference metrics")
        for validation in self.validation_plans:
            if not set(validation.linked_theme_ids) <= theme_ids:
                raise ValueError("content validations must reference themes")
            if validation.primary_metric_id not in metric_ids:
                raise ValueError("content validations must reference metrics")
        if not self.has_reliable_baseline:
            for metric in self.metrics:
                if (
                    metric.target_basis is not TargetBasis.TO_BE_VALIDATED
                    or not metric.is_target_hypothesis
                ):
                    raise ValueError(
                        "content plans without baselines must keep metric targets unvalidated"
                    )
            for validation in self.validation_plans:
                if (
                    validation.expected_outcome_basis is not TargetBasis.TO_BE_VALIDATED
                    or not validation.is_success_target_hypothesis
                ):
                    raise ValueError(
                        "content plans without baselines must keep validation outcomes unvalidated"
                    )
        return self


class MetricTarget(DomainModel):
    lower_bound: float
    upper_bound: float
    unit: str = Field(min_length=1, max_length=50)
    basis: TargetBasis
    rationale: str = Field(min_length=5, max_length=1000)
    is_hypothesis: bool

    @model_validator(mode="after")
    def validate_target_range(self) -> Self:
        if self.lower_bound > self.upper_bound:
            raise ValueError("metric target lower_bound cannot exceed upper_bound")
        if self.basis is TargetBasis.TO_BE_VALIDATED and not self.is_hypothesis:
            raise ValueError("unvalidated metric targets must be labeled as hypotheses")
        return self


class MetricDefinition(DomainModel):
    metric_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    metric_type: MetricType
    definition: str = Field(min_length=5, max_length=1000)
    formula: str = Field(min_length=3, max_length=1000)
    data_source: str = Field(min_length=2, max_length=500)
    observation_period: str = Field(min_length=2, max_length=500)
    decision_rule: str = Field(min_length=5, max_length=1000)
    baseline_value: float | None = None
    baseline_source: str | None = Field(default=None, max_length=500)
    target: MetricTarget | None = None

    @model_validator(mode="after")
    def validate_baseline_and_target_basis(self) -> Self:
        if (self.baseline_value is None) != (self.baseline_source is None):
            raise ValueError("baseline value and source must be provided together")
        if self.target is None:
            return self
        if self.target.basis is TargetBasis.PROVIDED_BASELINE and self.baseline_value is None:
            raise ValueError("baseline-based targets require a provided baseline")
        if self.baseline_value is None and not self.target.is_hypothesis:
            raise ValueError("targets without a baseline must be labeled as hypotheses")
        return self


class ExperimentPlan(DomainModel):
    experiment_id: str = Field(min_length=1, max_length=80)
    hypothesis_claim_id: str = Field(min_length=1, max_length=80)
    linked_strategy_ids: list[str] = Field(min_length=1)
    target_segment: str = Field(min_length=3, max_length=1000)
    design: str = Field(min_length=10, max_length=2500)
    comparison: str = Field(min_length=3, max_length=1000)
    duration: str = Field(min_length=2, max_length=500)
    primary_metric_ids: list[str] = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    sample_size_method: str = Field(min_length=5, max_length=1000)
    stop_conditions: list[str] = Field(min_length=1)


class MeasurementPlan(DomainModel):
    plan_id: str = Field(min_length=1, max_length=80)
    metrics: list[MetricDefinition] = Field(min_length=3)
    experiments: list[ExperimentPlan] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_measurement_coverage_and_references(self) -> Self:
        metric_types = {metric.metric_type for metric in self.metrics}
        required_types = {MetricType.OUTCOME, MetricType.PROCESS, MetricType.RISK}
        if not required_types <= metric_types:
            raise ValueError("measurement plans must include outcome, process, and risk metrics")

        metric_ids = {metric.metric_id for metric in self.metrics}
        if len(metric_ids) != len(self.metrics):
            raise ValueError("metric IDs must be unique")
        for experiment in self.experiments:
            if not set(experiment.primary_metric_ids) <= metric_ids:
                raise ValueError("experiments must reference measurement metrics")
        return self


class AudienceAnalysis(DomainModel):
    segments: list[str] = Field(min_length=1)
    priority_segment: str = Field(min_length=2, max_length=1000)
    needs_and_barriers: list[str] = Field(min_length=1)
    behavioral_signals: list[str] = Field(min_length=1)


class ReportNarrative(DomainModel):
    title: str = Field(min_length=3, max_length=300)
    executive_summary: str = Field(min_length=20, max_length=5000)
    audience_analysis: AudienceAnalysis
    supplemental_claims: list[Claim] = Field(min_length=3)
    limitations: list[str] = Field(min_length=1)
    decision_support_notice: str = Field(min_length=20, max_length=2000)

    @model_validator(mode="after")
    def validate_supplemental_claim_labels(self) -> Self:
        if any(
            claim.claim_type is ClaimType.FACT for claim in self.supplemental_claims
        ):
            raise ValueError("report narrative cannot introduce new fact claims")
        required_types = {
            ClaimType.INFERENCE,
            ClaimType.RECOMMENDATION,
            ClaimType.HYPOTHESIS,
        }
        actual_types = {claim.claim_type for claim in self.supplemental_claims}
        if not required_types <= actual_types:
            raise ValueError(
                "report narrative must distinguish inference, recommendation, and hypothesis"
            )
        return self


class ResourceBudgetItem(DomainModel):
    item: str = Field(min_length=2, max_length=300)
    estimate: str = Field(min_length=2, max_length=500)
    estimation_basis: str = Field(min_length=3, max_length=1000)
    needs_confirmation: bool


class ResourceCategory(StrEnum):
    PERSONNEL = "personnel"
    CHANNEL = "channel"
    TOOL = "tool"
    CONTENT_CAPACITY = "content_capacity"
    TIME = "time"
    BUDGET = "budget"


class EstimateExpression(StrEnum):
    USER_PROVIDED = "user_provided"
    RANGE = "range"
    FORMULA = "formula"
    TO_BE_CONFIRMED = "to_be_confirmed"


class ResourceRequirement(DomainModel):
    requirement_id: str = Field(min_length=1, max_length=80)
    category: ResourceCategory
    item: str = Field(min_length=2, max_length=300)
    quantity_or_capacity: str = Field(min_length=2, max_length=500)
    estimate: str = Field(min_length=2, max_length=500)
    estimate_expression: EstimateExpression
    estimation_basis: str = Field(min_length=3, max_length=1000)
    needs_confirmation: bool
    priority: StrategyPriority
    linked_strategy_ids: list[str] = Field(min_length=1)


class RiskItem(DomainModel):
    risk: str = Field(min_length=3, max_length=1000)
    trigger: str = Field(min_length=3, max_length=1000)
    mitigation: str = Field(min_length=3, max_length=1500)
    owner_role: str = Field(min_length=2, max_length=200)
    monitoring_metric_ids: list[str] = Field(min_length=1)


class ResourceBudgetRiskSummary(DomainModel):
    summary_id: str = Field(min_length=1, max_length=80)
    has_confirmed_budget_ceiling: bool
    budget_ceiling: str | None = Field(default=None, max_length=500)
    requirements: list[ResourceRequirement] = Field(min_length=6)
    priority_order: list[str] = Field(min_length=1)
    trade_offs: list[str] = Field(min_length=1)
    excluded_scope: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(min_length=1)
    risks: list[RiskItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_resource_coverage_and_budget_expression(self) -> Self:
        required_categories = set(ResourceCategory)
        actual_categories = {requirement.category for requirement in self.requirements}
        if not required_categories <= actual_categories:
            raise ValueError(
                "resource summaries must cover personnel, channel, tool, content capacity, "
                "time, and budget"
            )

        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("resource requirement IDs must be unique")
        if len(self.priority_order) != len(set(self.priority_order)):
            raise ValueError("resource priority order must not contain duplicate IDs")
        if set(self.priority_order) != set(requirement_ids):
            raise ValueError("resource priority order must include every requirement exactly once")

        if self.has_confirmed_budget_ceiling:
            if not self.budget_ceiling:
                raise ValueError("confirmed budget summaries require a budget ceiling")
            return self

        if self.budget_ceiling is not None:
            raise ValueError("unconfirmed budget summaries cannot assert a budget ceiling")
        for requirement in self.requirements:
            if requirement.category is not ResourceCategory.BUDGET:
                continue
            if requirement.estimate_expression not in {
                EstimateExpression.RANGE,
                EstimateExpression.FORMULA,
                EstimateExpression.TO_BE_CONFIRMED,
            }:
                raise ValueError(
                    "unknown budgets must use a range, formula, or confirmation placeholder"
                )
            if not requirement.needs_confirmation:
                raise ValueError("unknown budget estimates must require confirmation")
        return self


class ReportDeliveryStatus(StrEnum):
    FORMAL = "formal"
    DIRECTIONAL_DRAFT = "directional_draft"
    FAILURE_EXPLANATION = "failure_explanation"


class OperationsReport(DomainModel):
    report_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=3, max_length=300)
    generated_at: datetime
    delivery_status: ReportDeliveryStatus
    executive_summary: str = Field(min_length=20, max_length=5000)
    brief: OperationsBrief
    scene_classification: SceneClassification
    diagnosis: Diagnosis
    audience_analysis: AudienceAnalysis
    case_mechanisms: list[CaseMechanism] = Field(min_length=1)
    key_claims: list[Claim] = Field(min_length=1)
    strategies: list[StrategyOption] = Field(min_length=1)
    actions: list[ActionItem] = Field(min_length=1)
    metrics: list[MetricDefinition] = Field(min_length=1)
    experiments: list[ExperimentPlan] = Field(min_length=1)
    resources_and_budget: list[ResourceBudgetItem] = Field(min_length=1)
    risks: list[RiskItem] = Field(min_length=1)
    assumptions: list[Claim] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    evidence_appendix: list[EvidenceRecord] = Field(min_length=1)
    decision_support_notice: str = Field(min_length=20, max_length=2000)
    automated_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_report_references_and_labels(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        if any(claim.claim_type is not ClaimType.HYPOTHESIS for claim in self.assumptions):
            raise ValueError("all report assumptions must use the hypothesis claim type")

        evidence_ids = {item.evidence_id for item in self.evidence_appendix}
        strategy_ids = {item.strategy_id for item in self.strategies}
        metric_ids = {item.metric_id for item in self.metrics}
        assumption_ids = {item.claim_id for item in self.assumptions}

        for claim in self.key_claims:
            if claim.claim_type is ClaimType.FACT and not set(claim.evidence_ids) <= evidence_ids:
                raise ValueError("report facts must reference evidence in the appendix")
        for strategy in self.strategies:
            if not set(strategy.evidence_ids) <= evidence_ids:
                raise ValueError("strategies cannot reference missing evidence")
            if not set(strategy.assumption_claim_ids) <= assumption_ids:
                raise ValueError("strategies cannot reference missing assumptions")
        if any(action.strategy_id not in strategy_ids for action in self.actions):
            raise ValueError("actions must reference an included strategy")
        for experiment in self.experiments:
            if not set(experiment.linked_strategy_ids) <= strategy_ids:
                raise ValueError("experiments must reference included strategies")
            if not set(experiment.primary_metric_ids) <= metric_ids:
                raise ValueError("experiments must reference included metrics")
            if experiment.hypothesis_claim_id not in assumption_ids:
                raise ValueError("experiments must reference an explicit hypothesis")
        return self
