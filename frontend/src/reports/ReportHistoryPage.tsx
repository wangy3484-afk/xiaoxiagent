import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, apiRequest } from "../api/client";
import { useAuth } from "../auth/authState";
import type { ReportHistoryResponse, ReportVersionSummary } from "./types";

const SCENE_LABELS: Record<string, string> = {
  acquisition: "拉新增长",
  retention: "用户留存",
  campaign: "活动运营",
  content: "内容运营",
};

export function ReportHistoryPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [reports, setReports] = useState<ReportVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void apiRequest<ReportHistoryResponse>("/reports")
      .then((response) => setReports(response.reports ?? []))
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : "报告历史读取失败。"),
      )
      .finally(() => setLoading(false));
  }, []);

  const series = useMemo(() => {
    const grouped = new Map<string, ReportVersionSummary[]>();
    for (const report of reports) {
      const versions = grouped.get(report.series_id) ?? [];
      versions.push(report);
      grouped.set(report.series_id, versions);
    }
    return [...grouped.values()].map((versions) =>
      versions.sort((left, right) => right.version_number - left.version_number),
    );
  }, [reports]);

  async function signOut() {
    await auth.logout();
    navigate("/login", { replace: true });
  }

  return (
    <main className="shell compact-shell history-page">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">REPORT WORKSPACE</p>
          <h1 className="page-title">报告工作台</h1>
        </div>
        <div className="account-actions">
          <span>{auth.account?.email}</span>
          <button className="secondary-button" type="button" onClick={() => void signOut()}>
            退出登录
          </button>
        </div>
      </header>
      <div className="workspace-toolbar">
        <p className="lead">按运营场景和生成时间查看报告，历史版本始终保留。</p>
        <Link className="primary-link" to="/briefs/new">新建运营方案</Link>
      </div>

      {loading && <p role="status">正在读取报告历史…</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {!loading && !error && series.length === 0 && (
        <section className="empty-state">
          <h2>还没有运营报告</h2>
          <p>从一个真实运营场景开始，确认简报后即可生成专业方案。</p>
          <Link className="primary-link" to="/briefs/new">创建第一份方案</Link>
        </section>
      )}

      <section className="report-history" aria-label="报告历史">
        {series.map((versions) => {
          const latest = versions[0];
          return (
            <article className="history-card" key={latest.series_id}>
              <div className="history-card-main">
                <div className="history-meta">
                  <span>{SCENE_LABELS[latest.scene] ?? latest.scene}</span>
                  <time dateTime={latest.generated_at}>
                    {new Date(latest.generated_at).toLocaleString("zh-CN")}
                  </time>
                </div>
                <h2>{latest.title}</h2>
                <p>最新版本 v{latest.version_number} · {latest.delivery_status}</p>
                <Link className="primary-link" to={`/reports/${latest.report_version_id}`}>
                  阅读最新报告
                </Link>
              </div>
              <nav className="version-list" aria-label={`${latest.title}版本列表`}>
                <strong>历史版本</strong>
                {versions.map((version) => (
                  <Link key={version.report_version_id} to={`/reports/${version.report_version_id}`}>
                    v{version.version_number}
                    <small>{new Date(version.generated_at).toLocaleDateString("zh-CN")}</small>
                  </Link>
                ))}
              </nav>
            </article>
          );
        })}
      </section>
    </main>
  );
}
