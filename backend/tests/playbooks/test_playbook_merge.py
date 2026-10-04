"""Tests for primary/auxiliary playbook selection and conflict handling."""

from ops_agent.domain.intake import OperationsScene, SceneClassification
from ops_agent.playbooks import load_default_registry, merge_playbooks
from ops_agent.playbooks.loader import PlaybookRegistry


def _classification(
    primary: OperationsScene,
    secondary: list[OperationsScene] | None = None,
    *,
    user_corrected: bool = False,
) -> SceneClassification:
    return SceneClassification(
        primary_scene=primary,
        secondary_scenes=secondary or [],
        rationale=["测试分类依据"],
        confidence=1 if user_corrected else 0.9,
        user_corrected=user_corrected,
    )


def test_single_scene_merges_core_and_primary_without_conflict() -> None:
    merged = merge_playbooks(
        _classification(OperationsScene.ACQUISITION),
        load_default_registry(),
    )

    metric_ids = {item.id for item in merged.required_metrics}
    assert "core_outcome_metric" in metric_ids
    assert "customer_acquisition_cost" in metric_ids
    assert merged.secondary_scenes == []
    assert merged.conflicts == []


def test_multi_scene_includes_auxiliary_specialist_rules() -> None:
    merged = merge_playbooks(
        _classification(
            OperationsScene.ACQUISITION,
            [OperationsScene.CONTENT, OperationsScene.CAMPAIGN],
        ),
        load_default_registry(),
    )

    strategy_ids = {item.id for item in merged.strategy_sections}
    assert "acquisition_channel_portfolio" in strategy_ids
    assert "content_operating_system" in strategy_ids
    assert "campaign_mechanism" in strategy_ids


def test_user_corrected_primary_scene_is_used_without_reclassification() -> None:
    merged = merge_playbooks(
        _classification(
            OperationsScene.RETENTION,
            [OperationsScene.CONTENT],
            user_corrected=True,
        ),
        load_default_registry(),
    )

    assert merged.primary_scene is OperationsScene.RETENTION
    assert merged.classification_was_user_corrected is True
    assert "retention" in merged.selected_versions


def test_primary_scene_wins_conflict_and_records_explicit_tradeoff() -> None:
    registry = load_default_registry()
    primary = registry.for_scene(OperationsScene.ACQUISITION)
    auxiliary = registry.for_scene(OperationsScene.CONTENT)
    conflicting_metric = auxiliary.required_metrics[0].model_copy(
        update={
            "id": primary.required_metrics[0].id,
            "name": "辅助场景的冲突指标定义",
        }
    )
    registry_with_conflict = PlaybookRegistry(
        core=registry.core,
        by_scene={
            **registry.by_scene,
            OperationsScene.CONTENT: auxiliary.model_copy(
                update={"required_metrics": [conflicting_metric]}
            ),
        },
    )

    merged = merge_playbooks(
        _classification(OperationsScene.ACQUISITION, [OperationsScene.CONTENT]),
        registry_with_conflict,
    )

    retained = {item.id: item for item in merged.required_metrics}
    conflict = next(item for item in merged.conflicts if item.collection == "required_metrics")
    assert retained[primary.required_metrics[0].id] == primary.required_metrics[0]
    assert conflict.winning_scene is OperationsScene.ACQUISITION
    assert conflict.losing_scene is OperationsScene.CONTENT
    assert conflict.resolution == "primary_scene_precedence"
    assert "报告必须披露" in conflict.tradeoff
