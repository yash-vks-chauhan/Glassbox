import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export type Seed = {
  tenant_slug: string;
  password: string;
  advisor_email: string;
  admin_email: string;
  admin_mfa_secret: string;
};

const repoRoot = path.resolve(__dirname, "../..");
const backendDir = path.join(repoRoot, "backend");
const python = process.env.PYTHON ?? path.join(repoRoot, ".venv/bin/python");

/** Run Python in the backend directory with the same environment (and so
 * the same DATABASE_URL) as the backend under test. */
export function runPython(args: string[]) {
  return execFileSync(python, args, {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: "." },
    encoding: "utf8",
  }).trim();
}

/** The e2e advisor and MFA-enrolled admin accounts. Seeded once by
 * global-setup.ts; falls back to seeding here when run without it. */
export function seedUsers(): Seed {
  const raw = process.env.E2E_SEED ?? runPython(["scripts/seed_phase_f_e2e.py"]);
  return JSON.parse(raw) as Seed;
}

export function currentTotp(secret: string) {
  return runPython([
    "-c",
    "import pyotp, sys; print(pyotp.TOTP(sys.argv[1]).now())",
    secret,
  ]);
}

export function resetRateLimitBuckets() {
  runPython([
    "-c",
    [
      "from sqlalchemy import delete",
      "from app.db import SessionLocal",
      "from app.models_db import RateLimitBucket",
      "db = SessionLocal()",
      "db.execute(delete(RateLimitBucket))",
      "db.commit()",
      "db.close()",
    ].join("; "),
  ]);
}

export async function fillPrimaryLogin(page: Page, seed: Seed, email: string) {
  await page.getByLabel("Workspace").fill(seed.tenant_slug);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(seed.password);
  await page.getByRole("button", { name: /Continue to workbench/i }).click();
}

/** Sign in as the seeded advisor and land on `next`. */
export async function loginAsAdvisor(page: Page, seed: Seed, next: string) {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await fillPrimaryLogin(page, seed, seed.advisor_email);
  await expect(page).toHaveURL(new RegExp(next.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
}

/** Sign in as the seeded admin, completing the TOTP step, and land on `next`. */
export async function loginAsAdmin(page: Page, seed: Seed, next: string) {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await fillPrimaryLogin(page, seed, seed.admin_email);
  await expect(page).toHaveURL(/\/login\/mfa/);
  await page.getByLabel("Authenticator or recovery code").fill(currentTotp(seed.admin_mfa_secret));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(new RegExp(next.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
}

export async function submitQuestion(page: Page, question: string) {
  const composer = page.getByLabel("Conversation composer");
  await composer.fill(question);
  await composer.press("Enter");
}
