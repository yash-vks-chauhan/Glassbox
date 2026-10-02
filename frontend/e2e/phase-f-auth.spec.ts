import { expect, test } from "@playwright/test";

import {
  createInvite,
  currentTotp,
  fillPrimaryLogin as fillLogin,
  resetRateLimitBuckets,
  seedUsers,
  submitQuestion,
  type Seed,
} from "./helpers";

let seed: Seed;

function sseFinal(payload: unknown) {
  return [
    'event: accepted\ndata: {"status":"accepted"}',
    `event: final\ndata: ${JSON.stringify(payload)}`,
    "",
  ].join("\n\n");
}

function fillPrimaryLogin(page: Parameters<typeof fillLogin>[0], email: string) {
  return fillLogin(page, seed, email);
}

test.beforeAll(() => {
  seed = seedUsers();
});

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
  resetRateLimitBuckets();
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
  await expect(page.getByTestId("runtime-status-pill")).toContainText(
    /Production inference|Local evidence mode|Demo inference|Personal model route|Inference degraded|Model router|Runtime status unavailable|Checking inference route/,
  );

  await page.reload();
  await expect(page).toHaveURL(/\/app\/clients\/C004\/ask/);
  await expect(page.getByLabel("Conversation composer")).toBeVisible();

  await submitQuestion(page, "Can client C004 put 30% into fund F100?");
  await expect(page.getByText(/No\. Do not proceed as proposed/i)).toBeVisible({
    timeout: 30_000,
  });
  await page.getByLabel("Decision trust details").last().click();
  await expect(page.getByText("Runtime", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("Raw route", { exact: true }).last()).toBeVisible();
  await expect(
    page
      .getByText(
        /Private local evidence mode|Demo inference route|Provider model route|Approved router candidate|Safe fallback route|Model route recorded/,
      )
      .last(),
  ).toBeVisible();
  await page.getByRole("button", { name: /Escalate to compliance/i }).click();
  await expect(page.getByText(/Escalated · open/i)).toBeVisible({ timeout: 15_000 });
  const workbench = page.getByRole("main");

  let unavailableAttempts = 0;
  await page.route("**/ask/stream", async (route, request) => {
    if (request.method() !== "POST") {
      await route.fallback();
      return;
    }
    unavailableAttempts += 1;
    if (unavailableAttempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Production inference is blocked: no approved route." }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseFinal({
        decision_id: "e2e-retry-success",
        outcome: "answered",
        answer: "Retry succeeded with cited evidence [1].",
        citations: [{ source_id: "E2E", source_type: "policy", snippet: "Retry evidence." }],
        refusal_reason: null,
        trust: {
          grounding_score: 1,
          determinism_score: null,
          model_route: "local:glassbox-deterministic-fallback",
          retrieval_ms: 1,
          generation_ms: 1,
          verification_ms: 1,
          total_ms: 3,
          evidence_quality: 1,
          cache_hit: false,
        },
      }),
    });
  });
  await submitQuestion(page, "Trigger unavailable model route");
  await expect(workbench.getByText("GlassBox · model route unavailable")).toBeVisible();
  await expect(workbench.getByText(/Production inference is blocked/)).toBeVisible();
  await workbench.getByRole("button", { name: "Retry" }).last().click();
  await expect(page.getByText(/Retry succeeded with cited evidence/i)).toBeVisible();
  await page.unroute("**/ask/stream");

  await page.route("**/ask/stream", async (route) => {
    await route.fulfill({
      status: 429,
      contentType: "application/json",
      headers: {
        "access-control-expose-headers": "Retry-After",
        "retry-after": "7",
      },
      body: JSON.stringify({ detail: "Rate limit exceeded. Please slow down." }),
    });
  });
  await submitQuestion(page, "Trigger rate limit");
  await expect(workbench.getByText("GlassBox · rate limited")).toBeVisible();
  await expect(workbench.getByText(/Retry in about 7 seconds/)).toBeVisible();
  await page.unroute("**/ask/stream");

  await page.route("**/auth/refresh", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Refresh failed." }),
    });
  });
  await page.route("**/ask/stream", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Session expired." }),
    });
  });
  await submitQuestion(page, "Trigger expired session");
  await expect(workbench.getByText("GlassBox · session expired")).toBeVisible();
  await expect(workbench.getByText(/Sign in again, then retry/)).toBeVisible();
  await page.unroute("**/ask/stream");
  await page.unroute("**/auth/refresh");

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
  await expect(page.getByText("Endpoint usable", { exact: true })).toBeVisible();
  await expect(page.getByText("Local evidence engine ready", { exact: true })).toBeVisible();
  await expect(page.getByText("Production mode on", { exact: true })).toBeVisible();
  await expect(page.getByText(/Local evidence mode is ready|Production inference is/i)).toBeVisible();
});

