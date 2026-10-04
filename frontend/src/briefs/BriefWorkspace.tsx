import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, apiRequest } from "../api/client";
import type {
  BriefField,
  BriefPayload,
  BriefWorkflowResponse,
  Scene,
  SceneClassification,
} from "./types";

const FIELD_LABELS: Record<string, string> = {
  business_context: "业务背景",
  current_problem: "当前问题",
  operation_goal: "运营目标",
  target_users: "目标用户",
  business_stage: "业务阶段",
  execution_period: "执行周期",
  budget_and_resources: "预算与资源",
  existing_channels: "现有渠道（逗号分隔）",
  current_baseline: "当前基线",
  constraints: "限制条件（逗号分隔）",
  preferred_benchmark_companies: "希望参考的头部公司（逗号分隔）",
};

const LIST_FIELDS = new Set([
  "existing_channels",
  "constraints",
  "preferred_benchmark_companies",
]);

const SCENE_LABELS: Record<Scene, string> = {
  acquisition: "拉新增长",
  retention: "用户留存",
  campaign: "活动运营",
  content: "内容运营",
};

function fieldText(field: BriefField): string {
  if (Array.isArray(field.value)) return field.value.join("，");
  return typeof field.value === "string" ? field.value : "";
}

function correctedField(fieldName: string, rawValue: string): BriefField {
  const value = rawValue.trim();
  if (!value) {
    return {
      value: null,
      status: "unknown",
      source: "unknown",
      source_excerpt: null,
      asserted_as_fact: false,
    };
  }
  const normalizedValue = LIST_FIELDS.has(fieldName)
    ? value
        .split(/[，,\n]/)
        .map((item) => item.trim())
        .filter(Boolean)
    : value;
  return {
    value: normalizedValue,
    status: "confirmed",
    source: "user_correction",
    source_excerpt: value,
    asserted_as_fact: true,
  };
}

function correctedClassification(
  original: SceneClassification,
  selected: Scene,
): SceneClassification {
  if (original.primary_scene === selected) return original;
  return {
    primary_scene: selected,
    secondary_scenes: original.secondary_scenes.filter((scene) => scene !== selected),
    rationale: [`用户将主场景修正为${SCENE_LABELS[selected]}。`],
    confidence: 1,
    uncertainties: [],
    user_corrected: true,
  };
}

