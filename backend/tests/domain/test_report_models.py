"""Schema tests for diagnosis, actions, metrics, experiments, and reports."""

import re
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from ops_agent.artifacts import (
    ReportBranding,
    render_operations_report,
    render_operations_report_pdf,
    report_responsibility_notice,
)
from ops_agent.domain.intake import (
    BriefField,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.domain.report import (
    ActionItem,
    AudienceAnalysis,
    Diagnosis,
    ExperimentPlan,
    GoalRelationship,
    MetricDefinition,
    MetricTarget,
    MetricType,
    OperationsReport,
    ReportDeliveryStatus,
    ResourceBudgetItem,
    RiskItem,
    StrategyOption,
    StrategyPriority,
    TargetBasis,
)
from ops_agent.domain.research import (
    CaseMechanism,
    Claim,
    ClaimType,
    CredibilityAssessment,
    CredibilityLevel,
    EvidenceRecord,
    EvidenceVerificationStatus,
    PublicationDateStatus,
    SourceType,
)
from PIL import Image as PillowImage
from pydantic import ValidationError
from pypdf import PdfReader


def _brief() -> OperationsBrief:
    return OperationsBrief(
        operation_goal=BriefField[str].from_user("提高次月留存", "目标是提高次月留存"),
        target_users=BriefField[str].from_user("新注册商家", "目标用户是新注册商家"),
        current_problem=BriefField[str].from_user("首周关键行为完成率低", "首周激活不足"),
    )


def _fact() -> Claim:
    return Claim(
        claim_id="fact-1",
        text="官方材料确认上线了分层引导",
        claim_type=ClaimType.FACT,
        evidence_ids=["ev-1"],
        reasoning="官方材料直接陈述动作",
        verification_status=EvidenceVerificationStatus.VERIFIED,
    )


def _hypothesis() -> Claim:
    return Claim(
        claim_id="hyp-1",
        text="完成首个关键行为可能提高次月留存",
        claim_type=ClaimType.HYPOTHESIS,
        evidence_ids=[],
        reasoning="需要通过分群实验验证",
        verification_status=EvidenceVerificationStatus.UNVERIFIED,
    )


def _evidence() -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "evidence_id": "ev-1",
            "title": "官方产品说明",
            "publisher": "示例公司",
            "source_type": SourceType.OFFICIAL_PRIMARY,
            "url": "https://example.com/source",
            "publication_date": date(2025, 1, 1),
            "publication_date_status": PublicationDateStatus.KNOWN,
            "accessed_at": datetime(2026, 9, 29, tzinfo=UTC),
            "supporting_excerpt": "官方材料确认上线了分层引导。",
            "context_summary": "只证明动作已经实施，不单独证明效果。",
            "supported_claim_ids": ["fact-1"],
            "credibility": CredibilityAssessment(
                level=CredibilityLevel.HIGH,
                rationale="企业官方页面可以直接确认产品动作。",
                independence_notes="效果数据仍需独立来源核验。",
            ),
            "verification_status": EvidenceVerificationStatus.VERIFIED,
            "source_accessible": True,
            "content_hash": "b" * 64,
        }
    )


def _action_data() -> dict[str, object]:
    return {
        "action_id": "action-1",
        "strategy_id": "strategy-1",
        "phase": "0-30 天",
        "goal": "验证关键行为与留存的关系",
        "target_audience": "注册七天内未完成关键行为的商家",
        "action": "按行为完成度分组并提供差异化任务引导",
        "touchpoint": "产品内任务中心",
        "owner_role": "用户运营",
        "prerequisites": ["关键行为埋点可用"],
        "resources": ["1 名用户运营", "1 名前端开发"],
        "deliverable": "分层规则和任务引导实验",
        "timeline": "第 1-4 周",
        "acceptance_criteria": ["完成实验分流", "数据可按分群读取"],
    }


@pytest.mark.parametrize(
    "missing_field",
    [
        "goal",
        "target_audience",
        "touchpoint",
        "owner_role",
        "prerequisites",
        "resources",
        "deliverable",
        "timeline",
        "acceptance_criteria",
    ],
)
def test_action_item_rejects_any_missing_execution_loop_field(missing_field: str) -> None:
    data = _action_data()
    data.pop(missing_field)
    with pytest.raises(ValidationError):
        ActionItem.model_validate(data)


