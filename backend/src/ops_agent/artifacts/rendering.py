"""Deterministic HTML and Markdown rendering for structured operations reports."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import Literal

from ops_agent.artifacts.branding import ReportBranding
from ops_agent.domain.intake import FieldSource, FieldStatus
from ops_agent.domain.report import MetricDefinition, OperationsReport, ReportDeliveryStatus
from ops_agent.domain.research import Claim, ClaimType, EvidenceVerificationStatus

_CLAIM_LABELS = {
    ClaimType.FACT: "事实",
    ClaimType.INFERENCE: "推断",
    ClaimType.RECOMMENDATION: "建议",
    ClaimType.HYPOTHESIS: "假设",
}
_DELIVERY_LABELS = {
    ReportDeliveryStatus.FORMAL: "正式报告",
    ReportDeliveryStatus.DIRECTIONAL_DRAFT: "方向性草案",
    ReportDeliveryStatus.FAILURE_EXPLANATION: "失败说明",
}
_FIELD_STATUS_LABELS = {
    FieldStatus.CONFIRMED: "已确认",
    FieldStatus.INFERRED: "待确认推断",
    FieldStatus.UNKNOWN: "未提供",
}
_FIELD_SOURCE_LABELS = {
    FieldSource.USER_INPUT: "用户输入",
    FieldSource.USER_CORRECTION: "用户修正",
    FieldSource.SYSTEM_INFERENCE: "系统推断",
    FieldSource.UNKNOWN: "未知",
}
_VERIFICATION_LABELS = {
    EvidenceVerificationStatus.VERIFIED: "已核验",
    EvidenceVerificationStatus.UNVERIFIED: "未核验",
    EvidenceVerificationStatus.CONFLICTED: "存在冲突",
}
_BRIEF_LABELS = {
    "business_context": "业务背景",
    "current_problem": "当前问题",
    "operation_goal": "运营目标",
    "target_users": "目标用户",
    "business_stage": "业务阶段",
    "execution_period": "执行周期",
    "budget_and_resources": "预算与资源",
    "existing_channels": "现有渠道",
    "current_baseline": "当前基线",
    "constraints": "约束条件",
    "preferred_benchmark_companies": "优先参考公司",
}


@dataclass(frozen=True, slots=True)
class RenderedReport:
    """Both deterministic representations of one report version."""

    html: str
    markdown: str


@dataclass(frozen=True, slots=True)
class _Text:
    value: str
    citations: tuple[str, ...] = ()
    href: str | None = None
    anchor: str | None = None


@dataclass(frozen=True, slots=True)
class _Heading:
    level: int
    title: str
    anchor: str


@dataclass(frozen=True, slots=True)
class _Paragraph:
    content: _Text
    role: Literal["normal", "notice", "quality"] = "normal"


@dataclass(frozen=True, slots=True)
class _BulletList:
    items: tuple[_Text, ...]


@dataclass(frozen=True, slots=True)
class _Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[_Text, ...], ...]


type _Block = _Heading | _Paragraph | _BulletList | _Table


def render_operations_report(
    report: OperationsReport,
    *,
    branding: ReportBranding | None = None,
) -> RenderedReport:
    """Render a report with stable section order and citation numbering."""

    blocks = _build_document(report)
    return RenderedReport(
        html=_render_html(report, blocks, branding),
        markdown=_render_markdown(report, blocks, branding),
    )


def render_operations_report_html(
    report: OperationsReport,
    *,
    branding: ReportBranding | None = None,
) -> str:
    """Render a standalone, accessible HTML document."""

    return render_operations_report(report, branding=branding).html


def render_operations_report_markdown(
    report: OperationsReport,
    *,
    branding: ReportBranding | None = None,
) -> str:
    """Render portable Markdown with stable tables and citation anchors."""

    return render_operations_report(report, branding=branding).markdown


def report_responsibility_notice(report: OperationsReport) -> str:
    """Return delivery-status-specific, deterministic decision boundaries."""

    if report.delivery_status is ReportDeliveryStatus.FORMAL:
        status_notice = (
            "正式报告已通过当前质量门槛，但结论仍受证据时效、场景差异与数据边界约束。"
        )
    elif report.delivery_status is ReportDeliveryStatus.DIRECTIONAL_DRAFT:
        status_notice = (
            "方向性草案仍有未确认输入或证据局限，只可用于讨论和小范围验证，"
            "不应直接用于规模化执行。"
        )
    else:
        status_notice = "当前输出为失败说明，不包含可执行的运营方案。"
    return (
        f"{status_notice}本报告仅用于运营决策支持；所有策略仅在文中列明的适用条件"
        "成立时使用。效果预测、指标目标与资源估算必须由业务负责人结合实际数据验证，"
        "最终执行和业务决策由用户负责。"
    )


def _text(
    value: object,
    *,
    citations: tuple[str, ...] = (),
    href: str | None = None,
    anchor: str | None = None,
) -> _Text:
    if isinstance(value, bool):
        rendered = "是" if value else "否"
    elif value is None:
        rendered = "未提供"
    elif isinstance(value, list | tuple):
        rendered = "；".join(str(item) for item in value) if value else "无"
    else:
        rendered = str(value)
    return _Text(rendered, citations=citations, href=href, anchor=anchor)


def _citation_labels(
    evidence_ids: list[str], citation_by_evidence_id: dict[str, str]
) -> tuple[str, ...]:
    return tuple(
        citation_by_evidence_id[evidence_id]
        for evidence_id in evidence_ids
        if evidence_id in citation_by_evidence_id
    )


def _build_document(report: OperationsReport) -> tuple[_Block, ...]:
    citation_by_evidence_id = {
        item.evidence_id: f"E{index}"
        for index, item in enumerate(report.evidence_appendix, start=1)
    }
    blocks: list[_Block] = [
        _Paragraph(
            _text(
                f"{_DELIVERY_LABELS[report.delivery_status]} · "
                f"生成时间 {report.generated_at.isoformat()} · 报告 ID {report.report_id}"
            ),
            role="quality",
        ),
        _Paragraph(_text(report_responsibility_notice(report)), role="notice"),
        _Heading(2, "执行摘要", "executive-summary"),
        _Paragraph(_text(report.executive_summary)),
        _Heading(2, "需求简报", "brief"),
    ]

    brief_rows: list[tuple[_Text, ...]] = []
    for field_name in type(report.brief).model_fields:
        field = getattr(report.brief, field_name)
        brief_rows.append(
            (
                _text(_BRIEF_LABELS[field_name]),
                _text(field.value),
                _text(_FIELD_STATUS_LABELS[field.status]),
                _text(_FIELD_SOURCE_LABELS[field.source]),
            )
        )
    blocks.extend(
        [
            _Table(("字段", "内容", "状态", "来源"), tuple(brief_rows)),
            _Heading(2, "场景判断与目标人群", "scene-and-audience"),
            _Table(
                ("项目", "结论"),
                (
                    (_text("主场景"), _text(report.scene_classification.primary_scene.value)),
                    (
                        _text("辅助场景"),
                        _text(
                            [scene.value for scene in report.scene_classification.secondary_scenes]
                        ),
                    ),
                    (
                        _text("判断置信度"),
                        _text(f"{report.scene_classification.confidence:.0%}"),
                    ),
                    (_text("判断依据"), _text(report.scene_classification.rationale)),
                    (_text("不确定项"), _text(report.scene_classification.uncertainties)),
                    (_text("优先人群"), _text(report.audience_analysis.priority_segment)),
                    (_text("人群分层"), _text(report.audience_analysis.segments)),
                    (_text("需求与障碍"), _text(report.audience_analysis.needs_and_barriers)),
                    (_text("行为信号"), _text(report.audience_analysis.behavioral_signals)),
                ),
            ),
            _Heading(2, "问题诊断", "diagnosis"),
            _Paragraph(_text(report.diagnosis.core_problem)),
            _Table(
                ("业务目标", "运营目标", "目标行为", "指标"),
                tuple(
                    (
                        _text(item.business_goal),
                        _text(item.operations_goal),
                        _text(item.target_behavior),
                        _text(item.metric_ids),
                    )
                    for item in report.diagnosis.goal_relationships
                ),
            ),
            _Table(
                ("诊断维度", "内容"),
                (
                    (_text("业务阶段"), _text(report.diagnosis.business_stage)),
                    (_text("目标用户"), _text(report.diagnosis.target_users)),
                    (_text("行为路径"), _text(" → ".join(report.diagnosis.behavior_path))),
                    (_text("约束"), _text(report.diagnosis.constraints)),
                    (_text("优先理由"), _text(report.diagnosis.priority_rationale)),
                    (_text("替代解释"), _text(report.diagnosis.alternative_explanations)),
                    (_text("待补数据"), _text(report.diagnosis.data_needed)),
                ),
            ),
            _Heading(2, "参考案例机制", "case-mechanisms"),
            _Table(
                ("公司", "目标/人群", "机制", "可迁移", "不可照搬", "证据"),
                tuple(
                    (
                        _text(case.company),
                        _text(f"{case.goal}；{case.audience}"),
                        _text(
                            f"触点：{'、'.join(case.touchpoints)}；{case.mechanism}；"
                            f"条件：{'、'.join(case.execution_conditions)}"
                        ),
                        _text(case.transferable_elements),
                        _text(case.non_transferable_elements),
                        _text(
                            "来源",
                            citations=_citation_labels(
                                case.evidence_ids, citation_by_evidence_id
                            ),
                        ),
                    )
                    for case in report.case_mechanisms
                ),
            ),
            _Heading(2, "关键判断", "key-claims"),
            _claim_table(report.key_claims, citation_by_evidence_id),
            _Heading(2, "策略方案", "strategies"),
        ]
    )

    for index, strategy in enumerate(report.strategies, start=1):
        blocks.extend(
            [
                _Heading(3, f"{index}. {strategy.title}", f"strategy-{index}"),
                _Table(
                    ("维度", "内容"),
                    (
                        (_text("优先级"), _text(strategy.priority.value)),
                        (_text("目标分群"), _text(strategy.target_segment)),
                        (
                            _text("策略逻辑"),
                            _text(
                                strategy.strategy_logic,
                                citations=_citation_labels(
                                    strategy.evidence_ids, citation_by_evidence_id
                                ),
                            ),
                        ),
                        (_text("适用条件"), _text(strategy.applicability_conditions)),
                        (_text("场景差异"), _text(strategy.scene_differences)),
                        (_text("本地化调整"), _text(strategy.adaptations)),
                        (_text("影响路径"), _text(" → ".join(strategy.impact_path))),
                        (_text("不可复制因素"), _text(strategy.non_copyable_factors)),
                        (_text("风险"), _text(strategy.risks)),
                        (_text("依赖假设"), _text(strategy.assumption_claim_ids)),
                    ),
                ),
            ]
        )

    blocks.extend(
        [
            _Heading(2, "执行计划", "action-plan"),
            _Table(
                ("阶段/周期", "目标与人群", "动作与触点", "负责人/资源", "交付与验收"),
                tuple(
                    (
                        _text(f"{action.phase}；{action.timeline}"),
                        _text(f"{action.goal}；{action.target_audience}"),
                        _text(f"{action.action}；触点：{action.touchpoint}"),
                        _text(
                            f"{action.owner_role}；前置：{'、'.join(action.prerequisites)}；"
                            f"资源：{'、'.join(action.resources)}"
                        ),
                        _text(
                            f"{action.deliverable}；验收："
                            f"{'、'.join(action.acceptance_criteria)}"
                        ),
                    )
                    for action in report.actions
                ),
            ),
            _Heading(2, "指标体系", "metrics"),
            _Table(
                ("指标/类型", "定义与公式", "数据与周期", "目标", "决策规则"),
                tuple(
                    (
                        _text(f"{metric.name}（{metric.metric_type.value}）"),
                        _text(f"{metric.definition}；公式：{metric.formula}"),
                        _text(f"{metric.data_source}；{metric.observation_period}"),
                        _text(_metric_target(metric)),
                        _text(metric.decision_rule),
                    )
                    for metric in report.metrics
                ),
            ),
            _Heading(2, "实验设计", "experiments"),
            _Table(
                ("假设/人群", "设计与对照", "周期/指标", "成功标准", "停止条件"),
                tuple(
                    (
                        _text(
                            f"{experiment.hypothesis_claim_id}；"
                            f"{experiment.target_segment}"
                        ),
                        _text(f"{experiment.design}；对照：{experiment.comparison}"),
                        _text(
                            f"{experiment.duration}；"
                            f"{', '.join(experiment.primary_metric_ids)}；"
                            f"样本：{experiment.sample_size_method}"
                        ),
                        _text(experiment.success_criteria),
                        _text(experiment.stop_conditions),
                    )
                    for experiment in report.experiments
                ),
            ),
            _Heading(2, "资源与预算", "resources-and-budget"),
            _Table(
                ("资源项", "估算", "估算依据", "需确认"),
                tuple(
                    (
                        _text(item.item),
                        _text(item.estimate),
                        _text(item.estimation_basis),
                        _text(item.needs_confirmation),
                    )
                    for item in report.resources_and_budget
                ),
            ),
            _Heading(2, "风险控制", "risks"),
            _Table(
                ("风险", "触发信号", "应对措施", "负责人", "监控指标"),
                tuple(
                    (
                        _text(item.risk),
                        _text(item.trigger),
                        _text(item.mitigation),
                        _text(item.owner_role),
                        _text(item.monitoring_metric_ids),
                    )
                    for item in report.risks
                ),
            ),
            _Heading(2, "假设清单", "assumptions"),
            _claim_table(report.assumptions, citation_by_evidence_id),
            _Heading(2, "质量说明与局限", "quality-and-limitations"),
            _Paragraph(
                _text(
                    f"交付状态：{_DELIVERY_LABELS[report.delivery_status]}。"
                    "报告区分事实、推断、建议和假设；所有未验证目标均需先通过实验建立基线。"
                ),
                role="quality",
            ),
            _BulletList(tuple(_text(item) for item in report.limitations)),
            _Paragraph(_text(report.decision_support_notice), role="notice"),
            _Heading(2, "证据附录", "evidence-appendix"),
            _Table(
                ("编号", "来源", "摘录与适用边界", "可信度/核验", "访问时间"),
                tuple(
                    (
                        _text(
                            f"[{citation_by_evidence_id[item.evidence_id]}]",
                            anchor=(
                                "evidence-"
                                f"{citation_by_evidence_id[item.evidence_id].lower()}"
                            ),
                        ),
                        _text(
                            f"{item.title} — {item.publisher}",
                            href=str(item.url),
                        ),
                        _text(
                            f"摘录：{item.supporting_excerpt}；"
                            f"边界：{item.context_summary}"
                        ),
                        _text(
                            f"{item.credibility.level.value}；"
                            f"{_VERIFICATION_LABELS[item.verification_status]}；"
                            f"{item.credibility.rationale}"
                        ),
                        _text(item.accessed_at.isoformat()),
                    )
                    for item in report.evidence_appendix
                ),
            ),
        ]
    )
    return tuple(blocks)


def _claim_table(
    claims: Sequence[Claim], citation_by_evidence_id: dict[str, str]
) -> _Table:
    rows: list[tuple[_Text, ...]] = []
    for value in claims:
        rows.append(
            (
                _text(_CLAIM_LABELS[value.claim_type]),
                _text(
                    value.text,
                    citations=_citation_labels(
                        value.evidence_ids, citation_by_evidence_id
                    ),
                ),
                _text(value.reasoning),
                _text(_VERIFICATION_LABELS[value.verification_status]),
            )
        )
    return _Table(("类型", "判断", "依据/推理", "核验状态"), tuple(rows))


def _metric_target(metric: MetricDefinition) -> str:
    target = metric.target
    if target is None:
        return "未设定；需先建立基线"
    hypothesis_label = "假设值" if target.is_hypothesis else "已确认值"
    return (
        f"{target.lower_bound:g}–{target.upper_bound:g} {target.unit}；"
        f"{hypothesis_label}；依据：{target.rationale}"
    )


def _render_markdown(
    report: OperationsReport,
    blocks: tuple[_Block, ...],
    branding: ReportBranding | None,
) -> str:
    active_branding = branding or ReportBranding()
    lines: list[str] = []
    logo_data_uri = active_branding.logo_data_uri()
    if logo_data_uri:
        lines.extend(
            [
                f"![{_markdown_text(active_branding.logo_alt)}]({logo_data_uri})",
                "",
            ]
        )
    if active_branding.header_text:
        lines.extend([f"> {_markdown_text(active_branding.header_text)}", ""])
    lines.extend(
        [f"# {_markdown_text(active_branding.display_title(report.title))}", ""]
    )
    for block in blocks:
        if isinstance(block, _Heading):
            lines.extend([f'<a id="{_markdown_attr(block.anchor)}"></a>', ""])
            lines.extend([f"{'#' * block.level} {_markdown_text(block.title)}", ""])
        elif isinstance(block, _Paragraph):
            prefix = "> " if block.role in {"notice", "quality"} else ""
            lines.extend([f"{prefix}{_markdown_rich_text(block.content)}", ""])
        elif isinstance(block, _BulletList):
            lines.extend([f"- {_markdown_rich_text(item)}" for item in block.items])
            lines.append("")
        else:
            lines.append("| " + " | ".join(_markdown_cell(item) for item in block.headers) + " |")
            lines.append("| " + " | ".join("---" for _ in block.headers) + " |")
            for row in block.rows:
                lines.append(
                    "| "
                    + " | ".join(
                        _markdown_rich_text(cell, table_cell=True) for cell in row
                    )
                    + " |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_rich_text(value: _Text, *, table_cell: bool = False) -> str:
    content = _markdown_text(value.value)
    if table_cell:
        content = content.replace("|", "\\|").replace("\n", "<br>")
    if value.href:
        content = f"[{content}]({_markdown_url(value.href)})"
    if value.anchor:
        content = f'<a id="{_markdown_attr(value.anchor)}"></a>{content}'
    if value.citations:
        refs = " ".join(
            f"[{label}](#evidence-{label.lower()})" for label in value.citations
        )
        content = f"{content} {refs}"
    return content


def _markdown_text(value: str) -> str:
    escaped = escape(value, quote=False)
    return re.sub(r"([\\`*_\[\]#])", r"\\\1", escaped)


def _markdown_cell(value: str) -> str:
    return _markdown_text(value).replace("|", "\\|").replace("\n", "<br>")


def _markdown_url(value: str) -> str:
    return value.replace("(", "%28").replace(")", "%29")


def _markdown_attr(value: str) -> str:
    return escape(value, quote=True)


def _render_html(
    report: OperationsReport,
    blocks: tuple[_Block, ...],
    branding: ReportBranding | None,
) -> str:
    active_branding = branding or ReportBranding()
    body: list[str] = []
    for block in blocks:
        if isinstance(block, _Heading):
            body.append(
                f'<h{block.level} id="{escape(block.anchor, quote=True)}">'
                f"{escape(block.title)}</h{block.level}>"
            )
        elif isinstance(block, _Paragraph):
            css_class = f' class="{block.role}"' if block.role != "normal" else ""
            body.append(f"<p{css_class}>{_html_rich_text(block.content)}</p>")
        elif isinstance(block, _BulletList):
            items = "".join(f"<li>{_html_rich_text(item)}</li>" for item in block.items)
            body.append(f"<ul>{items}</ul>")
        else:
            head = "".join(f'<th scope="col">{escape(item)}</th>' for item in block.headers)
            rows = []
            for row in block.rows:
                rows.append(
                    "<tr>" + "".join(f"<td>{_html_rich_text(cell)}</td>" for cell in row) + "</tr>"
                )
            body.append(
                '<div class="table-wrap"><table><thead><tr>'
                f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
            )

    title = escape(active_branding.display_title(report.title))
    logo_data_uri = active_branding.logo_data_uri()
    brand_header = ""
    if logo_data_uri or active_branding.header_text:
        logo = (
            f'<img class="brand-logo" src="{escape(logo_data_uri, quote=True)}" '
            f'alt="{escape(active_branding.logo_alt, quote=True)}">'
            if logo_data_uri
            else ""
        )
        header_text = (
            f"<span>{escape(active_branding.header_text)}</span>"
            if active_branding.header_text
            else ""
        )
        brand_header = f'<header class="brand-header">{logo}{header_text}</header>\n'
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"<style>{_HTML_STYLE}</style>\n"
        "</head>\n<body>\n<main>\n"
        f"{brand_header}"
        f"<h1>{title}</h1>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def _html_rich_text(value: _Text) -> str:
    content = escape(value.value).replace("\n", "<br>")
    if value.href:
        content = (
            f'<a href="{escape(value.href, quote=True)}" rel="noopener noreferrer">'
            f"{content}</a>"
        )
    if value.anchor:
        content = f'<span id="{escape(value.anchor, quote=True)}">{content}</span>'
    if value.citations:
        refs = " ".join(
            f'<a class="citation" href="#evidence-{label.lower()}">[{label}]</a>'
            for label in value.citations
        )
        content = f"{content} {refs}"
    return content


_HTML_STYLE = re.sub(
    r"\s+",
    " ",
    """
    :root { color-scheme: light; font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif; }
    body { margin: 0; color: #172033; background: #f5f7fb; line-height: 1.65; }
    main { box-sizing: border-box; max-width: 1120px; margin: 0 auto;
      padding: 48px 40px 80px; background: #fff; }
    .brand-header { display: flex; gap: 16px; align-items: center; justify-content: space-between;
      margin-bottom: 24px; color: #52647a; font-size: .86rem; }
    .brand-logo { display: block; max-width: 180px; max-height: 54px; object-fit: contain; }
    h1 { margin: 0 0 24px; font-size: 2rem; line-height: 1.25; }
    h2 { margin: 44px 0 16px; padding-bottom: 8px;
      border-bottom: 2px solid #dbe4f0; font-size: 1.35rem; }
    h3 { margin: 28px 0 12px; font-size: 1.1rem; }
    p, ul { margin: 12px 0; }
    .notice, .quality { padding: 12px 16px; border-radius: 8px; }
    .notice { border-left: 4px solid #b7791f; background: #fffaf0; }
    .quality { border-left: 4px solid #3567a8; background: #eff6ff; }
    .table-wrap { margin: 14px 0 24px; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: .92rem; }
    th, td { padding: 10px 12px; border: 1px solid #dbe4f0; text-align: left; vertical-align: top; }
    th { background: #eef3f9; font-weight: 650; }
    tr:nth-child(even) td { background: #fafcff; }
    a { color: #1859a9; text-underline-offset: 2px; }
    .citation { white-space: nowrap; font-weight: 650; }
    @media (max-width: 640px) { main { padding: 28px 18px 56px; } h1 { font-size: 1.6rem; } }
    """,
).strip()
