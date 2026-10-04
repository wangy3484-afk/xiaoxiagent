import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import App from "./App";

describe("App", () => {
  it("renders the decision-support home page", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: { code: "AUTHENTICATION_REQUIRED" } }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "专业运营策略 Agent" })).toBeInTheDocument();
    expect(screen.getByLabelText("数据使用提醒")).toBeInTheDocument();
  });
});
