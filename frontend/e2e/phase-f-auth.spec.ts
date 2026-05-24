import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

type Seed = {
  tenant_slug: string;
  password: string;
  advisor_email: string;
  admin_email: string;
  admin_mfa_secret: string;
};

const repoRoot = path.resolve(__dirname, "../..");
const backendDir = path.join(repoRoot, "backend");
const python = process.env.PYTHON ?? path.join(repoRoot, ".venv/bin/python");

let seed: Seed;

function runPython(args: string[]) {
  return execFileSync(python, args, {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: "." },
    encoding: "utf8",
  }).trim();
}

function currentTotp(secret: string) {
  return runPython([
    "-c",
    "import pyotp, sys; print(pyotp.TOTP(sys.argv[1]).now())",
    secret,
  ]);
}

async function fillPrimaryLogin(page: Page, email: string) {
  await page.getByLabel("Workspace").fill(seed.tenant_slug);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(seed.password);
  await page.getByRole("button", { name: /Continue to workbench/i }).click();
}

test.beforeAll(() => {
  seed = JSON.parse(runPython(["scripts/seed_phase_f_e2e.py"])) as Seed;
});

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

test("unauthenticated app navigation redirects to real login", async ({ page }) => {
  await page.goto("/app/home");
  await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fhome/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("advisor login reaches workbench, hides admin, refreshes silently, and logs out", async ({
  page,
}) => {
  await page.goto("/login?next=%2Fapp%2Fclients%2FC004%2Fask");
  await fillPrimaryLogin(page, seed.advisor_email);

  await expect(page).toHaveURL(/\/app\/clients\/C004\/ask/);
  await expect(page.getByTestId("sidebar-role-badge")).toHaveText("advisor");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  await page.reload();
  await expect(page).toHaveURL(/\/app\/clients\/C004\/ask/);
  await expect(page.getByLabel("Conversation composer")).toBeVisible();

  await page.getByLabel("Conversation composer").fill("Can client C004 put 30% into fund F100?");
  await page.getByLabel("Conversation composer").press("Enter");
  await expect(page.getByText(/No\. I would not proceed/i)).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: /Escalate to compliance/i }).click();
  await expect(page.getByText(/Escalated · open/i)).toBeVisible({ timeout: 15_000 });

  await page.getByTestId("account-menu").click();
  await page.getByTestId("sign-out-action").click();
  await expect(page).toHaveURL(/\/login/);
});

test("admin login uses MFA page and shows users plus audit verify cards", async ({ page }) => {
  await page.goto("/login?next=%2Fapp%2Fadmin");
  await fillPrimaryLogin(page, seed.admin_email);

  await expect(page).toHaveURL(/\/login\/mfa/);
  await page.getByLabel("Authenticator or recovery code").fill(currentTotp(seed.admin_mfa_secret));
  await page.getByRole("button", { name: "Verify" }).click();

  await expect(page).toHaveURL(/\/app\/admin/);
  await expect(page.getByTestId("sidebar-role-badge")).toHaveText("admin");
  await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible();
  await expect(page.getByText("Users", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit verify", { exact: true })).toBeVisible();
  await expect(page.getByText("Production model setup", { exact: true })).toBeVisible();
  await expect(page.getByText(/Production inference is/i)).toBeVisible();
});

test("advisor direct navigation to admin page is blocked", async ({ page }) => {
  await page.goto("/login?next=%2Fapp%2Fhome");
  await fillPrimaryLogin(page, seed.advisor_email);
  await expect(page).toHaveURL(/\/app\/home/);

  await page.goto("/app/admin");
  await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
  await expect(page.getByText(/tenant admins and owners/i)).toBeVisible();
});