def test_metric_requires_definition_formula_and_hypothesis_without_baseline() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(
            {
                "metric_id": "metric-1",
                "name": "关键行为完成率",
                "metric_type": MetricType.PROCESS,
                "definition": "完成关键行为的目标用户占比",
                "data_source": "行为事件表",
                "observation_period": "每周",
                "decision_rule": "连续两周改善才进入扩大实验",
            }
        )

    with pytest.raises(ValidationError, match="must be labeled as hypotheses"):
        MetricDefinition(
            metric_id="metric-1",
            name="关键行为完成率",
            metric_type=MetricType.PROCESS,
            definition="完成关键行为的目标用户占比",
            formula="完成用户数 / 目标用户数",
            data_source="行为事件表",
            observation_period="每周",
            decision_rule="连续两周改善才进入扩大实验",
            target=MetricTarget(
                lower_bound=0.1,
                upper_bound=0.2,
                unit="相对提升",
                basis=TargetBasis.TO_BE_VALIDATED,
                rationale="当前缺少可靠基线，需要先实验",
                is_hypothesis=False,
            ),
        )


def _valid_report() -> OperationsReport:
    fact = _fact()
    hypothesis = _hypothesis()
    evidence = _evidence()
    strategy = StrategyOption(
        strategy_id="strategy-1",
        scene=OperationsScene.RETENTION,
        title="首周关键行为分层引导",
        target_segment="注册七天内未完成关键行为的商家",
        strategy_logic="先验证关键行为与留存关系，再对高潜分群提供递进任务引导。",
        evidence_ids=[evidence.evidence_id],
        assumption_claim_ids=[hypothesis.claim_id],
        applicability_conditions=["关键行为可被可靠记录"],
        scene_differences=["当前团队资源小于案例企业"],
        adaptations=["先在单一商家分群进行两周实验"],
        impact_path=["降低理解成本", "提高关键行为完成率", "观察次月留存"],
        non_copyable_factors=["案例企业的大规模销售团队"],
        risks=["过度触达导致用户反感"],
        priority=StrategyPriority.MUST,
    )
    metric = MetricDefinition(
        metric_id="metric-1",
        name="关键行为完成率",
        metric_type=MetricType.PROCESS,
        definition="完成关键行为的实验用户占比",
        formula="完成用户数 / 实验用户数",
        data_source="行为事件表",
        observation_period="每周，连续四周",
        decision_rule="实验组改善且风险指标不恶化时进入下一阶段",
        target=MetricTarget(
            lower_bound=0.05,
            upper_bound=0.15,
            unit="相对提升",
            basis=TargetBasis.TO_BE_VALIDATED,
            rationale="当前无可靠基线，以实验建立可行区间",
            is_hypothesis=True,
        ),
    )
    return OperationsReport(
        report_id="report-1",
        title="新注册商家留存运营方案",
        generated_at=datetime(2026, 9, 29, tzinfo=UTC),
        delivery_status=ReportDeliveryStatus.DIRECTIONAL_DRAFT,
        executive_summary="本方案优先验证首周关键行为与次月留存的关系，再决定是否扩大分层引导。",
        brief=_brief(),
        scene_classification=SceneClassification(
            primary_scene=OperationsScene.RETENTION,
            rationale=["核心目标是提高次月留存"],
            confidence=0.9,
        ),
        diagnosis=Diagnosis(
            business_stage="早期验证阶段",
            target_users="新注册商家",
            goal_relationships=[
                GoalRelationship(
                    business_goal="提高有效商家规模",
                    operations_goal="提高次月留存",
                    target_behavior="首周完成关键经营行为",
                    metric_ids=[metric.metric_id],
                )
            ],
            behavior_path=["注册", "理解价值", "完成关键行为", "持续经营"],
            core_problem="尚未确认关键行为与留存的关系，直接召回会掩盖激活问题。",
            supporting_claim_ids=[fact.claim_id, hypothesis.claim_id],
            constraints=["当前无可靠留存基线"],
            priority_rationale="先验证关键行为，能以最低成本区分产品理解和触达问题。",
            alternative_explanations=["产品价值表达不清", "目标用户不匹配"],
            data_needed=["分群次月留存", "关键行为完成时间"],
        ),
        audience_analysis=AudienceAnalysis(
            segments=["未完成关键行为", "已完成但未复访"],
            priority_segment="注册七天内未完成关键行为的商家",
            needs_and_barriers=["不理解首个经营动作", "缺少即时反馈"],
            behavioral_signals=["注册后七天无关键事件"],
        ),
        case_mechanisms=[
            CaseMechanism(
                case_id="case-1",
                company="示例公司",
                goal="促进新用户完成关键行为",
                audience="尚未激活的新用户",
                touchpoints=["产品内任务中心"],
                mechanism="按行为完成度提供递进任务",
                execution_conditions=["行为埋点可用"],
                observed_outcomes=[fact],
                evidence_ids=[evidence.evidence_id],
                transferable_elements=["行为分层"],
                non_transferable_elements=["大规模销售团队"],
            )
        ],
        key_claims=[fact, hypothesis],
        strategies=[strategy],
        actions=[ActionItem.model_validate(_action_data())],
        metrics=[metric],
        experiments=[
            ExperimentPlan(
                experiment_id="exp-1",
                hypothesis_claim_id=hypothesis.claim_id,
                linked_strategy_ids=[strategy.strategy_id],
                target_segment="注册七天内未完成关键行为的商家",
                design="随机分流实验组和对照组，仅实验组展示递进任务引导。",
                comparison="现有新手引导",
                duration="四周",
                primary_metric_ids=[metric.metric_id],
                success_criteria=["过程指标改善", "风险指标不恶化"],
                sample_size_method="根据当前流量先计算可检测效应，再决定实验周期",
                stop_conditions=["投诉率明显上升", "埋点异常"],
            )
        ],
        resources_and_budget=[
            ResourceBudgetItem(
                item="实验开发与运营",
                estimate="1 名前端开发与 1 名用户运营，工期待排期确认",
                estimation_basis="依据最小实验范围估算",
                needs_confirmation=True,
            )
        ],
        risks=[
            RiskItem(
                risk="高频引导造成反感",
                trigger="关闭引导或投诉率上升",
                mitigation="设置频控并保留退出入口",
                owner_role="用户运营",
                monitoring_metric_ids=[metric.metric_id],
            )
        ],
        assumptions=[hypothesis],
        limitations=["当前缺少可靠留存基线，目标区间仅用于实验"],
        evidence_appendix=[evidence],
        decision_support_notice="本报告仅用于运营决策支持，目标和资源估算必须结合实际数据验证，最终执行由业务负责人决定。",
    )


