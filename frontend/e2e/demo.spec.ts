import { expect, test, type Page } from "@playwright/test";

import { loginAsAdmin, resetRateLimitBuckets, seedUsers, submitQuestion, type Seed } from "./helpers";

const clientPath = "/app/clients/C001/ask";

let seed: Seed;

test.beforeAll(() => {
  seed = seedUsers();
});

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
  resetRateLimitBuckets();
});

/** Ask, wait for the new answer, and check how the UI classified it. */
async function ask(page: Page, question: string, outcomes: string[], expectText: RegExp) {
  const answers = page.locator("article[data-outcome]");
  const before = await answers.count();
  await submitQuestion(page, question);
  await expect(answers).toHaveCount(before + 1, { timeout: 30_000 });
  const latest = answers.nth(before);
  await expect(latest).toContainText(expectText);
  expect(outcomes).toContain(await latest.getAttribute("data-outcome"));
}

test("workbench covers mandate breach, suitability, refusal, audit, and insights", async ({
  page,
}) => {
  // The full tour includes compliance pages, so it runs as the seeded admin.
  await loginAsAdmin(page, seed, clientPath);
  await expect(page.getByText(/Ask anything within/i)).toBeVisible();

  await ask(page, "Can client C001 put 40% into fund F100?", ["flagged"], /single-position limit/);
  await expect(page).toHaveURL(/thread=/);
  // A high-risk fund for a moderate client: answered with cited evidence,
  // shown as flagged because it asks for review before recommending.
  await ask(
    page,
    "Is fund F100 suitable for client C001?",
    ["answered", "flagged"],
    /Suitability stance/,
  );
  await ask(
    page,
    "What is the capital gains tax rate in Germany?",
    ["refused"],
    /approved corpus does not contain/,
  );

  await page.goto("/app/insights");
  await expect(page.getByRole("heading", { name: "Insights" })).toBeVisible();
  await expect(page.getByText("Refusal rate")).toBeVisible();
  await expect(page.getByRole("main").getByText(/targets met/)).toBeVisible();

  await page.goto("/app/audit");
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await expect(page.getByText("What is the capital gains tax rate in Germany?").first()).toBeVisible();

  await page.goto("/app/review");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();

  await page.goto("/app/library");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await page.getByText("Global Emerging Markets Equity Fund (F100)").click();
  await expect(page.getByText(/Indexed passages/)).toBeVisible();
});
