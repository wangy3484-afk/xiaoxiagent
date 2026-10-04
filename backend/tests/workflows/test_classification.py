"""Scene classification, correction, and Playbook completeness tests."""

import pytest
from ops_agent.domain.intake import (
    BriefField,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.playbooks.loader import load_default_registry
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.classification import (
    check_completeness,
    classify_scene,
    correct_scene_classification,
)


def _brief(goal: str, **values: object) -> OperationsBrief:
    payload: dict[str, object] = {
        "operation_goal": BriefField[str].from_user(goal, goal),
        **values,
    }
    return OperationsBrief.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("goal", "scene"),
    [
        ("提升合格新客增长", OperationsScene.ACQUISITION),
        ("提高新用户次月留存", OperationsScene.RETENTION),
        ("完成双十一会员活动", OperationsScene.CAMPAIGN),
        ("建立小红书内容矩阵", OperationsScene.CONTENT),
    ],
)
async def test_classifies_each_single_scene(
    goal: str,
    scene: OperationsScene,
) -> None:
    model = DeterministicModelProvider(
        {
            "classify_scene": {
                "primary_scene": scene.value,
                "rationale": [f"核心目标是{goal}"],
                "confidence": 0.9,
            }
        }
    )

    result = await classify_scene(_brief(goal), model)

    assert result.primary_scene is scene
    assert result.secondary_scenes == []
    assert result.rationale


@pytest.mark.asyncio
async def test_cross_scene_request_keeps_one_primary_and_auxiliaries() -> None:
    model = DeterministicModelProvider(
        {
            "classify_scene": {
                "primary_scene": "acquisition",
                "secondary_scenes": ["content", "campaign"],
                "rationale": ["新客增长是结果目标", "内容和活动是获客手段"],
                "confidence": 0.84,
            }
        }
    )

    result = await classify_scene(_brief("通过内容活动提升新客增长"), model)

    assert result.primary_scene is OperationsScene.ACQUISITION
    assert result.secondary_scenes == [
        OperationsScene.CONTENT,
        OperationsScene.CAMPAIGN,
    ]


def test_completeness_reports_core_and_retention_playbook_gaps() -> None:
    classification = _classification(OperationsScene.RETENTION)
    brief = _brief(
        "提高次月留存",
        target_users=BriefField[str].from_user("新注册用户", "新注册用户"),
        current_problem=BriefField[str].from_user("首周流失高", "首周流失高"),
        execution_period=BriefField[str].from_user("未来90天", "未来90天"),
        budget_and_resources=BriefField[str].from_user("2名运营", "2名运营"),
    )

    result = check_completeness(brief, classification, load_default_registry())

    gap_names = [gap.field for gap in result.required_gaps]
    assert result.ready_for_research is False
    assert "current_baseline" in gap_names
    assert "business_stage" in gap_names
    baseline_gap = next(gap for gap in result.required_gaps if gap.field == "current_baseline")
    assert "retention" in baseline_gap.required_by
    assert "retention_definition" in baseline_gap.question_ids


def test_user_can_correct_an_inaccurate_scene_classification() -> None:
    original = _classification(OperationsScene.ACQUISITION)

    corrected = correct_scene_classification(
        original,
        primary_scene=OperationsScene.RETENTION,
        secondary_scenes=[OperationsScene.CONTENT],
        user_reason="我的核心目标是提高已注册用户留存，内容只是触达手段",
    )

    assert corrected.primary_scene is OperationsScene.RETENTION
    assert corrected.secondary_scenes == [OperationsScene.CONTENT]
    assert corrected.user_corrected is True
    assert corrected.confidence == 1
    assert corrected.rationale[0].startswith("用户修正：")


def _classification(scene: OperationsScene) -> SceneClassification:
    return SceneClassification(
        primary_scene=scene,
        rationale=["测试分类依据"],
        confidence=0.8,
    )
