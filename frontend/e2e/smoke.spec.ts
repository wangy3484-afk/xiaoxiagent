import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const unknownField = {
  value: null,
  status: "unknown",
  source: "unknown",
  source_excerpt: null,
  asserted_as_fact: false,
};

const draftBrief = {
  id: "brief-e2e",
  revision_id: "revision-1",
  revision_number: 1,
  status: "draft",
  brief: {
    business_context: unknownField,
    current_problem: unknownField,
    operation_goal: {
      value: "提升次月留存",
      status: "confirmed",
      source: "user_input",
      source_excerpt: "提升次月留存",
      asserted_as_fact: true,
    },
    target_users: unknownField,
    business_stage: unknownField,
    execution_period: unknownField,
    budget_and_resources: unknownField,
    existing_channels: unknownField,
    current_baseline: unknownField,
    constraints: unknownField,
    preferred_benchmark_companies: unknownField,
  },
  classification: {
    primary_scene: "retention",
    secondary_scenes: [],
    rationale: ["目标是提升留存"],
    confidence: 0.8,
    uncertainties: [],
    user_corrected: false,
  },
  ready_for_research: false,
  required_gaps: ["target_users"],
  clarifying_questions: [
    {
      id: "target-user",
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

async function mockSession(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "e2e-user", email: "operator@example.com" }),
    });
  });
}

async function expectNoSeriousAccessibilityViolations(
  page: import("@playwright/test").Page,
) {
  const results = await new AxeBuilder({ page }).analyze();
  const blocking = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(blocking, blocking.map((item) => `${item.id}: ${item.help}`).join("\n")).toEqual([]);
}

test("opens the report workspace", async ({ page }) => {
  await mockSession(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "专业运营策略 Agent" })).toBeVisible();

  await page.getByRole("link", { name: "登录并进入报告工作台" }).click();
  await expect(page).toHaveURL(/\/reports$/);
  await expect(page.getByRole("heading", { name: "报告工作台" })).toBeVisible();
});

test("completes fuzzy input, clarification, correction, and confirmation", async ({ page }) => {
  await mockSession(page);
  await page.route("**/api/v1/briefs/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/briefs/parse")) {
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(draftBrief) });
      return;
    }
    if (path.endsWith("/briefs/brief-e2e/confirm")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...draftBrief,
          revision_id: "revision-2",
          revision_number: 2,
          status: "confirmed",
          ready_for_research: true,
          required_gaps: [],
          clarifying_questions: [],
          classification: {
            primary_scene: "campaign",
            secondary_scenes: [],
            rationale: ["用户修正"],
            confidence: 1,
            uncertainties: [],
            user_corrected: true,
          },
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...draftBrief, revision_id: "revision-2", revision_number: 2 }),
    });
  });

  await page.goto("/briefs/new");
  await page.getByLabel("运营场景").fill("我们想提升留存，但目标人群和资源还不清楚。");
  await page.getByRole("button", { name: "生成结构化简报" }).click();
  await expect(page.getByRole("heading", { name: "确认研究基线" })).toBeVisible();
  await expect(page.getByText("需要影响的是哪类用户？")).toBeVisible();
  await expect(page.getByRole("button", { name: "未确认前不能生成报告" })).toBeDisabled();

  await page.getByLabel("主场景").selectOption("campaign");
  await page.getByLabel(/目标用户/).fill("注册 7 天内且未完成核心行为的用户");
  await page.getByRole("button", { name: "确认简报" }).click();

  await expect(page.getByText("简报已确认")).toBeVisible();
  await expect(page.getByRole("heading", { name: "活动运营研究基线已锁定" })).toBeVisible();
});

test("restores a running task after reload and shows completion", async ({ page }) => {
  await mockSession(page);
  let completed = false;
  await page.route("**/api/v1/jobs/job-running", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-running",
        brief_id: "brief-1",
        brief_revision_id: "revision-2",
        status: completed ? "completed" : "running",
        stage: completed ? "completed" : "research",
        progress_percent: completed ? 100 : 25,
        error_code: null,
        error_message: null,
        report_version_ids: completed ? ["report-1"] : [],
      }),
    });
  });

  await page.goto("/jobs/job-running");
  await expect(page.getByRole("heading", { name: "正在研究头部公司与相似案例" })).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "报告生成进度" })).toHaveAttribute(
    "aria-valuenow",
    "25",
  );
  completed = true;
  await page.reload();
  await expect(page.getByRole("heading", { name: "报告已生成" })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看报告" })).toBeVisible();
});

