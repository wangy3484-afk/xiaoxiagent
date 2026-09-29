import { expect, test } from "@playwright/test";

test("opens the report workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "专业运营策略 Agent" })).toBeVisible();

  await page.getByRole("link", { name: "查看报告工作台" }).click();
  await expect(page).toHaveURL(/\/reports$/);
  await expect(page.getByRole("heading", { name: "报告工作台" })).toBeVisible();
});
