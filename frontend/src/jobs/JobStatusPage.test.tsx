import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { JobStatusPage, type JobStatusResponse } from "./JobStatusPage";

function job(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    id: "job-1",
    brief_id: "brief-1",
    brief_revision_id: "revision-2",
    status: "running",
    stage: "research",
    progress_percent: 25,
    error_code: null,
    error_message: null,
    report_version_ids: [],
    ...overrides,
  };
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function LocationProbe() {
  return <output aria-label="current path">{useLocation().pathname}</output>;
}

function renderJobPage() {
  return render(
    <MemoryRouter initialEntries={["/jobs/job-1"]}>
      <Routes>
        <Route
          path="/jobs/:jobId"
          element={
            <>
              <JobStatusPage pollIntervalMs={5} />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

it("restores a running task from its URL and polls until completion", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response(job()))
    .mockResolvedValueOnce(
      response(
        job({
          status: "completed",
          stage: "completed",
          progress_percent: 100,
          report_version_ids: ["report-1"],
        }),
      ),
    );
  vi.stubGlobal("fetch", fetchMock);

  renderJobPage();

  expect(await screen.findByRole("heading", { name: "正在研究头部公司与相似案例" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "报告已生成" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看报告" })).toHaveAttribute(
    "href",
    "/reports/report-1",
  );
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("explains a retryable failure and creates a new job", async () => {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/jobs/job-1")) {
      return Promise.resolve(
        response(
          job({
            status: "retryable",
            stage: "retryable_error",
            error_code: "PROVIDER_RATE_LIMITED",
            error_message: "外部服务暂时不可用，可稍后重新生成。",
          }),
        ),
      );
    }
    if (path.endsWith("/jobs") && init?.method === "POST") {
      return Promise.resolve(response({ id: "job-2", status: "queued", stage: "queued" }, 202));
    }
    if (path.endsWith("/jobs/job-2")) {
      return Promise.resolve(response(job({ id: "job-2", status: "queued", stage: "queued", progress_percent: 0 })));
    }
    throw new Error(`unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderJobPage();

  expect(await screen.findByRole("heading", { name: "本次生成可以重试" })).toBeInTheDocument();
  expect(screen.getByText("PROVIDER_RATE_LIMITED")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新生成" }));

  expect(await screen.findByLabelText("current path")).toHaveTextContent("/jobs/job-2");
  const createCall = fetchMock.mock.calls.find(
    ([path, init]) => String(path).endsWith("/jobs") && init?.method === "POST",
  );
  expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
    brief_id: "brief-1",
    brief_revision_id: "revision-2",
  });
});

it("shows an unrecoverable failure without a retry action", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response(
        job({
          status: "failed",
          stage: "configuration_error",
          error_code: "PROVIDER_NOT_CONFIGURED",
          error_message: "模型或搜索服务尚未配置，请联系管理员。",
        }),
      ),
    ),
  );
  renderJobPage();

  expect(await screen.findByRole("heading", { name: "需要处理后再重新生成" })).toBeInTheDocument();
  expect(screen.getByText("模型或搜索服务尚未配置，请联系管理员。")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新生成" })).not.toBeInTheDocument();
});