test("offers retry for a retryable failure", async ({ page }) => {
  await mockSession(page);
  await page.route("**/api/v1/jobs/job-retryable", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-retryable",
        brief_id: "brief-1",
        brief_revision_id: "revision-2",
        status: "retryable",
        stage: "retryable_error",
        progress_percent: 25,
        error_code: "PROVIDER_RATE_LIMITED",
        error_message: "搜索服务暂时不可用，可稍后重新生成。",
        report_version_ids: [],
      }),
    });
  });
  await page.route("**/api/v1/jobs", async (route) => {
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ id: "job-new", status: "queued", stage: "queued" }),
    });
  });
  await page.route("**/api/v1/jobs/job-new", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-new",
        brief_id: "brief-1",
        brief_revision_id: "revision-2",
        status: "queued",
        stage: "queued",
        progress_percent: 0,
        error_code: null,
        error_message: null,
        report_version_ids: [],
      }),
    });
  });

  await page.goto("/jobs/job-retryable");
  await expect(page.getByRole("heading", { name: "本次生成可以重试" })).toBeVisible();
  await page.getByRole("button", { name: "重新生成" }).click();
  await expect(page).toHaveURL(/\/jobs\/job-new$/);
  await expect(page.getByRole("heading", { name: "任务已提交，等待生成" })).toBeVisible();
});

test("explains an unrecoverable failure without retry", async ({ page }) => {
  await mockSession(page);
  await page.route("**/api/v1/jobs/job-failed", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-failed",
        brief_id: "brief-1",
        brief_revision_id: "revision-2",
        status: "failed",
        stage: "configuration_error",
        progress_percent: 0,
        error_code: "PROVIDER_NOT_CONFIGURED",
        error_message: "模型或搜索服务尚未配置，请联系管理员。",
        report_version_ids: [],
      }),
    });
  });

  await page.goto("/jobs/job-failed");
  await expect(page.getByRole("heading", { name: "需要处理后再重新生成" })).toBeVisible();
  await expect(page.getByText("PROVIDER_NOT_CONFIGURED")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新生成" })).toHaveCount(0);
});

test("keeps report history and navigates immutable versions", async ({ page }) => {
  await mockSession(page);
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
  await page.route("**/api/v1/reports", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ reports: versions }),
    });
  });
  await page.route("**/api/v1/reports/report-*", async (route) => {
    const reportId = new URL(route.request().url()).pathname.endsWith("report-1")
      ? "report-1"
      : "report-2";
    const selected = versions.find((version) => version.report_version_id === reportId)!;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...selected,
        id: reportId,
        brief_revision_id: `revision-${selected.version_number}`,
        available_versions: [...versions].reverse(),
        report_payload: {
          executive_summary: `第 ${selected.version_number} 版执行摘要`,
          strategies: [{ name: "首周里程碑引导", objective: "提升关键行为完成率" }],
          decision_support_notice: "本报告用于决策支持，实际效果需要通过实验验证。",
        },
      }),
    });
  });

  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "新用户留存运营方案" })).toBeVisible();
  await expect(page.getByText("用户留存", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "新用户留存运营方案版本列表" })).toContainText(
    "v1",
  );
  await page.getByRole("link", { name: "阅读最新报告" }).click();
  await expect(page).toHaveURL(/\/reports\/report-2$/);
  await expect(page.getByRole("navigation", { name: "报告目录" })).toBeVisible();
  await expect(page.getByText("第 2 版执行摘要")).toBeVisible();
  await page.getByRole("link", { name: "v1" }).click();
  await expect(page).toHaveURL(/\/reports\/report-1$/);
  await expect(page.getByText("第 1 版执行摘要")).toBeVisible();
});

test("supports keyboard login and responsive accessible report reading", async ({ page }, testInfo) => {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "AUTHENTICATION_REQUIRED", message: "请先登录。" } }),
    });
  });
  await page.goto("/login");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("邮箱")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("密码")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "登录" })).toBeFocused();
  await expectNoSeriousAccessibilityViolations(page);

  await page.unroute("**/api/v1/auth/me");
  await mockSession(page);
  await page.route("**/api/v1/reports/report-accessible", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "report-accessible",
        report_version_id: "report-accessible",
        series_id: "report-accessible",
        job_id: "job-accessible",
        brief_revision_id: "revision-accessible",
        version_number: 1,
        title: "响应式运营策略报告",
        scene: "content",
        delivery_status: "formal",
        generated_at: "2026-10-04T01:00:00Z",
        available_versions: [],
        report_payload: {
          executive_summary: "通过内容供给、分发和转化闭环验证增长机会。",
          strategies: [{ name: "主题矩阵", objective: "稳定高质量内容供给" }],
          decision_support_notice: "本报告用于决策支持，实际效果需要通过实验验证。",
        },
      }),
    });
  });

  for (const viewport of [
    { name: "desktop", width: 1280, height: 800 },
    { name: "mobile", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/reports/report-accessible");
    await expect(page.getByRole("heading", { name: "响应式运营策略报告" })).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
    await expectNoSeriousAccessibilityViolations(page);
    await page.screenshot({
      path: testInfo.outputPath(`report-${viewport.name}.png`),
      fullPage: true,
    });
  }
});
