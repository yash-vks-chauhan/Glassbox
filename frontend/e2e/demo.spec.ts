import { expect, test, type Page } from "@playwright/test";

const clientId = "C001";
const clientPath = `/app/clients/${clientId}/ask`;

async function ask(page: Page, question: string) {
  if (!page.url().endsWith(clientPath)) {
    await page.goto(clientPath);
  }
  const composer = page.getByLabel("Conversation composer");
  await composer.fill(question);
  await composer.press("Enter");
  await expect(page.getByRole("link", { name: /Open replay/i }).first()).toBeVisible({
    timeout: 30_000,
  });
}

test("workbench covers mandate breach, suitability, refusal, audit, and dashboard", async ({
  page,
}) => {
  await page.goto(clientPath);
  await expect(page.getByText(/Ask anything within/i)).toBeVisible();

  await ask(page, "Can client C001 put 40% into fund F100?");
  await expect(page.locator('[data-outcome="flagged"]').first()).toBeVisible({
    timeout: 30_000,
  });

  await ask(page, "Is fund F100 suitable for client C001?");
  await expect(
    page.locator('[data-outcome="answered"], [data-outcome="fallback"]').first(),
  ).toBeVisible({ timeout: 30_000 });

  await ask(page, "What is the capital gains tax rate in Germany?");
  await expect(page.locator('[data-outcome="refused"]').first()).toBeVisible({
    timeout: 30_000,
  });

  await page.goto("/app/insights");
  await expect(page.getByRole("heading", { name: "Insights" })).toBeVisible();

  await page.goto("/app/audit");
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();

  await page.goto("/app/review");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
});
