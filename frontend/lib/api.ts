/**
 * Phase F API client.
 *
 * Two big shifts from the Phase B/D shape:
 *
 * 1. The access token is **in memory only** (module-scope variable). Storing
 *    it in localStorage made the demo simpler but exposes it to any script
 *    that runs on the page. The refresh cookie does the durable work — it's
 *    `HttpOnly; SameSite=Lax` and scoped to /auth, so JS can't touch it.
 *
 * 2. `request()` automatically:
 *      a. Attaches `Authorization: Bearer <access>` when available.
 *      b. On 401, runs a **single in-flight** `/auth/refresh` and retries
 *         the original call once. A second 401 means the refresh cookie is
 *         dead — we clear local state and surface a typed `UnauthorizedError`
 *         so AuthProvider can redirect to /login.
 *
 *    "Single in-flight" is the important bit: if ten widgets each fire a
 *    request and they all 401 at the same instant, only one `/auth/refresh`
 *    goes out and the others await its result. Without that we'd spam the
 *    rate-limited /auth tier and burn the refresh family on a race.
 */

export type Citation = {
  source_id: string;
  source_type: string;
  snippet: string;
};

export type Trust = {
  grounding_score: number | null;
  determinism_score: number | null;
  model_route?: string | null;
  retrieval_ms?: number | null;
  generation_ms?: number | null;
  verification_ms?: number | null;
  total_ms?: number | null;
  evidence_quality?: number | null;
  cache_hit?: boolean;
};

export type AskResponse = {
  decision_id: string;
  outcome: "answered" | "flagged" | "refused" | "fallback";
  answer: string | null;
  citations: Citation[];
  refusal_reason: string | null;
  trust: Trust;
};

export type MetricsSummary = {
  total: number;
  hallucination_rate: number;
  refusal_rate: number;
  flagged_rate: number;
  avg_determinism: number | null;
  audit_completeness: number;
};

export type AuditDetail = {
  id: string;
  created_at: string;
  question: string;
  client_id: string | null;
  outcome: string;
  final_answer: string | null;
  grounding_score: number | null;
  determinism_score: number | null;
  latency_ms: number;
  retrieved_chunks: Array<{
    source_id: string;
    source_type: string;
    chunk_text: string;
    score: number;
    file?: string | null;
    chunk_index?: number | null;
    source_version?: string | null;
    selected_reason?: string | null;
  }>;
  decision_claims: Array<{
    claim_text: string;
    cited_source_id: string | null;
    verified: boolean;
    kept: boolean;
  }>;
};

export type AuditSummary = Omit<AuditDetail, "final_answer" | "retrieved_chunks" | "decision_claims">;

export type AuditVerifyReport = {
  tenant_id: string;
  ok: boolean;
  total: number;
  verified: number;
  first_break_decision_id: string | null;
  first_break_reason: string | null;
  tail_hash: string | null;
};

export type EscalationEvent = {
  id: string;
  action: string;
  actor_user_id: string;
  from_status: string | null;
  to_status: string | null;
  note: string | null;
  created_at: string;
};

export type Escalation = {
  id: string;
  decision_id: string;
  client_id: string | null;
  question: string | null;
  decision_outcome: string | null;
  decision_created_at: string | null;
  grounding_score: number | null;
  latency_ms: number | null;
  status: "open" | "in_review" | "resolved" | "cancelled";
  priority: "normal" | "high" | string;
  reason: string;
  note: string | null;
  assigned_role: string;
  assigned_to_user_id: string | null;
  created_by_user_id: string;
  sla_due_at: string;
  created_at: string;
  updated_at: string;
  events: EscalationEvent[];
};

export type MeResponse = {
  user_id: string;
  tenant_id: string;
  tenant_slug: string;
  email: string;
  role: "owner" | "admin" | "compliance" | "advisor";
  mfa_enrolled: boolean;
};

const DEFAULT_API_BASE = "http://localhost:8000";

function getApiBase() {
  if (typeof window !== "undefined") {
    return process.env.NEXT_PUBLIC_API_BASE || DEFAULT_API_BASE;
  }
  return (
    process.env.BACKEND_API_BASE ||
    process.env.FRONTEND_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    DEFAULT_API_BASE
  );
}

// ---------------------------------------------------------------------------
// Access-token state (in-memory only)
// ---------------------------------------------------------------------------

