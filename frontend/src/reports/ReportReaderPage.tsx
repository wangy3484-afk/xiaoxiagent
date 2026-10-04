import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, apiRequest } from "../api/client";
import type { ReportVersionDetail } from "./types";

const SECTION_LABELS: Array<[string, string]> = [
  ["executive_summary", "执行摘要"],
  ["brief", "确认简报"],
  ["diagnosis", "问题诊断"],
  ["audience_analysis", "用户分析"],
  ["case_mechanisms", "案例机制"],
  ["key_claims", "关键判断"],
  ["strategies", "策略设计"],
  ["actions", "行动计划"],
  ["metrics", "指标体系"],
  ["experiments", "实验计划"],
  ["resources_and_budget", "资源与预算"],
  ["risks", "风险与预案"],
  ["assumptions", "待验证假设"],
  ["limitations", "限制说明"],
  ["evidence_appendix", "证据附录"],
  ["decision_support_notice", "决策支持说明"],
];

const KEY_LABELS: Record<string, string> = {
  text: "内容",
  reasoning: "判断依据",
  objective: "目标",
  target_segment: "目标人群",
  owner_role: "负责人角色",
  timeline: "时间",
  deliverable: "交付物",
  acceptance_criteria: "验收标准",
  formula: "口径公式",
  decision_rule: "判断规则",
  title: "标题",
  publisher: "来源主体",
  publication_date: "发布日期",
  accessed_at: "访问日期",
};

function labelFor(key: string): string {
  return KEY_LABELS[key] ?? key.replaceAll("_", " ");
}

const CLAIM_LABELS: Record<string, string> = {
  fact: "事实",
  inference: "推断",
  recommendation: "建议",
  hypothesis: "假设",
};

function isClaim(value: Record<string, unknown>): boolean {
  return typeof value.claim_type === "string" && typeof value.text === "string";
}

function isEvidence(value: Record<string, unknown>): boolean {
  return (
    typeof value.evidence_id === "string" &&
    typeof value.url === "string" &&
    typeof value.publisher === "string"
  );
}

function ClaimCard({ claim }: { claim: Record<string, unknown> }) {
  const claimType = String(claim.claim_type);
  const evidenceIds = Array.isArray(claim.evidence_ids) ? claim.evidence_ids : [];
  return (
    <article className="claim-card">
      <span className={`claim-badge ${claimType}`}>{CLAIM_LABELS[claimType] ?? claimType}</span>
      <p>{String(claim.text)}</p>
      {typeof claim.reasoning === "string" && <small>判断依据：{claim.reasoning}</small>}
      {evidenceIds.length > 0 && (
        <nav aria-label="关联证据" className="claim-evidence-links">
          {evidenceIds.map((evidenceId) => (
            <a key={String(evidenceId)} href={`#evidence-${String(evidenceId)}`}>
              证据 {String(evidenceId)}
            </a>
          ))}
        </nav>
      )}
    </article>
  );
}

function EvidenceCard({ evidence }: { evidence: Record<string, unknown> }) {
  const evidenceId = String(evidence.evidence_id);
  const publicationDate =
    typeof evidence.publication_date === "string" ? evidence.publication_date : "发布日期未知";
  const accessedAt =
    typeof evidence.accessed_at === "string"
      ? new Date(evidence.accessed_at).toLocaleDateString("zh-CN")
      : "未知";
  return (
    <article className="evidence-card" id={`evidence-${evidenceId}`}>
      <div className="evidence-card-heading">
        <span>{String(evidence.source_type ?? "source")}</span>
        <span>{String(evidence.verification_status ?? "unverified")}</span>
      </div>
      <h3>
        <a href={String(evidence.url)} target="_blank" rel="noreferrer">
          {String(evidence.title ?? "查看原始来源")}
        </a>
      </h3>
      <dl>
        <div><dt>来源主体</dt><dd>{String(evidence.publisher)}</dd></div>
        <div><dt>发布日期</dt><dd>{publicationDate}</dd></div>
        <div><dt>访问日期</dt><dd>{accessedAt}</dd></div>
      </dl>
      {typeof evidence.context_summary === "string" && <p>{evidence.context_summary}</p>}
    </article>
  );
}

function StructuredValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="unknown-value">未知</span>;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <span>{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    return (
      <div className={depth === 0 ? "report-card-grid" : "nested-list"}>
        {value.map((item, index) => (
          <article className="report-item" key={index}>
            <StructuredValue value={item} depth={depth + 1} />
          </article>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (isClaim(record)) return <ClaimCard claim={record} />;
    if (isEvidence(record)) return <EvidenceCard evidence={record} />;
    return (
      <dl className="structured-fields">
        {Object.entries(record).map(([key, item]) => (
          <div key={key}>
            <dt>{labelFor(key)}</dt>
            <dd><StructuredValue value={item} depth={depth + 1} /></dd>
          </div>
        ))}
      </dl>
    );
  }
  return null;
}

function responsibilityNotice(deliveryStatus: string): string {
  const statusNotice = deliveryStatus === "formal"
    ? "正式报告已通过当前质量门槛，但结论仍受证据时效、场景差异与数据边界约束。"
    : "方向性草案仍有未确认输入或证据局限，只可用于讨论和小范围验证，不应直接用于规模化执行。";
  return `${statusNotice}本报告仅用于运营决策支持；所有策略仅在报告列明的适用条件成立时使用。效果预测、指标目标与资源估算必须由业务负责人结合实际数据验证，最终执行和业务决策由用户负责。`;
}

export function ReportReaderPage() {
  const { reportId = "" } = useParams();
  const [result, setResult] = useState<{
    reportId: string;
    report: ReportVersionDetail | null;
    error: string;
  }>({ reportId: "", report: null, error: "" });

  useEffect(() => {
    let active = true;
    void apiRequest<ReportVersionDetail>(`/reports/${reportId}`)
      .then((report) => {
        if (active) setResult({ reportId, report, error: "" });
      })
      .catch((caught) => {
        if (active) {
          setResult({
            reportId,
            report: null,
            error: caught instanceof ApiError ? caught.message : "报告读取失败。",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [reportId]);

  if (result.reportId === reportId && result.error) {
    return (
      <main className="shell compact-shell">
        <h1 className="page-title">无法读取报告</h1>
        <p className="error-message" role="alert">{result.error}</p>
        <Link className="secondary-link" to="/reports">返回报告历史</Link>
      </main>
    );
  }
  if (result.reportId !== reportId || !result.report) {
    return <main className="shell compact-shell" role="status">正在读取报告…</main>;
  }
  const report = result.report;

  const availableSections = SECTION_LABELS.filter(([key]) => key in report.report_payload);
  return (
    <main className="report-reader">
      <header className="report-hero">
        <Link to="/reports">← 返回报告历史</Link>
        <p className="eyebrow">{report.scene} · v{report.version_number}</p>
        <h1 className="page-title">{report.title}</h1>
        <div className="report-byline">
          <time dateTime={report.generated_at}>
            {new Date(report.generated_at).toLocaleString("zh-CN")}
          </time>
          <span>{report.delivery_status}</span>
        </div>
        <nav className="version-switcher" aria-label="报告版本">
          {report.available_versions.map((version) => (
            <Link
              key={version.report_version_id}
              className={version.report_version_id === report.id ? "active" : ""}
              to={`/reports/${version.report_version_id}`}
            >
              v{version.version_number}
            </Link>
          ))}
        </nav>
      </header>

      <aside className="decision-support-banner" aria-label="决策支持与验证责任">
        <strong>决策支持与验证责任</strong>
        <p>{responsibilityNotice(report.delivery_status)}</p>
      </aside>

      <div className="report-layout">
        <aside className="report-toc">
          <strong>报告目录</strong>
          <nav aria-label="报告目录">
            {availableSections.map(([key, label]) => (
              <a key={key} href={`#section-${key}`}>{label}</a>
            ))}
          </nav>
        </aside>
        <article className="report-content">
          {availableSections.map(([key, label]) => (
            <section id={`section-${key}`} key={key}>
              <p className="eyebrow">{key.replaceAll("_", " ")}</p>
              <h2>{label}</h2>
              <StructuredValue value={report.report_payload[key]} />
            </section>
          ))}
        </article>
      </div>
    </main>
  );
}
