import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, apiRequest } from "../api/client";

export interface JobStatusResponse {
  id: string;
  brief_id: string;
  brief_revision_id: string;
  status: "queued" | "running" | "retryable" | "completed" | "failed" | "cancelled";
  stage: string;
  progress_percent: number;
  error_code: string | null;
  error_message: string | null;
  report_version_ids: string[];
}

interface JobCreateResponse {
  id: string;
  status: string;
  stage: string;
}

const STAGE_LABELS: Record<string, string> = {
  queued: "任务已提交，等待生成",
  initializing: "正在准备研究上下文",
  load_context: "正在读取确认简报",
  research: "正在研究头部公司与相似案例",
  diagnosis: "正在诊断核心运营问题",
  strategy: "正在设计场景化策略",
  planning: "正在生成行动、指标与实验计划",
  assembly: "正在组装专业运营报告",
  quality: "正在进行独立质量审查",
  finalize: "正在确定交付状态",
  completed: "报告已生成",
  retryable_error: "外部服务暂时不可用",
  configuration_error: "服务配置不完整",
  queue_error: "任务队列暂时不可用",
  failed: "报告生成失败",
};

const ACTIVE_STATUSES = new Set(["queued", "running"]);

export function JobStatusPage({ pollIntervalMs = 2000 }: { pollIntervalMs?: number }) {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const current = await apiRequest<JobStatusResponse>(`/jobs/${jobId}`);
      setJob(current);
      setError("");
      return current;
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "任务状态读取失败，请稍后重试。");
      return null;
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      const current = await load();
      if (!stopped && current && ACTIVE_STATUSES.has(current.status)) {
        timer = setTimeout(() => void poll(), pollIntervalMs);
      }
    }
    void poll();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [load, pollIntervalMs]);

  async function retry() {
    if (!job) return;
    setRetrying(true);
    setError("");
    try {
      const created = await apiRequest<JobCreateResponse>("/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          brief_id: job.brief_id,
          brief_revision_id: job.brief_revision_id,
        }),
      });
      navigate(`/jobs/${created.id}`, { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "重新生成失败，请稍后重试。");
    } finally {
      setRetrying(false);
    }
  }

  if (loading && !job) {
    return (
      <main className="shell compact-shell" aria-live="polite">
        <p className="eyebrow">REPORT JOB</p>
        <h1 className="page-title">正在恢复任务状态</h1>
      </main>
    );
  }

  if (!job) {
    return (
      <main className="shell compact-shell">
        <h1 className="page-title">无法读取报告任务</h1>
        {error && <p className="error-message" role="alert">{error}</p>}
        <Link className="secondary-link" to="/reports">返回工作台</Link>
      </main>
    );
  }

  const canRetry = job.status === "retryable" || job.error_code === "JOB_QUEUE_UNAVAILABLE";
  const active = ACTIVE_STATUSES.has(job.status);
  return (
    <main className="shell compact-shell job-page">
      <p className="eyebrow">REPORT JOB · {job.id.slice(0, 8)}</p>
      <h1 className="page-title">{STAGE_LABELS[job.stage] ?? "正在生成运营报告"}</h1>
      <p className="lead">
        {active
          ? "你可以离开此页面，稍后重新进入仍会从服务端恢复最新进度。"
          : job.status === "completed"
            ? "报告与质量审查结果已安全保存。"
            : "已保留确认简报和任务事件，便于排查或重新生成。"}
      </p>

      <section className="progress-card" aria-live="polite">
        <div className="progress-heading">
          <span>当前阶段</span>
          <strong>{Math.max(0, Math.min(100, job.progress_percent))}%</strong>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="报告生成进度"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={job.progress_percent}
        >
          <span style={{ width: `${job.progress_percent}%` }} />
        </div>
        <dl className="job-metadata">
          <div><dt>任务状态</dt><dd>{job.status}</dd></div>
          <div><dt>执行阶段</dt><dd>{job.stage}</dd></div>
          <div><dt>简报版本</dt><dd>{job.brief_revision_id.slice(0, 8)}</dd></div>
        </dl>
      </section>

      {(job.status === "failed" || job.status === "retryable") && (
        <section className="failure-card" aria-labelledby="failure-title">
          <p className="eyebrow">GENERATION NOTICE</p>
          <h2 id="failure-title">{canRetry ? "本次生成可以重试" : "需要处理后再重新生成"}</h2>
          <p>{job.error_message ?? "任务未能完成，请联系管理员并提供任务编号。"}</p>
          {job.error_code && <code>{job.error_code}</code>}
          {canRetry && (
            <button className="primary-button" type="button" onClick={() => void retry()} disabled={retrying}>
              {retrying ? "正在重新提交…" : "重新生成"}
            </button>
          )}
        </section>
      )}

      {job.status === "completed" && job.report_version_ids.length > 0 && (
        <section className="confirmation-card">
          <p className="success-kicker">生成完成</p>
          <h2>专业运营报告已经就绪</h2>
          <Link className="primary-link" to={`/reports/${job.report_version_ids.at(-1)}`}>
            查看报告
          </Link>
        </section>
      )}
      {error && <p className="error-message" role="alert">{error}</p>}
      <Link className="secondary-link" to="/reports">返回报告工作台</Link>
    </main>
  );
}