test("advisor direct navigation to admin page is blocked", async ({ page }) => {
  await page.goto("/login?next=%2Fapp%2Fhome");
  await fillPrimaryLogin(page, seed.advisor_email);
  await expect(page).toHaveURL(/\/app\/home/);

  await page.reload();
  await expect(page).toHaveURL(/\/app\/home/);
  await expect(page.getByTestId("sidebar-role-badge")).toHaveText("advisor");

  await page.goto("/app/admin");
  await expect(page.getByRole("heading", { name: "Admin access required" })).toBeVisible();
  await expect(page.getByText(/tenant admins and owners/i)).toBeVisible();
});

const INVITE_MFA_KEY = "glassbox.pending_invite_mfa";
const INVITE_PASSWORD = "Invited-Sup3rSecur3!";

async function acceptInvite(page: Parameters<typeof fillLogin>[0], token: string) {
  await page.goto(`/accept-invite/${token}`);
  await page.getByLabel("Display name (optional)").fill("Invited Admin");
  await page.getByLabel("Password", { exact: true }).fill(INVITE_PASSWORD);
  await page.getByLabel("Confirm password").fill(INVITE_PASSWORD);
  await page.getByRole("button", { name: /Create account/ }).click();
  await expect(page).toHaveURL(new RegExp(`/accept-invite/${token}/mfa$`));
}

test("an invited admin enrols MFA while accepting the invitation", async ({ page }) => {
  const token = createInvite("admin");

  // Without a pending enrolment, the MFA step sends you back to the invitation.
  await page.goto(`/accept-invite/${token}/mfa`);
  await expect(page).toHaveURL(new RegExp(`/accept-invite/${token}$`));

  await acceptInvite(page, token);
  await page.getByText("Can't scan? Enter this setup key manually").click();
  const secret = (await page.getByTestId("mfa-setup-key").textContent())?.trim() ?? "";
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/);

  await page.getByLabel("Authenticator code").fill(currentTotp(secret));
  await page.getByRole("button", { name: /Verify and finish/ }).click();

  await expect(page.getByText("MFA enrolled")).toBeVisible();
  await expect(page.locator("ul li")).not.toHaveCount(0);
  // The single-show secret doesn't outlive enrolment.
  expect(await page.evaluate((key) => sessionStorage.getItem(key), INVITE_MFA_KEY)).toBeNull();

  await page.getByRole("button", { name: /Continue to GlassBox/ }).click();
  await expect(page).toHaveURL(/\/app/);
  await expect(page.getByTestId("sidebar-role-badge")).toHaveText("admin");
});

test("an expired MFA enrolment asks for a fresh invitation", async ({ page }) => {
  const token = createInvite("admin");
  await acceptInvite(page, token);
  await expect(page.getByLabel("Authenticator code")).toBeVisible();

  await page.evaluate((key) => {
    const pending = JSON.parse(sessionStorage.getItem(key) ?? "{}");
    pending.created_at = Date.now() - 10 * 60 * 1000;
    sessionStorage.setItem(key, JSON.stringify(pending));
  }, INVITE_MFA_KEY);
  await page.reload();

  await expect(
    page.getByRole("alert").filter({ hasText: "Your enrolment session expired" }),
  ).toHaveText("Your enrolment session expired. Ask for a fresh invitation.");
  await expect(page.getByLabel("Authenticator code")).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/accept-invite/${token}/mfa$`));
  expect(await page.evaluate((key) => sessionStorage.getItem(key), INVITE_MFA_KEY)).toBeNull();
});

// Set on the backend under test (CI does) to exercise first-run setup.
const SETUP_KEY = process.env.BOOTSTRAP_SETUP_KEY ?? "";

async function startSetup(page: Parameters<typeof fillLogin>[0], workspace: string, email: string) {
  await page.goto("/setup");
  await page.getByLabel("Setup key", { exact: true }).fill(SETUP_KEY);
  await page.getByLabel("Workspace name").fill(workspace);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(INVITE_PASSWORD);
  await page.getByLabel("Confirm password").fill(INVITE_PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
}

test("first-run setup creates a workspace owner with MFA", async ({ page }) => {
  test.skip(!SETUP_KEY, "needs BOOTSTRAP_SETUP_KEY on the backend");
  const id = Math.random().toString(36).slice(2, 8);
  const workspace = `E2E Firm ${id}`;

  await startSetup(page, workspace, `e2e-owner-${id}@example.com`);
  await page.getByText("Can't scan? Enter this setup key manually").click();
  const secret = (await page.getByTestId("mfa-setup-key").textContent())?.trim() ?? "";
  await page.getByLabel("Authenticator code").fill(currentTotp(secret));
  await page.getByRole("button", { name: /Verify and finish/ }).click();

  await expect(page.getByText("Owner account ready")).toBeVisible();
  await expect(page.getByText(`e2e-firm-${id}`)).toBeVisible();
  await page.getByRole("button", { name: /Continue to GlassBox/ }).click();
  await expect(page).toHaveURL(/\/app/);
  await expect(page.getByTestId("sidebar-role-badge")).toHaveText("owner");

  // Once the workspace has an owner, setup is closed for it.
  await startSetup(page, workspace, `e2e-late-${id}@example.com`);
  await expect(
    page.getByRole("alert").filter({ hasText: "already has an owner" }),
  ).toBeVisible();
});
