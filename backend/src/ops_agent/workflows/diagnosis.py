"""Operations diagnosis node for strategy planning."""

import json
from typing import NotRequired, TypedDict

from ops_agent.domain.intake import (
    BriefField,
    FieldStatus,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.domain.report import Diagnosis, GoalRelationship
from ops_agent.domain.research import ClaimType, EvidenceBundle, EvidenceCoverageResult
from ops_agent.providers.contracts import ModelMessage, ModelProvider, ModelRequest
from ops_agent.workflows.confirmation import ConfirmedBriefBaseline


class DiagnosisState(TypedDict):
    confirmed_baseline: ConfirmedBriefBaseline
    evidence_bundle: EvidenceBundle
    evidence_coverage: NotRequired[EvidenceCoverageResult | None]
    diagnosis: NotRequired[Diagnosis | None]


async def diagnose_operations(
    state: DiagnosisState,
    model: ModelProvider,
) -> DiagnosisState:
    """LangGraph-compatible node that writes a professional diagnosis."""
    baseline = state["confirmed_baseline"]
    diagnosis = await build_diagnosis(
        baseline.brief,
        baseline.classification,
        state["evidence_bundle"],
        model,
        evidence_coverage=state.get("evidence_coverage"),
    )
    return {**state, "diagnosis": diagnosis}


async def build_diagnosis(
    brief: OperationsBrief,
    classification: SceneClassification,
    evidence_bundle: EvidenceBundle,
    model: ModelProvider,
    *,
    evidence_coverage: EvidenceCoverageResult | None = None,
) -> Diagnosis:
    """Ask for a diagnosis draft, then enforce deterministic diagnosis floors."""
    response = await model.generate_structured(
        ModelRequest(
            purpose="diagnose_operations",
            messages=(
                ModelMessage(role="system", content=_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "confirmed_brief_fields": _confirmed_brief_payload(brief),
                            "classification": classification.model_dump(mode="json"),
                            "claims": [
                                claim.model_dump(mode="json")
                                for claim in evidence_bundle.claims
                            ],
                            "coverage": (
                                evidence_coverage.model_dump(mode="json")
                                if evidence_coverage is not None
                                else None
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ),
            max_output_tokens=3_000,
            temperature=0,
        ),
        Diagnosis,
    )
    return _reconcile_diagnosis(
        response.output,
        brief=brief,
        classification=classification,
        evidence_bundle=evidence_bundle,
        evidence_coverage=evidence_coverage,
    )


def _reconcile_diagnosis(
    diagnosis: Diagnosis,
    *,
    brief: OperationsBrief,
    classification: SceneClassification,
    evidence_bundle: EvidenceBundle,
    evidence_coverage: EvidenceCoverageResult | None,
) -> Diagnosis:
    relationships = [
        _decompose_goal_relationship(relationship, brief, classification)
        for relationship in diagnosis.goal_relationships
    ]
    supporting_claim_ids = _valid_supporting_claim_ids(diagnosis, evidence_bundle)
    constraints = diagnosis.constraints or _constraints_from_brief(brief)
    alternative_explanations = list(diagnosis.alternative_explanations)
    data_needed = list(diagnosis.data_needed)

    if _needs_data_explanations(brief, evidence_bundle, evidence_coverage):
        alternative_explanations = _unique(
            [*alternative_explanations, *_default_alternative_explanations(classification)]
        )
        data_needed = _unique([*data_needed, *_default_data_needed(brief, classification)])

    return diagnosis.model_copy(
        update={
            "business_stage": _field_text(brief.business_stage)
            or diagnosis.business_stage
            or "用户尚未确认业务阶段",
            "target_users": _field_text(brief.target_users)
            or diagnosis.target_users
            or "用户尚未确认目标用户",
            "goal_relationships": relationships,
            "supporting_claim_ids": supporting_claim_ids,
            "constraints": constraints,
            "alternative_explanations": alternative_explanations,
            "data_needed": data_needed,
        }
    )


def _decompose_goal_relationship(
    relationship: GoalRelationship,
    brief: OperationsBrief,
    classification: SceneClassification,
) -> GoalRelationship:
    goal = _field_text(brief.operation_goal) or relationship.operations_goal
    if not _is_result_goal(goal):
        return relationship
    if _looks_like_behavior(relationship.target_behavior, goal):
        return relationship
    return relationship.model_copy(
        update={"target_behavior": _default_target_behavior(brief, classification)}
    )


def _valid_supporting_claim_ids(
    diagnosis: Diagnosis,
    evidence_bundle: EvidenceBundle,
) -> list[str]:
    known_claim_ids = {claim.claim_id for claim in evidence_bundle.claims}
    valid = [claim_id for claim_id in diagnosis.supporting_claim_ids if claim_id in known_claim_ids]
    if valid:
        return valid
    if evidence_bundle.claims:
        return [evidence_bundle.claims[0].claim_id]
    raise ValueError("diagnosis requires at least one supporting claim")


def _needs_data_explanations(
    brief: OperationsBrief,
    evidence_bundle: EvidenceBundle,
    evidence_coverage: EvidenceCoverageResult | None,
) -> bool:
    if brief.current_baseline.status is not FieldStatus.CONFIRMED:
        return True
    if not any(claim.claim_type is ClaimType.FACT for claim in evidence_bundle.claims):
        return True
    return bool(evidence_coverage and evidence_coverage.status.value != "sufficient")


def _default_alternative_explanations(
    classification: SceneClassification,
) -> list[str]:
    return {
        OperationsScene.ACQUISITION: [
            "目标人群与当前渠道触达的人群不匹配，导致获客质量不足。",
            "价值主张或首个转化动作不清晰，用户理解成本高于激励收益。",
            "转化漏斗的关键步骤存在摩擦，需要用分步数据定位掉点。",
        ],
        OperationsScene.RETENTION: [
            "用户未在首周完成关键留存行为，后续召回难以弥补早期激活缺口。",
            "产品价值兑现周期长，用户在看到收益前已经流失。",
            "分层触达不足，不同活跃度用户收到同质化运营动作。",
        ],
        OperationsScene.CAMPAIGN: [
            "活动利益点不足以驱动目标人群行动，参与门槛或规则理解成本过高。",
            "预热、上线和收尾节奏不完整，导致流量峰值无法沉淀。",
            "资源排期与活动目标不匹配，需要缩小范围或延长周期。",
        ],
        OperationsScene.CONTENT: [
            "内容主题与目标用户当前任务不匹配，曝光不能转化为有效互动。",
            "内容供给节奏不稳定，难以形成用户预期和复访。",
            "分发渠道与转化路径脱节，需要明确内容后的下一步动作。",
        ],
    }[classification.primary_scene]


def _default_data_needed(
    brief: OperationsBrief,
    classification: SceneClassification,
) -> list[str]:
    common = [
        "当前核心指标基线和口径",
        "目标用户分群后的关键行为漏斗",
        "不同渠道或触点的转化与流失数据",
    ]
    scene_specific = {
        OperationsScene.ACQUISITION: ["新客来源、注册、首单或激活的分步转化率"],
        OperationsScene.RETENTION: ["按注册批次或行为分层的次日、7日、30日留存"],
        OperationsScene.CAMPAIGN: ["活动曝光、报名、参与、转化和复访的阶段数据"],
        OperationsScene.CONTENT: ["内容曝光、点击、互动、关注和转化路径数据"],
    }[classification.primary_scene]
    if brief.current_baseline.status is not FieldStatus.CONFIRMED:
        return [*common, *scene_specific]
    return [*common[1:], *scene_specific]


def _default_target_behavior(
    brief: OperationsBrief,
    classification: SceneClassification,
) -> str:
    goal = _field_text(brief.operation_goal) or ""
    if "首单" in goal:
        return "目标用户完成首单并留下可持续触达关系"
    return {
        OperationsScene.ACQUISITION: "目标用户完成注册、首个关键行为或首次付费",
        OperationsScene.RETENTION: "目标用户在关键周期内重复完成核心价值行为",
        OperationsScene.CAMPAIGN: "目标用户完成活动参与、分享或转化动作",
        OperationsScene.CONTENT: "目标用户完成内容互动并进入后续转化路径",
    }[classification.primary_scene]


def _constraints_from_brief(brief: OperationsBrief) -> list[str]:
    constraints = _field_list(brief.constraints)
    resource = _field_text(brief.budget_and_resources)
    if resource:
        constraints.append(resource)
    return constraints or ["当前约束信息有限，关键判断需通过数据或实验验证"]


def _confirmed_brief_payload(brief: OperationsBrief) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field_name in type(brief).model_fields:
        field = getattr(brief, field_name)
        if field.status is FieldStatus.CONFIRMED:
            payload[field_name] = field.model_dump(mode="json")
    return payload


def _field_text(field: BriefField[str]) -> str | None:
    if field.status is FieldStatus.CONFIRMED and isinstance(field.value, str):
        return field.value
    return None


def _field_list(field: BriefField[list[str]]) -> list[str]:
    if field.status is FieldStatus.CONFIRMED and isinstance(field.value, list):
        return [value for value in field.value if value.strip()]
    return []


def _is_result_goal(goal: str) -> bool:
    return any(signal in goal for signal in ("提升", "提高", "增长", "留存", "活跃", "转化"))


def _looks_like_behavior(target_behavior: str, goal: str) -> bool:
    if target_behavior.strip() == goal.strip():
        return False
    return any(signal in target_behavior for signal in ("完成", "行为", "下单", "参与", "复访"))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


_SYSTEM_PROMPT = "\n".join(
    (
        "你是专业运营诊断节点。先诊断，不生成完整策略。",
        "必须建立 business_goal -> operations_goal -> target_behavior -> metric_ids 的关系。",
        "如果用户只给出增长、留存、活跃或转化等结果目标，必须拆成可干预用户行为。",
        "缺少基线或证据不足时，列出多个可验证解释和所需数据，不要选择单一未经支持的原因。",
        "不得把未知字段、低可信来源或假设当作已经确认的事实。",
    )
)