export function BriefWorkspace() {
  const navigate = useNavigate();
  const [scenario, setScenario] = useState("");
  const [workflow, setWorkflow] = useState<BriefWorkflowResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [scene, setScene] = useState<Scene>("retention");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submittingJob, setSubmittingJob] = useState(false);

  const orderedFields = useMemo(
    () => Object.keys(FIELD_LABELS).filter((field) => workflow?.brief[field]),
    [workflow],
  );

  async function parseScenario(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const parsed = await apiRequest<BriefWorkflowResponse>("/briefs/parse", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ scenario }),
      });
      setWorkflow(parsed);
      setScene(parsed.classification.primary_scene);
      setAnswers(
        Object.fromEntries(
          Object.entries(parsed.brief).map(([name, field]) => [name, fieldText(field)]),
        ),
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "场景解析失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function saveAndConfirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workflow) return;
    setBusy(true);
    setError("");
    try {
      const brief: BriefPayload = Object.fromEntries(
        Object.keys(workflow.brief).map((fieldName) => [
          fieldName,
          correctedField(fieldName, answers[fieldName] ?? ""),
        ]),
      );
      const revised = await apiRequest<BriefWorkflowResponse>(`/briefs/${workflow.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          expected_revision_number: workflow.revision_number,
          brief,
          classification: correctedClassification(workflow.classification, scene),
        }),
      });
      const confirmed = await apiRequest<BriefWorkflowResponse>(
        `/briefs/${workflow.id}/confirm`,
        {
          method: "POST",
          body: JSON.stringify({ expected_revision_number: revised.revision_number }),
        },
      );
      setWorkflow(confirmed);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "简报确认失败，请检查必填信息。");
    } finally {
      setBusy(false);
    }
  }

  async function createReportJob() {
    if (!workflow || workflow.status !== "confirmed") return;
    setSubmittingJob(true);
    setError("");
    try {
      const job = await apiRequest<{ id: string }>("/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          brief_id: workflow.id,
          brief_revision_id: workflow.revision_id,
        }),
      });
      navigate(`/jobs/${job.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "报告任务提交失败，请稍后重试。");
    } finally {
      setSubmittingJob(false);
    }
  }

  if (!workflow) {
    return (
      <main className="shell compact-shell intake-page">
        <p className="eyebrow">NEW OPERATIONS BRIEF</p>
        <h1 className="page-title">描述你当前的运营场景</h1>
        <p className="lead">
          可以写目标、用户、周期、预算、现有渠道和希望参考的公司；暂时不知道的数据可以明确写“未知”。
        </p>
        <aside className="notice" aria-label="数据使用提醒">
          <strong>请仅提交非敏感、汇总后的运营信息。</strong>
          <span> 禁止个人身份信息、用户明细、账号密钥和公司机密。</span>
        </aside>
        <form className="scenario-form" onSubmit={parseScenario}>
          <label htmlFor="scenario">运营场景</label>
          <textarea
            id="scenario"
            value={scenario}
            onChange={(event) => setScenario(event.target.value)}
            minLength={1}
            maxLength={20000}
            rows={9}
            placeholder="例如：我们是一款本地生活应用，希望在未来 90 天提升新注册用户的次月留存……"
            required
          />
          {error && <p className="error-message" role="alert">{error}</p>}
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "正在解析…" : "生成结构化简报"}
          </button>
        </form>
      </main>
    );
  }

  const confirmed = workflow.status === "confirmed";
  return (
    <main className="shell compact-shell intake-page">
      <p className="eyebrow">OPERATIONS BRIEF</p>
      <h1 className="page-title">确认研究基线</h1>
      <aside className="boundary-card" aria-label="输入数据边界">
        <strong>{workflow.data_boundary.title}</strong>
        <span>不可提交：{workflow.data_boundary.prohibited.join("、")}</span>
        <span>可使用：{workflow.data_boundary.allowed_alternatives.join("、")}</span>
      </aside>

      {confirmed ? (
        <section className="confirmation-card" aria-live="polite">
          <p className="success-kicker">简报已确认</p>
          <h2>{SCENE_LABELS[workflow.classification.primary_scene]}研究基线已锁定</h2>
          <p>系统将仅基于第 {workflow.revision_number} 版简报创建报告任务。</p>
          <div className="inline-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void createReportJob()}
              disabled={submittingJob}
            >
              {submittingJob ? "正在提交…" : "生成运营报告"}
            </button>
            <Link className="secondary-link" to="/reports">返回工作台</Link>
          </div>
        </section>
      ) : (
        <form className="brief-form" onSubmit={saveAndConfirm}>
          <section className="brief-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">CLASSIFICATION</p>
                <h2>运营场景分类</h2>
              </div>
              <span className="confidence-badge">
                模型置信度 {Math.round(workflow.classification.confidence * 100)}%
              </span>
            </div>
            <label>
              主场景
              <select value={scene} onChange={(event) => setScene(event.target.value as Scene)}>
                {Object.entries(SCENE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <p className="field-help">{workflow.classification.rationale.join("；")}</p>
          </section>

          {workflow.clarifying_questions.length > 0 && (
            <section className="brief-section question-list" aria-labelledby="questions-title">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">CLARIFICATION</p>
                  <h2 id="questions-title">需要你确认的问题</h2>
                </div>
                <span>{workflow.required_gaps.length} 个关键缺口</span>
              </div>
              {workflow.clarifying_questions.map((question) => (
                <article key={question.id}>
                  <strong>{question.prompt}</strong>
                  <p>{question.rationale}</p>
                </article>
              ))}
            </section>
          )}

          <section className="brief-section field-grid">
            {orderedFields.map((fieldName) => {
              const field = workflow.brief[fieldName];
              const required = fieldName === "operation_goal" || fieldName === "target_users";
              return (
                <label key={fieldName}>
                  <span>
                    {FIELD_LABELS[fieldName]}
                    {required && <em>必填</em>}
                  </span>
                  <textarea
                    value={answers[fieldName] ?? ""}
                    onChange={(event) =>
                      setAnswers((current) => ({ ...current, [fieldName]: event.target.value }))
                    }
                    rows={3}
                    required={required}
                  />
                  <small className={`field-status ${field.status}`}>当前状态：{field.status}</small>
                </label>
              );
            })}
          </section>
          {error && <p className="error-message" role="alert">{error}</p>}
          <div className="sticky-actions">
            <button className="secondary-button" type="button" disabled>
              未确认前不能生成报告
            </button>
            <button className="primary-button" type="submit" disabled={busy}>
              {busy ? "正在确认…" : "确认简报"}
            </button>
          </div>
        </form>
      )}
    </main>
  );
}
