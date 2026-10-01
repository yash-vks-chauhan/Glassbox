import type { MetricsSummary } from "@/lib/api";

export type RateKey =
  | "audit_completeness"
  | "hallucination_rate"
  | "refusal_rate"
  | "flagged_rate"
  | "avg_determinism";

export type GovernanceTarget = {
  key: RateKey;
  label: string;
  description: string;
  target: number;
  /** When true, lower is better (e.g. hallucination rate). */
  lowerIsBetter?: boolean;
  /** Audit log filtered to the decisions behind this metric. */
  href?: string;
};

export const GOVERNANCE_TARGETS: GovernanceTarget[] = [
  { key: "audit_completeness", label: "Audit completeness", description: "Decisions with full replay evidence", target: 0.98, href: "/app/audit?range=7d" },
  { key: "hallucination_rate", label: "Low-grounding rate", description: "Answers under 60% support", target: 0.05, lowerIsBetter: true, href: "/app/audit?grounding=low&range=7d" },
  { key: "refusal_rate", label: "Refusal rate", description: "Out-of-scope correctly refused", target: 0.18, href: "/app/audit?outcome=refused&range=7d" },
  { key: "flagged_rate", label: "Flagged rate", description: "Routed for supervisor review", target: 0.25, href: "/app/audit?outcome=flagged&range=7d" },
  { key: "avg_determinism", label: "Determinism", description: "Repeated-run answer stability", target: 0.9 },
];

export type TargetStatus = "ok" | "warn" | "danger" | "pending";

export function targetStatus(target: GovernanceTarget, value: number | null | undefined): TargetStatus {
  if (value === null || value === undefined) return "pending";
  if (target.lowerIsBetter) {
    if (value <= target.target) return "ok";
    if (value <= target.target * 2) return "warn";
    return "danger";
  }
  if (value >= target.target) return "ok";
  if (value >= target.target * 0.7) return "warn";
  return "danger";
}

/** How many governance targets the current metrics meet. */
export function targetsMet(metrics: MetricsSummary) {
  const ok = GOVERNANCE_TARGETS.filter((t) => targetStatus(t, metrics[t.key]) === "ok").length;
  return { ok, total: GOVERNANCE_TARGETS.length };
}
