"""Tests for brief provenance and operations-scene classification."""

import pytest
from ops_agent.domain.intake import (
    BriefField,
    FieldSource,
    FieldStatus,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from pydantic import ValidationError


def _user_text(value: str) -> BriefField[str]:
    return BriefField[str].from_user(value, value)


def test_complete_brief_preserves_every_user_source() -> None:
    brief = OperationsBrief(
        business_context=_user_text("社区生鲜电商，处于区域扩张期"),
        current_problem=_user_text("新客首单转化偏低"),
        operation_goal=_user_text("提升合格新客首单转化"),
        target_users=_user_text("一二线城市的新注册家庭用户"),
        business_stage=_user_text("区域扩张期"),
        execution_period=_user_text("未来 90 天"),
        budget_and_resources=_user_text("20 万元，2 名运营"),
        existing_channels=BriefField[list[str]].from_user(
            ["微信社群", "应用商店"], "现有微信社群和应用商店自然量"
        ),
        current_baseline=_user_text("注册到首单转化率 8%"),
        constraints=BriefField[list[str]].from_user(
            ["不使用用户个人明细", "不自动投放"], "不得上传用户明细，不自动投放"
        ),
        preferred_benchmark_companies=BriefField[list[str]].from_user(
            ["京东", "淘宝"], "希望参考京东和淘宝"
        ),
    )

    assert brief.unknown_fields() == []
    assert brief.inferred_fields() == []
    assert brief.current_baseline.asserted_as_fact is True
    assert brief.existing_channels.source is FieldSource.USER_INPUT


def test_missing_fields_are_explicitly_unknown() -> None:
    brief = OperationsBrief(operation_goal=_user_text("提高次月留存"))

    assert "operation_goal" not in brief.unknown_fields()
    assert "target_users" in brief.unknown_fields()
    assert brief.current_baseline.value is None
    assert brief.current_baseline.status is FieldStatus.UNKNOWN


def test_cross_scene_classification_keeps_one_primary_scene() -> None:
    classification = SceneClassification(
        primary_scene=OperationsScene.ACQUISITION,
        secondary_scenes=[OperationsScene.CONTENT, OperationsScene.CAMPAIGN],
        rationale=["核心目标是新客增长", "内容和活动承担获客触点"],
        confidence=0.82,
        uncertainties=["尚未确认内容产能"],
    )

    assert classification.primary_scene is OperationsScene.ACQUISITION
    assert classification.secondary_scenes == [
        OperationsScene.CONTENT,
        OperationsScene.CAMPAIGN,
    ]


def test_inference_cannot_be_marked_as_confirmed_fact() -> None:
    with pytest.raises(ValidationError, match="system inference cannot be asserted as fact"):
        BriefField[str](
            value="可能处于成长期",
            status=FieldStatus.INFERRED,
            source=FieldSource.SYSTEM_INFERENCE,
            source_excerpt="根据增长目标推测",
            asserted_as_fact=True,
        )


def test_user_correction_is_confirmed_and_traceable() -> None:
    field = BriefField[str].from_correction("留存", "用户将主场景改为留存")

    assert field.source is FieldSource.USER_CORRECTION
    assert field.status is FieldStatus.CONFIRMED
    assert field.asserted_as_fact is True
