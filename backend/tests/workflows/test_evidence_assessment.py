"""Evidence credibility, freshness, and adaptation assessment tests."""

from datetime import UTC, date, datetime

from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.domain.research import (
    AdaptationDimensionName,
    CredibilityLevel,
    FreshnessLevel,
    SourceType,
)
from ops_agent.workflows.research import (
    CollectedResearchSource,
    assess_collected_sources,
)
from pydantic import HttpUrl


def _brief() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user(
            "社区团购小程序", "社区团购小程序"
        ),
        operation_goal=BriefField[str].from_user(
            "提升新客首单转化", "提升新客首单转化"
        ),
        target_users=BriefField[str].from_user(
            "三四线城市新注册用户", "三四线城市新注册用户"
        ),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        budget_and_resources=BriefField[str].from_user(
            "2名运营，预算有限", "2名运营，预算有限"
        ),
        existing_channels=BriefField[list[str]].from_user(
            ["社群", "小红书"], "社群、小红书"
        ),
    )


def _source(
    source_id: str,
    *,
    publisher: str,
    title: str,
    url: str,
    text: str,
    publication_date: date | None,
    content_hash: str,
) -> CollectedResearchSource:
    parsed_url = HttpUrl(url)
    return CollectedResearchSource(
        source_id=source_id,
        query_id="q1",
        query="社区团购 新客首单转化 案例",
        search_rank=1,
        search_title=title,
        search_snippet=text[:120],
        requested_url=parsed_url,
        canonical_url=parsed_url,
        title=title,
        publisher=publisher,
        publication_date=publication_date,
        text=text,
        content_hash=content_hash,
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


def test_assesses_source_type_freshness_and_resource_fit() -> None:
    sources = [
        _source(
            "src-official",
            publisher="淘宝官方规则中心",
            title="淘宝官方新客首单转化活动规则公告",
            url="https://rule.taobao.com/case",
            text=(
                "淘宝官方公告说明，新客首单转化活动依赖全国流量池、"
                "亿级补贴和平台级资源。"
            ),
            publication_date=date(2026, 8, 1),
            content_hash="a" * 64,
        ),
        _source(
            "src-research",
            publisher="QuestMobile研究院",
            title="社区团购冷启动用户转化研究报告",
            url="https://example.com/research",
            text="研究报告分析社区团购小程序在冷启动阶段通过社群提升新客首单转化。",
            publication_date=date(2025, 9, 1),
            content_hash="b" * 64,
        ),
        _source(
            "src-blog",
            publisher="个人博客",
            title="我理解的小红书拉新技巧",
            url="https://example.com/blog",
            text="这是一篇二手经验总结，提到小红书内容可以引导新客。",
            publication_date=None,
            content_hash="c" * 64,
        ),
    ]

    assessments = assess_collected_sources(
        sources,
        _brief(),
        reference_date=date(2026, 9, 30),
    )

    assert [item.source_type for item in assessments] == [
        SourceType.OFFICIAL_PRIMARY,
        SourceType.TRUSTED_THIRD_PARTY,
        SourceType.GENERAL_SECONDARY,
    ]
    assert [item.credibility.level for item in assessments] == [
        CredibilityLevel.HIGH,
        CredibilityLevel.MEDIUM,
        CredibilityLevel.LOW,
    ]
    assert assessments[0].freshness.level is FreshnessLevel.CURRENT
    assert assessments[2].freshness.level is FreshnessLevel.UNKNOWN
    assert all(len(item.adaptation) == len(AdaptationDimensionName) for item in assessments)

    resource_fit = next(
        item
        for item in assessments[0].adaptation
        if item.dimension is AdaptationDimensionName.RESOURCE_SCALE
    )
    assert resource_fit.score == 1
    assert "资源" in resource_fit.rationale


def test_evidence_assessment_covers_all_adaptation_dimensions() -> None:
    assessment = assess_collected_sources(
        [
            _source(
                "src-complete",
                publisher="QuestMobile研究院",
                title="社区团购新客首单转化研究报告",
                url="https://example.com/complete",
                text=(
                    "社区团购小程序在冷启动阶段面向三四线城市新注册用户，"
                    "通过社群和小红书提升新客首单转化。"
                ),
                publication_date=date(2026, 1, 1),
                content_hash="d" * 64,
            )
        ],
        _brief(),
        reference_date=date(2026, 9, 30),
    )[0]

    assert {item.dimension for item in assessment.adaptation} == set(
        AdaptationDimensionName
    )