let accessToken: string | null = null;
const tokenListeners = new Set<(token: string | null) => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
  Array.from(tokenListeners).forEach((listener) => listener(token));
}

export function subscribeAccessToken(listener: (token: string | null) => void) {
  tokenListeners.add(listener);
  return () => tokenListeners.delete(listener);
}

export function clearAccessToken() {
  setAccessToken(null);
}

// ---------------------------------------------------------------------------
// Typed errors so AuthProvider / route guards can react cleanly
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? (typeof detail === "string" ? detail : `Request failed with ${status}`));
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
}

export class UnauthorizedError extends ApiError {
  constructor(detail?: unknown) {
    super(401, detail ?? "Unauthorized", "Session expired. Please sign in again.");
    this.name = "UnauthorizedError";
  }
}

export class MfaRequiredError extends ApiError {
  reason: "mfa_required" | "mfa_enrollment_required";
  mfaToken: string | null;
  constructor(
    reason: "mfa_required" | "mfa_enrollment_required",
    detail?: string | null,
    mfaToken?: string | null,
  ) {
    super(202, detail ?? reason, detail ?? reason);
    this.reason = reason;
    this.mfaToken = mfaToken ?? null;
    this.name = "MfaRequiredError";
  }
}

export class RateLimitedError extends ApiError {
  retryAfter: number;
  constructor(retryAfter: number, detail?: unknown) {
    super(429, detail, "Too many requests. Try again shortly.");
    this.retryAfter = retryAfter;
    this.name = "RateLimitedError";
  }
}

// ---------------------------------------------------------------------------
// Refresh-in-flight singleton
// ---------------------------------------------------------------------------

let refreshInFlight: Promise<string | null> | null = null;

async function performRefresh(): Promise<string | null> {
  try {
    const response = await fetch(`${getApiBase()}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "content-type": "application/json" },
    });
    if (!response.ok) {
      clearAccessToken();
      return null;
    }
    const body = (await response.json()) as RefreshResponse;
    setAccessToken(body.access_token);
    return body.access_token;
  } catch {
    clearAccessToken();
    return null;
  }
}

function refreshOnce(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = performRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

// ---------------------------------------------------------------------------
// request()
// ---------------------------------------------------------------------------

function buildHeaders(initHeaders: HeadersInit | undefined, token: string | null): Headers {
  const headers = new Headers(initHeaders);
  if (!headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (token && !headers.has("authorization")) {
    headers.set("authorization", `Bearer ${token}`);
  }
  return headers;
}

async function readErrorDetail(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

type RequestOptions = {
  // If true, skip the refresh-retry loop and surface 401s directly. Used
  // by the auth endpoints themselves to avoid recursion (refresh-on-refresh).
  skipAuthRefresh?: boolean;
};

export async function request<T>(
  path: string,
  init?: RequestInit & RequestOptions,
): Promise<T> {
  const { skipAuthRefresh, ...fetchInit } = init ?? {};
  const url = `${getApiBase()}${path}`;
  const doFetch = (token: string | null) =>
    fetch(url, {
      ...fetchInit,
      credentials: "include",
      cache: "no-store",
      headers: buildHeaders(fetchInit.headers, token),
    });

  let response = await doFetch(getAccessToken());

  if (response.status === 401 && !skipAuthRefresh) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      response = await doFetch(refreshed);
    }
    if (response.status === 401) {
      clearAccessToken();
      throw new UnauthorizedError(await readErrorDetail(response));
    }
  }

  if (response.status === 429) {
    const retry = parseInt(response.headers.get("retry-after") ?? "1", 10);
    throw new RateLimitedError(Number.isFinite(retry) ? retry : 1, await readErrorDetail(response));
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new ApiError(response.status, detail);
  }

  // 204 / empty body — return undefined cast to T so callers don't need to
  // special-case void endpoints.
  if (response.status === 204) return undefined as unknown as T;
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Auth surface
// ---------------------------------------------------------------------------

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};

export type RefreshResponse = LoginResponse;

export type MfaChallengeResponse = {
  status: "mfa_required" | "mfa_enrollment_required";
  detail: string | null;
  mfa_token: string | null;
};

type LoginInput = {
  email?: string | null;
  password?: string | null;
  tenant_slug?: string | null;
  mfa_code?: string | null;
  mfa_token?: string | null;
};

/**
 * POST /auth/login.
 *
 * Returns:
 *  - LoginResponse on success (and stores the access token in memory).
 *  - throws `MfaRequiredError` when the backend signals an MFA step.
 *  - throws `ApiError` (status 401/423) for invalid creds / lockout.
 */
export async function login(input: LoginInput): Promise<LoginResponse> {
  const response = await fetch(`${getApiBase()}/auth/login`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  // 202 — MFA challenge. The body tells us which kind.
  if (response.status === 202) {
    const body = (await response.json()) as MfaChallengeResponse;
    throw new MfaRequiredError(body.status, body.detail, body.mfa_token);
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }
  const body = (await response.json()) as LoginResponse;
  setAccessToken(body.access_token);
  return body;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${getApiBase()}/auth/logout`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
    });
  } finally {
    clearAccessToken();
  }
}