def test_complete_report_contains_all_required_sections() -> None:
    report = _valid_report()

    assert report.actions[0].acceptance_criteria
    assert report.metrics[0].formula
    assert report.assumptions[0].claim_type is ClaimType.HYPOTHESIS
    assert report.automated_execution_allowed is False


def test_report_rejects_non_hypothesis_in_assumption_section() -> None:
    data = _valid_report().model_dump()
    data["assumptions"] = [_fact().model_dump()]

    with pytest.raises(ValidationError, match="assumptions must use the hypothesis"):
        OperationsReport.model_validate(data)


def test_report_rejects_missing_required_chapter() -> None:
    data = _valid_report().model_dump()
    data.pop("resources_and_budget")

    with pytest.raises(ValidationError):
        OperationsReport.model_validate(data)


def test_report_rendering_is_deterministic_and_citations_are_consistent() -> None:
    report = _valid_report()

    first = render_operations_report(report)
    second = render_operations_report(report)

    assert first == second
    assert first.markdown.count("[E1](#evidence-e1)") == 3
    assert '<a id="evidence-e1"></a>\\[E1\\]' in first.markdown
    assert first.html.count('href="#evidence-e1">[E1]</a>') == 3
    assert 'id="evidence-e1">[E1]</span>' in first.html
    assert "<script>" not in first.html
    assert sha256(first.markdown.encode()).hexdigest() == (
        "01681f9298f5f63ba9b515745c89f726acfee79e76eaa4eb18e4957f34d25849"
    )
    assert sha256(first.html.encode()).hexdigest() == (
        "360f350491620c82152d484340370a8a6ac12ed1c432bf0086e337f23fda527b"
    )


