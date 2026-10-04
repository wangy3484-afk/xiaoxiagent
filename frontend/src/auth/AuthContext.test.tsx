import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import App from "../App";

const account = { id: "user-1", email: "operator@example.com" };

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("authentication workflow", () => {
  it("restores an existing session before showing the protected workspace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(account));
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/reports");

    expect(screen.getByRole("heading", { name: "正在恢复登录状态" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "报告工作台" })).toBeInTheDocument();
    expect(screen.getByText(account.email)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("logs in successfully and returns to the originally requested page", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/auth/me")) {
        return Promise.resolve(
          jsonResponse(
            { detail: { code: "AUTHENTICATION_REQUIRED", message: "请先登录。" } },
            401,
          ),
        );
      }
      if (String(input).endsWith("/auth/login") && init?.method === "POST") {
        return Promise.resolve(jsonResponse(account));
      }
      throw new Error(`unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAt("/reports");

    expect(await screen.findByRole("heading", { name: "账号登录" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("登录状态已失效");
    await user.type(screen.getByLabelText("邮箱"), account.email);
    await user.type(screen.getByLabelText("密码"), "correct-horse-battery-staple");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("heading", { name: "报告工作台" })).toBeInTheDocument();
    expect(screen.getByText(account.email)).toBeInTheDocument();
  });

  it("shows the safe API error when credentials are invalid", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse({ detail: {} }, 401));
      }
      return Promise.resolve(
        jsonResponse(
          { detail: { code: "INVALID_CREDENTIALS", message: "邮箱或密码错误。" } },
          401,
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAt("/login");

    await screen.findByRole("heading", { name: "账号登录" });
    await user.type(screen.getByLabelText("邮箱"), account.email);
    await user.type(screen.getByLabelText("密码"), "wrong-password-long-enough");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("邮箱或密码错误");
    expect(screen.queryByRole("heading", { name: "报告工作台" })).not.toBeInTheDocument();
  });

  it("logs out and prevents returning to the protected page", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return Promise.resolve(jsonResponse(account));
      if (path.endsWith("/auth/logout") && init?.method === "POST") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAt("/reports");

    await screen.findByRole("heading", { name: "报告工作台" });
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "账号登录" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("heading", { name: "报告工作台" })).not.toBeInTheDocument();
  });
});
