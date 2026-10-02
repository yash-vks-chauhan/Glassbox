import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
  loginAsAdmin,
  loginAsAdvisor,
  resetRateLimitBuckets,
  runPython,
  seedUsers,
  submitQuestion,
} from "../e2e/helpers";

const outDir = path.resolve(__dirname, "../../docs/screenshots");

async function shoot(page: Page, name: string) {
  // Let toasts clear and fonts, charts and smooth scrolling settle.
  await expect(page.locator("[data-sonner-toast]")).toHaveCount(0, { timeout: 15_000 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(outDir, `${name}.png`) });
}

async function ask(page: Page, question: string) {
  const answers = page.locator("article[data-outcome]");
  const before = await answers.count();
  await submitQuestion(page, question);
  await expect(answers).toHaveCount(before + 1);
}

test("capture the README screenshots", async ({ browser, page }) => {
  const seed = seedUsers();
  resetRateLimitBuckets();

  await page.goto("/");
  await shoot(page, "landing");

  // An advisor works a few real questions, so the dashboards have data.
  await loginAsAdvisor(page, seed, "/app/clients/C002/ask");
  await ask(page, "Can client C002 invest in cryptocurrency?");
  await ask(page, "Does fund F200 have low risk?");
  await page.goto("/app/clients/C001/ask");
  await ask(page, "Can client C001 put 40% into fund F100?");
  await shoot(page, "ask");

  await page.getByRole("button", { name: /Escalate to compliance/i }).last().click();
  await expect(page.getByText(/Escalated · open/i).last()).toBeVisible();
  const replayHref = await page.getByRole("link", { name: /Open replay/i }).last().getAttribute("href");
  const decisionId = replayHref!.split("/").pop()!;
  await ask(page, "What is the capital gains tax rate in Germany?");
  await shoot(page, "refusal");

  await page.goto(`/app/audit/${decisionId}`);
  await expect(page.getByRole("main").getByText(/single-position/i).first()).toBeVisible();
  await shoot(page, "audit-replay");

  // A measured determinism run for the dashboards (no decisions recorded).
  runPython([
    "-c",
    [
      "from app.core.determinism import run_now",
      "from app.db import SessionLocal",
      "from app.models_db import DEMO_TENANT_ID",
      "db = SessionLocal()",
      "run_now(db, tenant_id=DEMO_TENANT_ID, user_id=None, runs_per_question=3, sample_size=5)",
      "db.close()",
    ].join("; "),
  ]);

  // Compliance (the admin here: four-eyes) reviews it.
  const reviewerContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const reviewer = await reviewerContext.newPage();
  await loginAsAdmin(reviewer, seed, `/app/review/${decisionId}`);
  await expect(reviewer.getByRole("main").getByText("Reviewing decision")).toBeVisible();
  await reviewer.getByRole("button", { name: "Supported" }).first().click();
  await reviewer.getByLabel("Notes").fill("Concur: the 25% single-position cap applies.");
  await shoot(reviewer, "review");

  await reviewer.goto("/app/insights");
  await expect(reviewer.getByText("Refusal rate")).toBeVisible();
  await shoot(reviewer, "insights");

  await reviewer.goto("/app/audit");
  await expect(reviewer.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await shoot(reviewer, "audit-log");

  await reviewer.goto("/app/admin");
  await expect(reviewer.getByText("Audit verify", { exact: true })).toBeVisible();
  await shoot(reviewer, "admin");
  await reviewerContext.close();
});
