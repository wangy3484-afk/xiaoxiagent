"""Operations diagnosis workflow tests."""

from datetime import UTC, date, datetime

import pytest
from ops_agent.domain.intake import (
    BriefField,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.domain.research import (
    Claim,
    ClaimEvidenceLink,
    ClaimType,
    CredibilityAssessment,
    CredibilityLevel,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceSupportType,
    EvidenceVerificationStatus,
    PublicationDateStatus,
    SourceType,
)
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.diagnosis import build_diagnosis
from pydantic import HttpUrl


def _brief(*, with_baseline: bool) -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("社区团购小程序", "社区团购小程序"),
        operation_goal=BriefField[str].from_user(
            "提升新客首单转化", "提升新客首单转化"
        ),
        target_users=BriefField[str].from_user("新注册用户", "新注册用户"),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        budget_and_resources=BriefField[str].from_user("2名运营", "2名运营"),
        current_baseline=(
            BriefField[str].from_user("首单转化率8%", "首单转化率8%")
            if with_baseline
            else BriefField[str].unknown()
        ),
    )


def _classification() -> SceneClassification:
    return SceneClassification(
        primary_scene=OperationsScene.ACQUISITION,
        rationale=["核心目标是提升新客首单转化"],
        confidence=0.9,
    )


def _fact_bundle() -> EvidenceBundle:
    claim = Claim(
        claim_id="claim-1",
        text="官方材料确认上线了首单任务",
        claim_type=ClaimType.FACT,
        evidence_ids=["ev-1"],
        reasoning="原文直接支持。",
        verification_status=EvidenceVerificationStatus.VERIFIED,
    )
    evidence = EvidenceRecord(
        evidence_id="ev-1",
        title="官方活动规则",
        publisher="示例企业",
        source_type=SourceType.OFFICIAL_PRIMARY,
        url=HttpUrl("https://example.com/source"),
        publication_date=date(2026, 8, 1),
        publication_date_status=PublicationDateStatus.KNOWN,
        accessed_at=datetime(2026, 9, 30, tzinfo=UTC),
        supporting_excerpt="官方材料确认上线了首单任务。",
        context_summary="只证明动作，不证明效果。",
        supported_claim_ids=["claim-1"],
        credibility=CredibilityAssessment(
            level=CredibilityLevel.HIGH,
            rationale="官方材料可以确认实施动作。",
            independence_notes="效果仍需交叉验证。",
        ),
        verification_status=EvidenceVerificationStatus.VERIFIED,
        source_accessible=True,
        content_hash="a" * 64,
    )
    return EvidenceBundle(
        claims=[claim],
        evidence=[evidence],
        links=[
            ClaimEvidenceLink(
                claim_id=claim.claim_id,
                evidence_id=evidence.evidence_id,
                support_type=EvidenceSupportType.DIRECT,
                rationale="原文直接支持。",
            )
        ],
    )


def _hypothesis_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        claims=[
            Claim(
                claim_id="hyp-1",
                text="首单任务可能提升转化",
                claim_type=ClaimType.HYPOTHESIS,
                evidence_ids=[],
                reasoning="需要实验验证。",
                verification_status=EvidenceVerificationStatus.UNVERIFIED,
            )
        ],
        evidence=[],
        links=[],
    )


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "diagnose_operations": {
                "business_stage": "冷启动阶段",
                "target_users": "新注册用户",
                "goal_relationships": [
                    {
                        "business_goal": "提升订单规模",
                        "operations_goal": "提升新客首单转化",
                        "target_behavior": "提升新客首单转化",
                        "metric_ids": ["metric_new_first_order"],
                    }
                ],
                "behavior_path": ["触达", "理解权益", "完成首单"],
                "core_problem": "尚未定位首单转化低发生在哪个漏斗环节。",
                "supporting_claim_ids": ["claim-1"],
                "constraints": ["2名运营"],
                "priority_rationale": "优先定位首单漏斗掉点，再决定运营动作。",
                "alternative_explanations": [],
                "data_needed": [],
            }
        }
    )


@pytest.mark.asyncio
async def test_diagnosis_decomposes_result_goal_into_target_behavior() -> None:
    diagnosis = await build_diagnosis(
        _brief(with_baseline=True),
        _classification(),
        _fact_bundle(),
        _model(),
    )

    relationship = diagnosis.goal_relationships[0]
    assert relationship.operations_goal == "提升新客首单转化"
    assert relationship.target_behavior != relationship.operations_goal
    assert "完成首单" in relationship.target_behavior
    assert relationship.metric_ids == ["metric_new_first_order"]


@pytest.mark.asyncio
async def test_diagnosis_adds_verifiable_explanations_when_data_is_missing() -> None:
    diagnosis = await build_diagnosis(
        _brief(with_baseline=False),
        _classification(),
        _hypothesis_bundle(),
        _model(),
    )

    assert len(diagnosis.alternative_explanations) >= 2
    assert len(diagnosis.data_needed) >= 3
    assert any("基线" in item for item in diagnosis.data_needed)
    assert diagnosis.supporting_claim_ids == ["hyp-1"]