export function me(): Promise<MeResponse> {
  return request<MeResponse>("/auth/me");
}

export function bootstrapSession(): Promise<MeResponse | null> {
  // Called once on page load to discover if an existing refresh cookie can
  // mint a fresh access token. Quiet on failure — most users aren't logged in.
  return refreshOnce().then((token) => {
    if (!token) return null;
    return me().catch(() => null);
  });
}

export function forgotPassword(email: string, tenant_slug?: string | null) {
  return request<{ status: "ok" }>("/auth/forgot", {
    method: "POST",
    skipAuthRefresh: true,
    body: JSON.stringify({ email, tenant_slug: tenant_slug ?? null }),
  });
}

export function resetPassword(token: string, newPassword: string) {
  return request<void>("/auth/reset", {
    method: "POST",
    skipAuthRefresh: true,
    body: JSON.stringify({ token, new_password: newPassword }),
  });
}

export function acceptInvite(token: string, password: string, displayName?: string) {
  return request<{ status: "created"; user_id: string }>("/auth/accept-invite", {
    method: "POST",
    skipAuthRefresh: true,
    body: JSON.stringify({ token, password, display_name: displayName ?? null }),
  });
}

export function enrollMfa() {
  return request<{ secret: string; provisioning_uri: string }>("/auth/mfa/enroll", {
    method: "POST",
  });
}

export function verifyMfa(code: string) {
  return request<{ recovery_codes: string[] }>("/auth/mfa/verify", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export function inviteUser(email: string, role: "owner" | "admin" | "compliance" | "advisor") {
  return request<{ status: "invited" }>("/auth/invite", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

// ---------------------------------------------------------------------------
// Domain endpoints
// ---------------------------------------------------------------------------

export function ask(input: {
  question: string;
  client_id?: string | null;
}) {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify({
      question: input.question,
      client_id: input.client_id ?? null,
    }),
  });
}

export type AskStreamEventName =
  | "accepted"
  | "retrieval_done"
  | "generation_started"
  | "verification_done"
  | "final"
  | "error";

export type AskStreamEvent = {
  event: AskStreamEventName;
  data: Record<string, unknown> | AskResponse;
};

export async function askStream(
  input: {
    question: string;
    client_id?: string | null;
  },
  onEvent: (event: AskStreamEvent) => void,
): Promise<AskResponse> {
  const url = `${getApiBase()}/ask/stream`;

  const doFetch = (token: string | null) =>
    fetch(url, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: buildHeaders({}, token),
      body: JSON.stringify({
        question: input.question,
        client_id: input.client_id ?? null,
      }),
    });

  let response = await doFetch(getAccessToken());
  if (response.status === 401) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      response = await doFetch(refreshed);
    }
    if (response.status === 401) {
      clearAccessToken();
      throw new UnauthorizedError(await readErrorDetail(response));
    }
  }
  if (response.status === 429) {
    const retry = parseInt(response.headers.get("retry-after") ?? "1", 10);
    throw new RateLimitedError(Number.isFinite(retry) ? retry : 1, await readErrorDetail(response));
  }
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }
  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";
  let final: AskResponse | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const event = parseSse(part);
      if (!event) continue;
      onEvent(event);
      if (event.event === "error") {
        const data = event.data as Record<string, unknown>;
        const message = typeof data.message === "string" ? data.message : "Streaming request failed.";
        throw new Error(message);
      }
      if (event.event === "final") {
        final = event.data as AskResponse;
      }
    }
  }
  if (!final) throw new Error("Streaming request ended without a final answer.");
  return final;
}

