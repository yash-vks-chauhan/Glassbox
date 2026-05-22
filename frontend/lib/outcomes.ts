import type { AskResponse } from "@/lib/api";

export type OutcomeKind = "answered" | "flagged" | "refused" | "fallback";

export type OutcomeMeta = {
  kind: OutcomeKind;
  label: string;
  shortDescription: string;
  longDescription: string;
  /** Token suffix used for `state-{kind}`, `border-state-{kind}`, etc. */
  token: "grounded" | "flagged" | "refused" | "fallback";
};

const META: Record<OutcomeKind, OutcomeMeta> = {
  answered: {
    kind: "answered",
    label: "Grounded",
    shortDescription: "Evidence-backed answer",
    longDescription: "Every claim in the answer is supported by a retrieved source.",
    token: "grounded",
  },
  flagged: {
    kind: "flagged",
    label: "Flagged",
    shortDescription: "Mandate or suitability issue",
    longDescription: "Decision needs supervisor sign-off before client action.",
    token: "flagged",
  },
  refused: {
    kind: "refused",
    label: "Refused",
    shortDescription: "Out of approved scope",
    longDescription: "Approved corpus does not cover the question. Escalate.",
    token: "refused",
  },
  fallback: {
    kind: "fallback",
    label: "Fallback",
    shortDescription: "Safe offline path used",
    longDescription: "Hosted model unavailable; safe deterministic path returned.",
    token: "fallback",
  },
};

const FLAG_REGEX =
  /\b(violat|breach|exceed|not permitted|must not|human should review|review before recommendation|escalate|out of compliance)\b/i;

export function classify(result: {
  outcome: string;
  answer?: string | null;
}): OutcomeKind {
  if (result.outcome === "flagged") return "flagged";
  if (
    (result.outcome === "answered" || result.outcome === "fallback") &&
    result.answer &&
    FLAG_REGEX.test(result.answer)
  ) {
    return "flagged";
  }
  if (result.outcome === "answered") return "answered";
  if (result.outcome === "fallback") return "fallback";
  return "refused";
}

export function outcomeMeta(kind: OutcomeKind): OutcomeMeta {
  return META[kind];
}

export function outcomeMetaFor(result: AskResponse | { outcome: string; answer?: string | null }) {
  return META[classify(result)];
}
