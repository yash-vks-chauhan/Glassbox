import { expect, test } from "@playwright/test";

import { resetRateLimitBuckets, submitQuestion } from "./helpers";

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
  resetRateLimitBuckets();
});

test("visitors can explore the demo as an advisor and as compliance", async ({ browser, page }) => {
  test.skip(process.env.DEMO_LOGIN_ENABLED !== "1", "needs DEMO_LOGIN_ENABLED on the backend");

  await page.goto("/login");
  await page.getByRole("button", { name: /Try as an advisor/ }).click();
  await expect(page).toHaveURL(/\/app\/clients\/C001\/ask/);
  await expect(page.getByTestId("demo-banner")).toBeVisible();
  await expect(page.getByTestId("sidebar-role-badge")).toHaveText("advisor");
  await submitQuestion(page, "Can client C001 put 40% into fund F100?");
  await expect(page.locator('[data-outcome="flagged"]').first()).toBeVisible({ timeout: 30_000 });

  // A second visitor, in their own browser, takes the compliance seat.
  const otherContext = await browser.newContext();
  const visitor = await otherContext.newPage();
  await visitor.goto("/login");
  await visitor.getByRole("button", { name: /Try as compliance/ }).click();
  await expect(visitor).toHaveURL(/\/app\/review/);
  await expect(visitor.getByTestId("sidebar-role-badge")).toHaveText("compliance");
  await expect(visitor.getByRole("heading", { name: "Review queue" })).toBeVisible();

  // The demo accounts' sign-in settings are fixed.
  await visitor.goto("/app/settings/security");
  await expect(visitor.getByText(/This is a shared demo account/)).toBeVisible();
  await expect(visitor.getByRole("button", { name: /Change password/i })).toHaveCount(0);
  await otherContext.close();
});
