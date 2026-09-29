import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import App from "./App";

describe("App", () => {
  it("renders the decision-support home page", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "专业运营策略 Agent" })).toBeInTheDocument();
    expect(screen.getByLabelText("数据使用提醒")).toBeInTheDocument();
  });
});
