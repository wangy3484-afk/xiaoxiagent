import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { BriefWorkspace } from "./BriefWorkspace";
import type { BriefField, BriefWorkflowResponse } from "./types";

function unknownField(): BriefField {
  return {
    value: null,
    status: "unknown",
    source: "unknown",
    source_excerpt: null,
    asserted_as_fact: false,
  };
}

function confirmedField(value: string): BriefField {
  return {
    value,
    status: "confirmed",
    source: "user_input",
    source_excerpt: value,
    asserted_as_fact: true,
  };
}

const parsedBrief: BriefWorkflowResponse = {
  id: "brief-1",
  revision_id: "revision-1",
  revision_number: 1,
  status: "draft",
  brief: {
    business_context: unknownField(),
    current_problem: confirmedField("首周关键行为完成率偏低"),
    operation_goal: confirmedField("提升次月留存"),
    target_users: unknownField(),
    business_stage: unknownField(),
    execution_period: unknownField(),
    budget_and_resources: unknownField(),
    existing_channels: unknownField(),
    current_baseline: unknownField(),
    constraints: unknownField(),
    preferred_benchmark_companies: unknownField(),
  },
  classification: {
    primary_scene: "retention",
    secondary_scenes: [],
    rationale: ["目标是提升留存"],
    confidence: 0.82,
    uncertainties: ["目标用户待确认"],
    user_corrected: false,
  },
  ready_for_research: false,
  required_gaps: ["target_users"],
  clarifying_questions: [
    {
      id: "target-users",
      field: "target_users",
      prompt: "需要影响的是哪类用户？",
      priority: "critical",
      rationale: "目标用户决定触达机制。",
    },
  ],
  data_boundary: {
    title: "请仅提交非敏感、汇总后的运营信息",
    prohibited: ["个人身份信息", "用户明细"],
    allowed_alternatives: ["汇总指标", "匿名用户分群"],
  },
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

it("completes fuzzy input, correction, clarification, and confirmation", async () => {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/briefs/parse")) return Promise.resolve(jsonResponse(parsedBrief, 201));
    if (path.endsWith("/briefs/brief-1") && init?.method === "PATCH") {
      return Promise.resolve(
        jsonResponse({
          ...parsedBrief,
          revision_id: "revision-2",
          revision_number: 2,
          brief: {
            ...parsedBrief.brief,
            target_users: {
              value: "注册 7 天内且未完成核心行为的用户",
              status: "confirmed",
              source: "user_correction",
              source_excerpt: "注册 7 天内且未完成核心行为的用户",
              asserted_as_fact: true,
            },
          },
          classification: {
            primary_scene: "campaign",
            secondary_scenes: [],
            rationale: ["用户将主场景修正为活动运营。"],
            confidence: 1,
            uncertainties: [],
            user_corrected: true,
          },
        }),
      );
    }
    if (path.endsWith("/briefs/brief-1/confirm") && init?.method === "POST") {
      return Promise.resolve(
        jsonResponse({
          ...parsedBrief,
          revision_id: "revision-2",
          revision_number: 2,
          status: "confirmed",
          ready_for_research: true,
          required_gaps: [],
          clarifying_questions: [],
          classification: {
            primary_scene: "campaign",
            secondary_scenes: [],
            rationale: ["用户将主场景修正为活动运营。"],
            confidence: 1,
            uncertainties: [],
            user_corrected: true,
          },
        }),
      );
    }
    if (path.endsWith("/jobs") && init?.method === "POST") {
      return Promise.resolve(jsonResponse({ id: "job-1", status: "queued", stage: "queued" }, 202));
    }
    throw new Error(`unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <BriefWorkspace />
    </MemoryRouter>,
  );

  await user.type(
    screen.getByLabelText("运营场景"),
    "我们想提升留存，但目标人群和资源还不清楚。",
  );
  await user.click(screen.getByRole("button", { name: "生成结构化简报" }));

  expect(await screen.findByRole("heading", { name: "确认研究基线" })).toBeInTheDocument();
  expect(screen.getByLabelText("输入数据边界")).toHaveTextContent("个人身份信息");
  expect(screen.getByText("需要影响的是哪类用户？")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "未确认前不能生成报告" })).toBeDisabled();

  await user.selectOptions(screen.getByLabelText("主场景"), "campaign");
  await user.type(screen.getByLabelText(/目标用户/), "注册 7 天内且未完成核心行为的用户");
  await user.click(screen.getByRole("button", { name: "确认简报" }));

  expect(await screen.findByText("简报已确认")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "活动运营研究基线已锁定" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成运营报告" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "生成运营报告" }));
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/jobs"))).toBe(true);

  const patchCall = fetchMock.mock.calls.find(
    ([path, init]) => String(path).endsWith("/briefs/brief-1") && init?.method === "PATCH",
  );
  const patchBody = JSON.parse(String(patchCall?.[1]?.body)) as {
    classification: { primary_scene: string; confidence: number; user_corrected: boolean };
  };
  expect(patchBody.classification).toMatchObject({
    primary_scene: "campaign",
    confidence: 1,
    user_corrected: true,
  });
});