function parseSse(chunk: string): AskStreamEvent | null {
  const eventLine = chunk.split("\n").find((line) => line.startsWith("event:"));
  const dataLines = chunk
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());
  if (!eventLine || dataLines.length === 0) return null;
  const event = eventLine.slice(6).trim() as AskStreamEventName;
  return { event, data: JSON.parse(dataLines.join("\n")) };
}

export function getMetrics() {
  return request<MetricsSummary>("/metrics/summary");
}

export function getAuditSummaries(limit = 20) {
  return request<AuditSummary[]>(`/audit?limit=${limit}`);
}

export function getAudit(id: string) {
  return request<AuditDetail>(`/audit/${id}`);
}

export function verifyAuditChain() {
  return request<AuditVerifyReport>("/audit/verify");
}

export function createEscalation(input: {
  decision_id: string;
  reason?: string;
  note?: string | null;
}) {
  return request<Escalation>("/escalations", {
    method: "POST",
    body: JSON.stringify({
      decision_id: input.decision_id,
      reason: input.reason ?? "advisor_requested_review",
      note: input.note ?? null,
    }),
  });
}

export function listEscalations(limit = 100, status?: Escalation["status"]) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  return request<Escalation[]>(`/escalations?${params.toString()}`);
}

export function updateEscalation(
  escalationId: string,
  input: { status?: Escalation["status"]; assigned_to_user_id?: string | null; note?: string | null },
) {
  return request<Escalation>(`/escalations/${encodeURIComponent(escalationId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export type LlmStatus = {
  local_llm: boolean;
  configured_model: string;
  has_openrouter_key: boolean;
  models_endpoint_reachable: boolean;
  configured_model_available: boolean | null;
  recommended_free_models: Array<{ id: string; name: string }>;
  error?: string;
};

export function getLlmStatus() {
  return request<LlmStatus>("/llm/status");
}

export type ModelHealth = {
  provider: string;
  label: string;
  model: string;
  route: string;
  configured: boolean;
  healthy: boolean;
  available: boolean;
  production_eligible: boolean;
  blocked_reason: string | null;
  latency_ms: number | null;
  error: string | null;
};

export type ProductionModelRouteStatus = {
  provider: string;
  label: string;
  model: string;
  route: string;
  configured: boolean;
  production_eligible: boolean;
  blocked_reason: string | null;
  approved_for_inference: boolean;
  approval: {
    approved: boolean;
    reason: string;
    run_id: string | null;
    created_at: string | null;
  };
  prompt_profile: Record<string, unknown>;
};

export type ProductionModelStatus = {
  production_mode: boolean;
  product_inference_allowed: boolean;
  active_route: string | null;
  candidate_routes: string[];
  approved_routes: string[];
  required_eval_questions: number;
  eval_freshness_hours: number;
  require_recent_eval: boolean;
  approved_models_env: string;
  blocked_reason: string | null;
  routes: ProductionModelRouteStatus[];
};

export type ModelLeaderboardRow = {
  run_id: string | null;
  created_at: string | null;
  provider: string;
  label: string;
  model: string;
  route: string;
  status: string;
  production_ready: boolean;
  overall_score: number;
  outcome_accuracy: number;
  citation_accuracy: number;
  retrieval_recall: number;
  faithfulness_score: number;
  golden_claim_score: number;
  hallucination_rate: number;
  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  determinism: number;
  answerability_accuracy: number;
  refusal_correctness: number;
  numeric_compliance_accuracy: number;
  prompt_injection_resistance: number;
  advisor_quality_score: number;
  evaluated_questions: number;
  dataset_size: number | null;
  dataset_version: string | null;
  category_scores: Record<string, { count: number; score: number; pass_rate: number }>;
  failure_buckets: Record<string, number>;
  eval_gate: string;
  failure_examples: ModelEvalFailure[];
  error: string | null;
  health: Record<string, unknown> | null;
};

export type ModelLeaderboard = {
  dataset_version: string;
  dataset_size: number;
  evaluated_questions: number;
  thresholds: Record<string, number>;
  models: ModelLeaderboardRow[];
};

export type ModelEvalFailure = {
  id?: string;
  run_id?: string;
  case_id: string;
  category: string;
  question: string;
  client_id: string | null;
  expected_outcome: string;
  actual_outcome: string;
  passed: boolean;
  outcome_score: number;
  citation_score: number;
  retrieval_score: number;
  faithfulness_score: number;
  golden_claim_score: number;
  answerability_score?: number;
  refusal_score?: number;
  numeric_compliance_score?: number;
  prompt_injection_score?: number;
  advisor_quality_score?: number;
  hallucinated: boolean;
  latency_ms: number;
  failure_bucket?: string;
  expected_sources: string[];
  cited_sources: string[];
  retrieved_sources: string[];
  missing_terms: string[];
  banned_terms?: string[];
  failure_reasons: string[];
  answer: string | null;
  refusal_reason: string | null;
  gold_answer?: string | null;
  reason?: string | null;
  adversarial?: boolean;
};

export type ModelEvalRun = Omit<
  ModelLeaderboardRow,
  "health" | "failure_examples"
> & {
  thresholds?: Record<string, number>;
  failure_examples?: ModelEvalFailure[];
  results?: ModelEvalFailure[];
};

export function getModelHealth() {
  return request<ModelHealth[]>("/models/health");
}

export function getProductionModelStatus() {
  return request<ProductionModelStatus>("/models/production-status");
}

export function getModelLeaderboard(limit = 40, determinismRuns = 2) {
  return request<ModelLeaderboard>(
    `/models/leaderboard?limit=${limit}&determinism_runs=${determinismRuns}`,
  );
}

export function runModelEval(limit = 40, determinismRuns = 2, gate: "fast" | "full" = "fast") {
  return request<ModelLeaderboard>(
    `/models/eval-runs?limit=${limit}&determinism_runs=${determinismRuns}&gate=${gate}`,
    { method: "POST" },
  );
}

export function getModelEvalRuns(limit = 20) {
  return request<ModelEvalRun[]>(`/models/eval-runs?limit=${limit}`);
}

export function getModelEvalRun(runId: string) {
  return request<ModelEvalRun>(`/models/eval-runs/${runId}`);
}

export type ByoKey = {
  provider: string;
  last4: string | null;
  kid: string;
  created_at: string;
};

export function listByoKeys() {
  return request<ByoKey[]>("/users/me/byo-keys");
}

export function saveByoKey(input: { provider: string; api_key: string }) {
  return request<ByoKey>("/users/me/byo-keys", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteByoKey(provider: string) {
  return request<void>(`/users/me/byo-keys/${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
}

export function runDeterminism(input: {
  question: string;
  client_id?: string | null;
  runs?: number;
}) {
  return request<{
    determinism_score: number;
    representative_decision_id: string | null;
    per_run_outcomes: AskResponse[];
  }>("/determinism", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// ---------------------------------------------------------------------------
// Admin: tenant users (admin-tab Users card)
// ---------------------------------------------------------------------------

export type AdminUser = {
  id: string;
  email: string;
  role: "owner" | "admin" | "compliance" | "advisor";
  display_name: string | null;
  mfa_enrolled: boolean;
  email_verified: boolean;
  last_login_at: string | null;
  created_at: string;
  locked: boolean;
};

export type AdminInvitation = {
  id: string;
  email: string;
  role: "owner" | "admin" | "compliance" | "advisor";
  invited_by_user_id: string | null;
  expires_at: string;
  created_at: string;
};

export function listAdminUsers() {
  return request<AdminUser[]>("/admin/users");
}

export function changeAdminUserRole(userId: string, role: AdminUser["role"]) {
  return request<AdminUser>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function revokeAdminUser(userId: string) {
  return request<void>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
}

export function revokeAdminUserSessions(userId: string) {
  return request<void>(`/admin/users/${encodeURIComponent(userId)}/sessions/revoke`, {
    method: "POST",
  });
}

export function listAdminInvitations() {
  return request<AdminInvitation[]>("/admin/users/invitations");
}

export function cancelAdminInvitation(inviteId: string) {
  return request<void>(`/admin/users/invitations/${encodeURIComponent(inviteId)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Self-service (/app/settings/security)
// ---------------------------------------------------------------------------

export function changeOwnPassword(currentPassword: string, newPassword: string) {
  return request<void>("/users/me/change-password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export type Session = {
  id: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  user_agent: string | null;
  ip: string | null;
  is_current: boolean;
};

export function listOwnSessions() {
  return request<Session[]>("/users/me/sessions");
}

export function revokeAllOwnSessions() {
  return request<void>("/users/me/sessions/revoke-all", { method: "POST" });
}
