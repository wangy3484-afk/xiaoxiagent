"""Schema tests for research plans, evidence records, and claim links."""

from datetime import UTC, date, datetime

import pytest
from ops_agent.domain.research import (
    CaseMechanism,
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
    ResearchBudget,
    ResearchPlan,
    ResearchQuery,
    ResearchQueryKind,
    SourceType,
)
from pydantic import ValidationError


def _evidence_data() -> dict[str, object]:
    return {
        "evidence_id": "ev-001",
        "title": "企业官方运营说明",
        "publisher": "示例企业",
        "source_type": SourceType.OFFICIAL_PRIMARY,
        "url": "https://example.com/case",
        "publication_date": date(2025, 8, 1),
        "publication_date_status": PublicationDateStatus.KNOWN,
        "accessed_at": datetime(2026, 9, 29, tzinfo=UTC),
        "supporting_excerpt": "该企业说明其上线了分层触达机制。",
        "context_summary": "来源证明实施动作，不单独证明业务效果。",
        "supported_claim_ids": ["claim-001"],
        "credibility": CredibilityAssessment(
            level=CredibilityLevel.HIGH,
            rationale="企业官方页面可直接确认机制已经上线。",
            independence_notes="属于企业自述，效果仍需独立来源交叉核验。",
        ),
        "verification_status": EvidenceVerificationStatus.VERIFIED,
        "source_accessible": True,
        "content_hash": "a" * 64,
    }


def _fact_claim() -> Claim:
    return Claim(
        claim_id="claim-001",
        text="该企业上线了分层触达机制",
        claim_type=ClaimType.FACT,
        evidence_ids=["ev-001"],
        reasoning="官方页面直接陈述了上线动作",
        verification_status=EvidenceVerificationStatus.VERIFIED,
    )


def test_research_plan_covers_named_and_structurally_similar_cases() -> None:
    plan = ResearchPlan(
        topics=["新客首单转化机制"],
        named_companies=["京东"],
        similarity_dimensions=["目标", "业务阶段", "渠道"],
        queries=[
            ResearchQuery(
                query_id="q1",
                query="京东 新客 首单 转化 官方",
                purpose="核验指定企业动作",
                kind=ResearchQueryKind.NAMED_COMPANY,
                target_company="京东",
                expected_evidence=["官方规则", "机制说明"],
            ),
            ResearchQuery(
                query_id="q2",
                query="社区零售 新客 首单 转化 案例",
                purpose="寻找结构相似案例",
                kind=ResearchQueryKind.STRUCTURALLY_SIMILAR,
                expected_evidence=["相似业务阶段案例"],
            ),
        ],
        stop_conditions=["达到三个独立有效来源", "查询预算耗尽"],
        budget=ResearchBudget(max_queries=8, max_pages=24, max_seconds=300),
    )

    assert len(plan.queries) == 2


@pytest.mark.parametrize(
    "missing_field",
    ["publisher", "accessed_at", "supported_claim_ids", "credibility"],
)
def test_verified_evidence_rejects_missing_traceability_fields(missing_field: str) -> None:
    data = _evidence_data()
    data.pop(missing_field)

    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate(data)


def test_unknown_publication_date_does_not_allow_a_guessed_date() -> None:
    data = _evidence_data()
    data["publication_date_status"] = PublicationDateStatus.UNKNOWN

    with pytest.raises(ValidationError, match="cannot contain a guessed date"):
        EvidenceRecord.model_validate(data)

    data["publication_date"] = None
    evidence = EvidenceRecord.model_validate(data)
    assert evidence.publication_date is None


def test_fact_claim_requires_verified_evidence_reference() -> None:
    with pytest.raises(ValidationError, match="fact claims require evidence"):
        Claim(
            claim_id="claim-no-source",
            text="活动带来了增长",
            claim_type=ClaimType.FACT,
            evidence_ids=[],
            reasoning="没有可核验证据",
            verification_status=EvidenceVerificationStatus.UNVERIFIED,
        )


def test_claim_evidence_bundle_and_case_mechanism_are_traceable() -> None:
    claim = _fact_claim()
    evidence = EvidenceRecord.model_validate(_evidence_data())
    link = ClaimEvidenceLink(
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        support_type=EvidenceSupportType.DIRECT,
        rationale="原文直接确认上线动作",
    )
    bundle = EvidenceBundle(claims=[claim], evidence=[evidence], links=[link])
    mechanism = CaseMechanism(
        case_id="case-001",
        company="示例企业",
        goal="提高新用户首周激活",
        audience="完成注册但未完成关键行为的新用户",
        touchpoints=["站内消息", "新手任务页"],
        mechanism="根据关键行为完成度分层触达下一步任务",
        incentive="完成任务后获得非现金权益",
        execution_conditions=["具备事件埋点", "具备分层触达能力"],
        observed_outcomes=[claim],
        evidence_ids=[evidence.evidence_id],
        transferable_elements=["按行为分层", "逐步降低操作门槛"],
        non_transferable_elements=["头部平台的自然流量规模"],
    )

    assert bundle.links[0].support_type is EvidenceSupportType.DIRECT
    assert mechanism.evidence_ids == ["ev-001"]
