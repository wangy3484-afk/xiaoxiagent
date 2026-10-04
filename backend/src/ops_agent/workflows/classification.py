"""Scene classification and deterministic Playbook completeness checks."""

import json
from typing import Literal

from pydantic import Field

from ops_agent.domain.base import DomainModel
from ops_agent.domain.intake import (
    FieldStatus,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.playbooks.loader import PlaybookRegistry
from ops_agent.playbooks.merge import MergedPlaybook, merge_playbooks
from ops_agent.providers.contracts import ModelMessage, ModelProvider, ModelRequest


class BriefGap(DomainModel):
    field: str = Field(min_length=1)
    importance: Literal["required", "recommended"]
    required_by: list[str] = Field(min_length=1)
    question_ids: list[str] = Field(default_factory=list)


class BriefCompleteness(DomainModel):
    ready_for_research: bool
    required_gaps: list[BriefGap]
    recommended_gaps: list[BriefGap]
    merged_playbook: MergedPlaybook


async def classify_scene(
    brief: OperationsBrief,
    model: ModelProvider,
) -> SceneClassification:
    """Select one primary and optional auxiliary scenes with an explanation."""
    confirmed = {
        name: field.model_dump(mode="json")
        for name in type(brief).model_fields
        if (field := getattr(brief, name)).status is not FieldStatus.UNKNOWN
    }
    if not confirmed:
        raise ValueError("at least one supported brief field is required for classification")
    response = await model.generate_structured(
        ModelRequest(
            purpose="classify_scene",
            messages=(
                ModelMessage(role="system", content=_CLASSIFICATION_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(confirmed, ensure_ascii=False, sort_keys=True),
                ),
            ),
            max_output_tokens=1_000,
            temperature=0,
        ),
        SceneClassification,
    )
    return response.output


def check_completeness(
    brief: OperationsBrief,
    classification: SceneClassification,
    registry: PlaybookRegistry,
) -> BriefCompleteness:
    """Find required and recommended gaps from the selected Playbook bundle."""
    merged = merge_playbooks(classification, registry)
    required_gaps = _gaps(
        brief,
        fields=merged.required_input_fields,
        importance="required",
        classification=classification,
        registry=registry,
        merged=merged,
    )
    recommended_gaps = _gaps(
        brief,
        fields=merged.recommended_input_fields,
        importance="recommended",
        classification=classification,
        registry=registry,
        merged=merged,
    )
    return BriefCompleteness(
        ready_for_research=not required_gaps,
        required_gaps=required_gaps,
        recommended_gaps=recommended_gaps,
        merged_playbook=merged,
    )


def correct_scene_classification(
    classification: SceneClassification,
    *,
    primary_scene: OperationsScene,
    secondary_scenes: list[OperationsScene],
    user_reason: str,
) -> SceneClassification:
    """Apply an explicit user correction without preserving model uncertainty."""
    reason = user_reason.strip()
    if not reason:
        raise ValueError("scene correction requires a user reason")
    return SceneClassification(
        primary_scene=primary_scene,
        secondary_scenes=secondary_scenes,
        rationale=[f"用户修正：{reason}", *classification.rationale],
        confidence=1,
        uncertainties=[],
        user_corrected=True,
    )


def _gaps(
    brief: OperationsBrief,
    *,
    fields: list[str],
    importance: Literal["required", "recommended"],
    classification: SceneClassification,
    registry: PlaybookRegistry,
    merged: MergedPlaybook,
) -> list[BriefGap]:
    gaps: list[BriefGap] = []
    selected = [
        registry.core,
        registry.for_scene(classification.primary_scene),
        *(registry.for_scene(scene) for scene in classification.secondary_scenes),
    ]
    for field_name in fields:
        field = getattr(brief, field_name)
        if field.status is FieldStatus.CONFIRMED:
            continue
        required_by = [
            playbook.scene.value
            if isinstance(playbook.scene, OperationsScene)
            else playbook.scene
            for playbook in selected
            if field_name
            in (
                playbook.required_input_fields
                if importance == "required"
                else playbook.recommended_input_fields
            )
        ]
        question_ids = [
            question.id
            for question in merged.clarifying_questions
            if question.field == field_name
        ]
        gaps.append(
            BriefGap(
                field=field_name,
                importance=importance,
                required_by=required_by or [classification.primary_scene.value],
                question_ids=question_ids,
            )
        )
    return gaps


_CLASSIFICATION_PROMPT = "\n".join(
    (
        "你是运营场景分类器，只能从 acquisition、retention、campaign、content 中选择。",
        "primary_scene 必须对应用户最优先的结果目标；",
        "其他确实影响方案的方法域放入 secondary_scenes。",
        "rationale 必须指出简报中的目标或问题依据，不得把未知字段当作事实。",
        "confidence 表示分类把握，信息不足时降低置信度并在 uncertainties 中说明缺口。",
        "user_corrected 必须为 false。",
    )
)
