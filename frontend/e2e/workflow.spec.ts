import { expect, test } from "@playwright/test";

import {
  loginAsAdmin,
  loginAsAdvisor,
  resetRateLimitBuckets,
  seedUsers,
  submitQuestion,
  type Seed,
} from "./helpers";

let seed: Seed;

test.beforeAll(() => {
  seed = seedUsers();
});

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
  resetRateLimitBuckets();
});

test("a thread keeps its context across follow-ups and reloads", async ({ page }) => {
  await loginAsAdvisor(page, seed, "/app/clients/C001/ask");

  await submitQuestion(page, "Can client C001 put 40% into fund F100?");
  await expect(page.locator('[data-outcome="flagged"]').first()).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(/thread=/);

  await submitQuestion(page, "What about F200?");
  await expect(
    page.getByText("Can client C001 put 40% into fund F200?", { exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  // The conversation is stored, not held in memory.
  await page.reload();
  await expect(page.getByText("What about F200?", { exact: true })).toBeVisible();
  await expect(page.getByText(/Answered as:/)).toBeVisible();

  await page.goto("/app/threads");
  await expect(
    page.getByText("Can client C001 put 40% into fund F100?", { exact: true }).first(),
  ).toBeVisible();
});

test("compliance reviews an escalated decision and exports the audit binder", async ({
  browser,
  page,
}) => {
  // Advisor asks and escalates.
  await loginAsAdvisor(page, seed, "/app/clients/C001/ask");
  await submitQuestion(page, "Can client C001 put 40% into fund F100?");
  await expect(page.locator('[data-outcome="flagged"]').first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: /Escalate to compliance/i }).last().click();
  await expect(page.getByText(/Escalated · open/i).last()).toBeVisible({ timeout: 15_000 });
  const replayHref = await page.getByRole("link", { name: /Open replay/i }).last().getAttribute("href");
  const decisionId = replayHref!.split("/").pop()!;

  // A reviewer (the admin, a different person: four-eyes) works the queue.
  const reviewerContext = await browser.newContext();
  const reviewer = await reviewerContext.newPage();
  await loginAsAdmin(reviewer, seed, "/app/review");
  // Open this decision's row in the queue (earlier runs may have left others).
  await reviewer.locator(`a[href="/app/review/${decisionId}"]`).first().click();
  await expect(reviewer.getByRole("main").getByText("Reviewing decision")).toBeVisible();
  await reviewer.getByRole("button", { name: "Supported" }).first().click();
  await reviewer.getByLabel("Notes").fill("Concur: the 25% single-position cap applies.");
  await reviewer.getByRole("button", { name: "Submit review" }).click();
  await expect(reviewer.getByText("Review saved")).toBeVisible();
  await expect(reviewer.getByText("Review history")).toBeVisible();
  await expect(reviewer.getByText("Concur: the 25% single-position cap applies.")).toBeVisible();

  // The binder downloads as a real PDF.
  await reviewer.goto("/app/audit?range=24h");
  const download = reviewer.waitForEvent("download");
  await reviewer.getByRole("button", { name: "PDF binder" }).click();
  expect((await download).suggestedFilename()).toMatch(/^glassbox-audit-binder-.*\.pdf$/);
  await reviewerContext.close();
});