def test_report_rendering_escapes_untrusted_content() -> None:
    report = _valid_report().model_copy(
        update={"title": "运营方案 <script>alert('x')</script>"}
    )

    rendered = render_operations_report(report)

    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_pdf_rendering_embeds_chinese_text_links_and_page_furniture() -> None:
    first = render_operations_report_pdf(_valid_report())
    second = render_operations_report_pdf(_valid_report())

    assert first == second
    assert first.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(first))
    assert len(reader.pages) >= 2
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "新注册商家留存运营方案" in extracted
    assert "质量说明与局限" in extracted
    assert "证据附录" in extracted
    assert "第 1 页" in extracted
    annotations = [
        annotation
        for page in reader.pages
        for annotation in (page.get("/Annots") or [])
    ]
    assert annotations


@pytest.mark.parametrize(
    ("delivery_status", "status_text"),
    [
        (ReportDeliveryStatus.FORMAL, "正式报告已通过当前质量门槛"),
        (ReportDeliveryStatus.DIRECTIONAL_DRAFT, "方向性草案仍有未确认输入或证据局限"),
    ],
)
def test_all_export_formats_include_responsibility_boundaries(
    delivery_status: ReportDeliveryStatus,
    status_text: str,
) -> None:
    report = _valid_report().model_copy(update={"delivery_status": delivery_status})
    notice = report_responsibility_notice(report)
    rendered = render_operations_report(report)
    pdf_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(render_operations_report_pdf(report))).pages
    )

    for content in (notice, rendered.markdown, rendered.html, pdf_text):
        assert status_text in content
        assert "仅用于运营决策支持" in content
        assert "适用条件" in content
        assert "结合实际数据验证" in content
        assert not any(term in content for term in ("保证实现", "必然实现", "承诺达到"))


def test_branding_changes_identity_without_changing_report_structure(
    tmp_path: Path,
) -> None:
    logo_path = tmp_path / "brand-logo.png"
    PillowImage.new("RGB", (180, 48), color=(26, 83, 68)).save(logo_path)
    report = _valid_report()
    branding = ReportBranding(
        title="示例公司运营中心",
        header_text="内部运营决策支持报告",
        logo_path=logo_path,
        logo_alt="示例公司",
    )

    plain = render_operations_report(report)
    branded = render_operations_report(report, branding=branding)
    branded_pdf = render_operations_report_pdf(report, branding=branding)
    branded_pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(branded_pdf)).pages
    )

    html_heading_ids = re.compile(r'<h[23] id="([^"]+)">')
    markdown_anchor_ids = re.compile(r'<a id="([^"]+)"></a>')
    assert html_heading_ids.findall(branded.html) == html_heading_ids.findall(plain.html)
    assert markdown_anchor_ids.findall(branded.markdown) == markdown_anchor_ids.findall(
        plain.markdown
    )
    assert branded.html.count("<table>") == plain.html.count("<table>")
    assert branded.markdown.count("| ---") == plain.markdown.count("| ---")
    assert "示例公司运营中心｜新注册商家留存运营方案" in branded.html
    assert "内部运营决策支持报告" in branded.markdown
    assert "data:image/png;base64," in branded.html
    assert "data:image/png;base64," in branded.markdown
    assert b"/Subtype /Image" in branded_pdf
    assert "示例公司运营中心｜新注册商家留存运营方案" in branded_pdf_text
    assert "内部运营决策支持报告" in branded_pdf_text
    section_titles = [
        "执行摘要",
        "需求简报",
        "问题诊断",
        "策略方案",
        "执行计划",
        "指标体系",
        "证据附录",
    ]
    positions = [branded_pdf_text.index(title) for title in section_titles]
    assert positions == sorted(positions)
