export type Citation = {
  source_id: string;
  source_type: string;
  snippet: string;
};

export type Trust = {
  grounding_score: number | null;
  determinism_score: number | null;
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
  }>;
  decision_claims: Array<{
    claim_text: string;
    cited_source_id: string | null;
    verified: boolean;
    kept: boolean;
  }>;
};

export type AuditSummary = Omit<AuditDetail, "final_answer" | "retrieved_chunks" | "decision_claims">;

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function ask(input: {
  question: string;
  client_id?: string | null;
  byo_key?: string | null;
}) {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify(input)
  });
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
    body: JSON.stringify(input)
  });
}
