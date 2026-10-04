"""Deterministic common/primary/auxiliary playbook composition."""

from typing import Any, Literal

from pydantic import Field

from ops_agent.domain.base import DomainModel
from ops_agent.domain.intake import OperationsScene, SceneClassification
from ops_agent.playbooks.loader import PlaybookRegistry
from ops_agent.playbooks.schema import (
    ClarifyingQuestion,
    DiagnosticDimension,
    PlaybookMetric,
    QualityRule,
    StrategySection,
)

CollectionName = Literal[
    "clarifying_questions",
    "diagnostic_dimensions",
    "strategy_sections",
    "required_metrics",
    "quality_rules",
]
MergeItem = (
    ClarifyingQuestion | DiagnosticDimension | StrategySection | PlaybookMetric | QualityRule
)


class PlaybookConflict(DomainModel):
    collection: CollectionName
    item_id: str
    winning_scene: OperationsScene
    losing_scene: OperationsScene
    retained_value: dict[str, Any]
    discarded_value: dict[str, Any]
    resolution: Literal["primary_scene_precedence", "auxiliary_order_precedence"]
    tradeoff: str = Field(min_length=10, max_length=1000)


class MergedPlaybook(DomainModel):
    primary_scene: OperationsScene
    secondary_scenes: list[OperationsScene]
    classification_was_user_corrected: bool
    selected_versions: dict[str, str]
    required_input_fields: list[str]
    recommended_input_fields: list[str]
    clarifying_questions: list[ClarifyingQuestion]
    diagnostic_dimensions: list[DiagnosticDimension]
    strategy_sections: list[StrategySection]
    required_metrics: list[PlaybookMetric]
    quality_rules: list[QualityRule]
    conflicts: list[PlaybookConflict]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _merge_collection(
    collection: CollectionName,
    core_items: list[MergeItem],
    primary_items: list[MergeItem],
    auxiliary_items: list[tuple[OperationsScene, list[MergeItem]]],
    primary_scene: OperationsScene,
) -> tuple[list[MergeItem], list[PlaybookConflict]]:
    merged = {item.id: item for item in core_items}
    source: dict[str, OperationsScene | Literal["core"]] = {item.id: "core" for item in core_items}
    for item in primary_items:
        merged[item.id] = item
        source[item.id] = primary_scene

    conflicts: list[PlaybookConflict] = []
    for auxiliary_scene, items in auxiliary_items:
        for item in items:
            existing = merged.get(item.id)
            if existing is None:
                merged[item.id] = item
                source[item.id] = auxiliary_scene
                continue
            if existing == item:
                continue
            existing_source = source[item.id]
            if not isinstance(existing_source, OperationsScene):
                merged[item.id] = item
                source[item.id] = auxiliary_scene
                continue
            resolution: Literal[
                "primary_scene_precedence", "auxiliary_order_precedence"
            ] = (
                "primary_scene_precedence"
                if existing_source == primary_scene
                else "auxiliary_order_precedence"
            )
            conflicts.append(
                PlaybookConflict(
                    collection=collection,
                    item_id=item.id,
                    winning_scene=existing_source,
                    losing_scene=auxiliary_scene,
                    retained_value=existing.model_dump(mode="json"),
                    discarded_value=item.model_dump(mode="json"),
                    resolution=resolution,
                    tradeoff=(
                        f"保留 {existing_source.value} 对 {collection}/{item.id} 的定义，"
                        f"未合并 {auxiliary_scene.value} 的冲突版本；报告必须披露这一取舍。"
                    ),
                )
            )
    return list(merged.values()), conflicts


def merge_playbooks(
    classification: SceneClassification,
    registry: PlaybookRegistry,
) -> MergedPlaybook:
    """Compose the core, primary, and auxiliaries with explicit conflict records."""
    primary = registry.for_scene(classification.primary_scene)
    auxiliaries = [
        (scene, registry.for_scene(scene)) for scene in classification.secondary_scenes
    ]

    required_inputs = _unique(
        registry.core.required_input_fields
        + primary.required_input_fields
        + [field for _, playbook in auxiliaries for field in playbook.required_input_fields]
    )
    recommended_inputs = _unique(
        registry.core.recommended_input_fields
        + primary.recommended_input_fields
        + [field for _, playbook in auxiliaries for field in playbook.recommended_input_fields]
    )
    recommended_inputs = [field for field in recommended_inputs if field not in required_inputs]

    collections: tuple[CollectionName, ...] = (
        "clarifying_questions",
        "diagnostic_dimensions",
        "strategy_sections",
        "required_metrics",
        "quality_rules",
    )
    merged_values: dict[CollectionName, list[MergeItem]] = {}
    conflicts: list[PlaybookConflict] = []
    for collection in collections:
        values, collection_conflicts = _merge_collection(
            collection=collection,
            core_items=getattr(registry.core, collection),
            primary_items=getattr(primary, collection),
            auxiliary_items=[
                (scene, getattr(playbook, collection)) for scene, playbook in auxiliaries
            ],
            primary_scene=classification.primary_scene,
        )
        merged_values[collection] = values
        conflicts.extend(collection_conflicts)

    selected_versions = {
        "core": registry.core.playbook_version,
        classification.primary_scene.value: primary.playbook_version,
        **{scene.value: playbook.playbook_version for scene, playbook in auxiliaries},
    }
    return MergedPlaybook(
        primary_scene=classification.primary_scene,
        secondary_scenes=classification.secondary_scenes,
        classification_was_user_corrected=classification.user_corrected,
        selected_versions=selected_versions,
        required_input_fields=required_inputs,
        recommended_input_fields=recommended_inputs,
        clarifying_questions=[
            item
            for item in merged_values["clarifying_questions"]
            if isinstance(item, ClarifyingQuestion)
        ],
        diagnostic_dimensions=[
            item
            for item in merged_values["diagnostic_dimensions"]
            if isinstance(item, DiagnosticDimension)
        ],
        strategy_sections=[
            item
            for item in merged_values["strategy_sections"]
            if isinstance(item, StrategySection)
        ],
        required_metrics=[
            item for item in merged_values["required_metrics"] if isinstance(item, PlaybookMetric)
        ],
        quality_rules=[
            item for item in merged_values["quality_rules"] if isinstance(item, QualityRule)
        ],
        conflicts=conflicts,
    )
