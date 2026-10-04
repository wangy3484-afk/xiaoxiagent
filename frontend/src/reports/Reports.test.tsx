import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { AuthContext } from "../auth/authState";
import { ReportHistoryPage } from "./ReportHistoryPage";
import { ReportReaderPage } from "./ReportReaderPage";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const versions = [
  {
    report_version_id: "report-2",
    series_id: "report-1",
    job_id: "job-2",
    version_number: 2,
    title: "新用户留存运营方案",
    scene: "retention",
    delivery_status: "formal",
    generated_at: "2026-10-04T01:00:00Z",
  },
  {
    report_version_id: "report-1",
    series_id: "report-1",
    job_id: "job-1",
    version_number: 1,
    title: "新用户留存运营方案",
    scene: "retention",
    delivery_status: "directional_draft",
    generated_at: "2026-10-03T01:00:00Z",
  },
];

afterEach(() => vi.unstubAllGlobals());

it("groups report history and preserves every version", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ reports: versions })));
  render(
    <MemoryRouter>
      <AuthContext.Provider
        value={{
          status: "authenticated",
          account: { id: "user-1", email: "operator@example.com" },
          login: vi.fn(),
          logout: vi.fn(),
        }}
      >
        <ReportHistoryPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("heading", { name: "新用户留存运营方案" })).toBeInTheDocument();
  expect(screen.getByText("最新版本 v2 · formal")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /v1/ })).toHaveAttribute("href", "/reports/report-1");
  expect(screen.getByRole("link", { name: /v2/ })).toHaveAttribute("href", "/reports/report-2");
});

it("renders a read-only report with table of contents and version navigation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse({
        ...versions[0],
        id: "report-2",
        brief_revision_id: "revision-2",
        available_versions: [...versions].reverse(),
        report_payload: {
          executive_summary: "围绕新用户首周关键行为建立分层触达与验证闭环。",
          diagnosis: { core_tension: "价值到达速度慢于用户流失速度" },
          strategies: [
            { strategy_id: "strategy-1", name: "首周里程碑引导", objective: "提升关键行为完成率" },
          ],
          key_claims: [
            {
              claim_id: "claim-1",
              text: "头部平台普遍通过首周关键行为引导改善留存。",
              claim_type: "fact",
              evidence_ids: ["evidence-1"],
              reasoning: "官方案例直接说明了引导机制。",
              verification_status: "verified",
            },
            {
              claim_id: "claim-2",
              text: "该机制可能适合当前资源约束。",
              claim_type: "inference",
              evidence_ids: [],
              reasoning: "根据团队规模进行适配判断。",
              verification_status: "unverified",
            },
          ],
          evidence_appendix: [
            {
              evidence_id: "evidence-1",
              title: "官方留存机制说明",
              publisher: "示例平台",
              source_type: "official_primary",
              url: "https://example.com/retention-case",
              publication_date: null,
              publication_date_status: "unknown",
              accessed_at: "2026-10-04T01:00:00Z",
              verification_status: "verified",
              context_summary: "官方公开说明首周引导机制。",
            },
          ],
          decision_support_notice: "本报告用于运营决策支持，实际效果需通过业务实验验证。",
        },
      }),
    ),
  );
  render(
    <MemoryRouter initialEntries={["/reports/report-2"]}>
      <Routes>
        <Route path="/reports/:reportId" element={<ReportReaderPage />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("heading", { name: "新用户留存运营方案" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "报告目录" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "执行摘要" })).toHaveAttribute(
    "href",
    "#section-executive_summary",
  );
  expect(screen.getByRole("heading", { name: "策略设计" })).toBeInTheDocument();
  expect(screen.getByText("首周里程碑引导")).toBeInTheDocument();
  expect(screen.getByText("事实")).toHaveClass("fact");
  expect(screen.getByText("推断")).toHaveClass("inference");
  expect(screen.getByRole("link", { name: "证据 evidence-1" })).toHaveAttribute(
    "href",
    "#evidence-evidence-1",
  );
  expect(screen.getByRole("link", { name: "官方留存机制说明" })).toHaveAttribute(
    "href",
    "https://example.com/retention-case",
  );
  expect(screen.getByText("示例平台")).toBeInTheDocument();
  expect(screen.getByText("发布日期未知")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "v1" })).toHaveAttribute("href", "/reports/report-1");
  expect(screen.getByRole("link", { name: "v2" })).toHaveClass("active");
  expect(screen.getByRole("complementary", { name: "决策支持与验证责任" })).toHaveTextContent(
    "所有策略仅在报告列明的适用条件成立时使用",
  );
  expect(screen.getByRole("complementary", { name: "决策支持与验证责任" })).toHaveTextContent(
    "必须由业务负责人结合实际数据验证",
  );
  expect(screen.getByRole("complementary", { name: "决策支持与验证责任" })).not.toHaveTextContent(
    /保证实现|必然实现|承诺达到/,
  );
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

it("shows draft-specific execution boundaries", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse({
        ...versions[1],
        id: "report-1",
        brief_revision_id: "revision-1",
        available_versions: [versions[1]],
        report_payload: { executive_summary: "先完成小范围验证。" },
      }),
    ),
  );
  render(
    <MemoryRouter initialEntries={["/reports/report-1"]}>
      <Routes>
        <Route path="/reports/:reportId" element={<ReportReaderPage />} />
      </Routes>
    </MemoryRouter>,
  );

  const boundary = await screen.findByRole("complementary", {
    name: "决策支持与验证责任",
  });
  expect(boundary).toHaveTextContent("方向性草案仍有未确认输入或证据局限");
  expect(boundary).toHaveTextContent("不应直接用于规模化执行");
  expect(boundary).not.toHaveTextContent(/保证实现|必然实现|承诺达到/);
});
