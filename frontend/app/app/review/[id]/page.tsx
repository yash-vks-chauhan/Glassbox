"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock4,
  FileText,
  History,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  getAudit,
  submitReview,
  type AuditDetail,
  type Review,
  type ReviewAssessment,
  type ReviewReasonCode,
} from "@/lib/api";
import { useClients } from "@/lib/clients-hooks";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

const ASSESSMENTS: Array<{ id: ReviewAssessment; label: string }> = [
  { id: "correct", label: "AI was correct" },
  { id: "needs_signoff", label: "Correct, needs supervisor sign-off" },
  { id: "incorrect", label: "AI was wrong — record a correction" },
  { id: "insufficient_evidence", label: "Insufficient evidence — keep escalated" },
];

const ASSESSMENT_LABEL = Object.fromEntries(ASSESSMENTS.map((a) => [a.id, a.label])) as Record<
  ReviewAssessment,
  string
>;

const REASONS: Array<{ code: ReviewReasonCode; label: string }> = [
  { code: "concentration_breach", label: "Concentration breach (IPS)" },
  { code: "liquidity_floor", label: "Liquidity floor (IPS)" },
  { code: "sector_exclusion", label: "Sector exclusion (IPS)" },
  { code: "region_exclusion", label: "Region exclusion (IPS)" },
  { code: "tax_out_of_scope", label: "Cross-border tax — out of scope" },
  { code: "suitability_mismatch", label: "Suitability — risk mismatch" },
  { code: "other", label: "Other" },
];

const REASON_LABEL = Object.fromEntries(REASONS.map((r) => [r.code, r.label])) as Record<
  ReviewReasonCode,
  string
>;

type CorrectedOutcome = NonNullable<Review["corrected_outcome"]>;

type Draft = {
  assessment: ReviewAssessment;
  reason: ReviewReasonCode;
  notes: string;
  correctedOutcome: CorrectedOutcome;
  /** claim id -> did its cited source support it */
  verdicts: Record<string, boolean>;
};

const EMPTY_DRAFT: Draft = {
  assessment: "correct",
  reason: "concentration_breach",
  notes: "",
  correctedOutcome: "refused",
  verdicts: {},
};

// Drafts are a per-device convenience, so browser storage is enough; every
// access is guarded because storage can be unavailable (private windows).
function draftKey(decisionId: string) {
  return `glassbox:review-draft:${decisionId}`;
}

function loadDraft(decisionId: string): Draft | null {
  try {
    const raw = window.localStorage.getItem(draftKey(decisionId));
    return raw ? { ...EMPTY_DRAFT, ...(JSON.parse(raw) as Partial<Draft>) } : null;
  } catch {
    return null;
  }
}

function storeDraft(decisionId: string, draft: Draft | null) {
  try {
    if (draft) window.localStorage.setItem(draftKey(decisionId), JSON.stringify(draft));
    else window.localStorage.removeItem(draftKey(decisionId));
    return true;
  } catch {
    return false;
  }
}

export default function ReviewDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  // Keyed by decision so state (including a saved draft) starts fresh for each.
  return <ReviewDecision key={id} id={id} />;
}

function ReviewDecision({ id }: { id: string }) {
  const { clients } = useClients();
  const [audit, setAudit] = useState<AuditDetail | null | "loading">("loading");
  // The form only renders after the decision loads in the browser, so
  // reading the device-local draft here can't cause a hydration mismatch.
  const [draft, setDraft] = useState<Draft>(() => loadDraft(id) ?? EMPTY_DRAFT);
  const [submitting, setSubmitting] = useState(false);
  const nowMs = useNow();

  useEffect(() => {
    let active = true;
    getAudit(id).then(
      (row) => active && setAudit(row),
      () => active && setAudit(null),
    );
    return () => {
      active = false;
    };
  }, [id]);

  async function reload() {
    try {
      setAudit(await getAudit(id));
    } catch {
      setAudit(null);
    }
  }

  if (audit === "loading") {
    return (
      <div className="mx-auto max-w-[1240px] px-5 py-6 lg:px-8">
        <Skeleton className="h-7 w-48 rounded-md" />
        <div className="mt-4 grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <Skeleton className="h-96 rounded-xl" />
          <Skeleton className="h-96 rounded-xl" />
        </div>
      </div>
    );
  }
  if (!audit) {
    return (
      <div className="mx-auto max-w-[1240px] px-5 py-10 lg:px-8">
        <Link
          href="/app/review"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to review queue
        </Link>
        <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          Could not load decision {id}.
        </div>
      </div>
    );
  }

  const client = clients.find((c) => c.id === audit.client_id);
  const escalation = audit.active_escalation;
  const slaMinutes =
    escalation && nowMs !== null
      ? Math.round((new Date(escalation.sla_due_at).getTime() - nowMs) / 60_000)
      : null;

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function toggleVerdict(claimId: string, supported: boolean) {
    setDraft((current) => {
      const verdicts = { ...current.verdicts };
      if (verdicts[claimId] === supported) delete verdicts[claimId];
      else verdicts[claimId] = supported;
      return { ...current, verdicts };
    });
  }

  function saveDraft() {
    if (storeDraft(id, draft)) toast.success("Draft saved on this device");
    else toast.error("This browser blocked local storage, so the draft wasn't saved");
  }

  async function submit() {
    setSubmitting(true);
    try {
      const review = await submitReview(id, {
        assessment: draft.assessment,
        reason_code: draft.reason,
        notes: draft.notes.trim() || null,
        corrected_outcome: draft.assessment === "incorrect" ? draft.correctedOutcome : null,
        claim_verdicts: Object.entries(draft.verdicts).map(([claim_id, supported]) => ({
          claim_id,
          supported,
        })),
      });
      toast.success("Review saved", {
        description: review.escalation_status
          ? `Escalation is now ${review.escalation_status.replace("_", " ")}.`
          : "No escalation was open for this decision.",
      });
      storeDraft(id, null);
      setDraft(EMPTY_DRAFT);
      await reload();
    } catch (error) {
      toast.error("Review not saved", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setSubmitting(false);
    }
  }

  const labelledCount = Object.keys(draft.verdicts).length;

  return (
    <div className="mx-auto max-w-[1480px] px-5 py-5 lg:px-8 lg:py-6">
      <div className="mb-4 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link href="/app/review" className="hover:text-foreground">
          Review queue
        </Link>
        <ChevronRight className="h-3 w-3 opacity-60" />
        <span className="font-mono text-foreground/80">{audit.id.slice(0, 8)}</span>
      </div>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Reviewing decision
          </div>
          <h1 className="font-serif text-xl font-semibold tracking-tight">{audit.question}</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{new Date(audit.created_at).toLocaleString()}</span>
            <span>·</span>
            <span>{audit.latency_ms}ms</span>
            <span>·</span>
            {client ? (
              <Link href={`/app/clients/${client.id}`} className="hover:text-foreground">
                {client.displayName} ({client.id})
              </Link>
            ) : (
              <span>{audit.client_id ?? "no client"}</span>
            )}
            <span>·</span>
            <Link href={`/app/audit/${audit.id}`} className="hover:text-foreground">
              Open replay
            </Link>
          </div>
        </div>
        <OutcomeBadge result={audit} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-4">
          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Answer returned
              </div>
            </header>
            <div className="p-4 text-[14px] leading-7">
              {audit.final_answer ?? (
                <span className="text-muted-foreground">
                  No final answer — this decision was refused or escalated before answer
                  generation.
                </span>
              )}
            </div>
          </section>

          <section className="rounded-xl border bg-card">
            <header className="flex items-center justify-between border-b px-4 py-2.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Claim audit
              </div>
              <div className="text-[11px] tabular text-muted-foreground">
                {audit.decision_claims.filter((c) => c.kept).length} kept ·{" "}
                {audit.decision_claims.filter((c) => !c.kept).length} dropped
              </div>
            </header>
            {audit.decision_claims.length === 0 ? (
              <div className="px-4 py-6 text-sm text-muted-foreground">
                No claims were emitted for this decision.
              </div>
            ) : (
              <ul className="divide-y divide-border/60">
                {audit.decision_claims.map((claim, i) => {
                  const verdict = claim.id ? draft.verdicts[claim.id] : undefined;
                  return (
                    <li
                      key={claim.id ?? `${claim.claim_text}-${i}`}
                      className="grid grid-cols-[24px_1fr] items-start gap-3 px-4 py-3"
                    >
                      <span
                        className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full"
                        style={{
                          background: claim.kept
                            ? "hsl(var(--state-grounded-soft))"
                            : "hsl(var(--state-refused-soft))",
                          color: claim.kept
                            ? "hsl(var(--state-grounded-soft-foreground))"
                            : "hsl(var(--state-refused-soft-foreground))",
                        }}
                      >
                        {claim.kept ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                      </span>
                      <div className="min-w-0">
                        <p className="text-[13px] leading-6">{claim.claim_text}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                          <span
                            className={cn(
                              "rounded-sm border px-1.5 py-0.5",
                              claim.kept ? "state-grounded" : "state-refused",
                            )}
                          >
                            {claim.kept ? "Kept" : "Dropped"}
                          </span>
                          <span
                            className={cn(
                              "rounded-sm border px-1.5 py-0.5",
                              claim.verified ? "state-grounded" : "state-flagged",
                            )}
                          >
                            {claim.verified ? "Verified" : "Unverified"}
                          </span>
                          <span className="font-mono">{claim.cited_source_id ?? "no source"}</span>
                          {claim.id ? (
                            <span className="ml-auto flex items-center gap-1">
                              <span className="mr-1">Source supports it?</span>
                              <VerdictButton
                                active={verdict === true}
                                onClick={() => toggleVerdict(claim.id!, true)}
                                label="Supported"
                                icon={ThumbsUp}
                              />
                              <VerdictButton
                                active={verdict === false}
                                onClick={() => toggleVerdict(claim.id!, false)}
                                label="Not supported"
                                icon={ThumbsDown}
                              />
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Retrieved evidence
              </div>
            </header>
            <ul className="divide-y divide-border/60">
              {audit.retrieved_chunks.map((chunk, i) => (
                <li key={`${chunk.source_id}-${i}`} className="px-4 py-3">
                  <div className="mb-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <FileText className="h-3 w-3" />
                    <span className="font-mono uppercase tracking-[0.12em]">
                      {chunk.source_type}
                    </span>
                    <span className="font-mono text-foreground/80">{chunk.source_id}</span>
                    <span className="ml-auto tabular">score {chunk.score.toFixed(3)}</span>
                  </div>
                  <p className="text-[13px] leading-6 text-foreground/85">{chunk.chunk_text}</p>
                </li>
              ))}
              {audit.retrieved_chunks.length === 0 ? (
                <li className="px-4 py-6 text-sm text-muted-foreground">
                  No retrieved evidence stored for this decision.
                </li>
              ) : null}
            </ul>
          </section>

          <ReviewHistory audit={audit} />
        </div>

        <aside className="lg:sticky lg:top-[5.5rem] lg:self-start">
          <div className="rounded-xl border bg-card">
            <header className="flex items-center justify-between border-b px-4 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                <ShieldAlert className="h-3 w-3" />
                Reviewer
              </div>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 text-[11px]",
                  slaMinutes !== null && slaMinutes < 0
                    ? "text-destructive"
                    : slaMinutes !== null && slaMinutes < 60
                      ? "text-flagged-soft-foreground"
                      : "text-muted-foreground",
                )}
              >
                <Clock4 className="h-3 w-3" />
                {escalation === null
                  ? "No open escalation"
                  : slaMinutes === null
                    ? "SLA"
                    : slaMinutes >= 0
                      ? `${slaMinutes}m to SLA`
                      : `SLA breached ${Math.abs(slaMinutes)}m ago`}
              </span>
            </header>

            <div className="space-y-4 p-4">
              <div className="space-y-2">
                <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                  Outcome assessment
                </Label>
                <div className="grid gap-1.5" role="radiogroup" aria-label="Outcome assessment">
                  {ASSESSMENTS.map((o) => (
                    <label
                      key={o.id}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm",
                        draft.assessment === o.id
                          ? "border-primary/40 bg-accent/40"
                          : "border-border bg-background/60",
                      )}
                    >
                      <input
                        type="radio"
                        checked={draft.assessment === o.id}
                        onChange={() => update("assessment", o.id)}
                        name="assessment"
                        className="accent-primary"
                      />
                      {o.label}
                    </label>
                  ))}
                </div>
              </div>

              {draft.assessment === "incorrect" ? (
                <div className="space-y-1.5">
                  <Label
                    htmlFor="corrected-outcome"
                    className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                  >
                    Correct outcome
                  </Label>
                  <select
                    id="corrected-outcome"
                    value={draft.correctedOutcome}
                    onChange={(e) => update("correctedOutcome", e.target.value as CorrectedOutcome)}
                    className="h-9 w-full rounded-md border bg-card px-2.5 text-sm"
                  >
                    <option value="refused">Refused</option>
                    <option value="flagged">Flagged for review</option>
                    <option value="answered">Answered</option>
                  </select>
                </div>
              ) : null}

              <div className="space-y-1.5">
                <Label
                  htmlFor="reason"
                  className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                >
                  Reason code
                </Label>
                <select
                  id="reason"
                  value={draft.reason}
                  onChange={(e) => update("reason", e.target.value as ReviewReasonCode)}
                  className="h-9 w-full rounded-md border bg-card px-2.5 text-sm"
                >
                  {REASONS.map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="notes" className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                  Notes
                </Label>
                <Textarea
                  id="notes"
                  rows={4}
                  value={draft.notes}
                  maxLength={4000}
                  onChange={(e) => update("notes", e.target.value)}
                  placeholder="Reasoning the advisor will see with this review."
                />
              </div>

              <div className="flex gap-2">
                <Button onClick={submit} disabled={submitting} className="h-9 flex-1 rounded-md">
                  {submitting ? "Saving…" : "Submit review"}
                </Button>
                <Button variant="outline" onClick={saveDraft} className="h-9 rounded-md">
                  Save draft
                </Button>
              </div>

              <div className="rounded-md border border-dashed bg-card/40 px-2.5 py-2 text-[11px] text-muted-foreground">
                {labelledCount > 0
                  ? `${labelledCount} claim verdict${labelledCount === 1 ? "" : "s"} will be saved as labelled training examples for the grounding scorer.`
                  : "Mark claims as supported or not to add labelled training examples for the grounding scorer."}
              </div>
            </div>
          </div>
          <div className="mt-3 rounded-xl border bg-card/40 p-3 text-[11px] text-muted-foreground">
            <AlertCircle className="mr-1.5 inline h-3 w-3" />
            The decision itself never changes. Reviews and corrections are appended alongside it,
            and the person who asked a question can&apos;t review it.
          </div>
        </aside>
      </div>
    </div>
  );
}

function VerdictButton({
  active,
  onClick,
  label,
  icon: Icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: typeof ThumbsUp;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-md border transition-colors",
        active ? "border-primary/50 bg-primary text-primary-foreground" : "bg-background hover:bg-accent",
      )}
    >
      <Icon className="h-3 w-3" />
    </button>
  );
}

function ReviewHistory({ audit }: { audit: AuditDetail }) {
  if (audit.reviews.length === 0 && audit.corrections.length === 0) return null;
  return (
    <section className="rounded-xl border bg-card">
      <header className="flex items-center gap-1.5 border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        <History className="h-3 w-3" />
        Review history
      </header>
      <ul className="divide-y divide-border/60">
        {audit.reviews.map((review) => {
          const supported = review.claim_labels.filter((l) => l.supported).length;
          return (
            <li key={review.id} className="space-y-1 px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-medium">{ASSESSMENT_LABEL[review.assessment] ?? review.assessment}</span>
                <span className="text-xs text-muted-foreground">
                  · {REASON_LABEL[review.reason_code] ?? review.reason_code}
                </span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {review.reviewer_email ?? "reviewer"} · {new Date(review.created_at).toLocaleString()}
                </span>
              </div>
              {review.notes ? <p className="text-[13px] leading-6 text-foreground/85">{review.notes}</p> : null}
              <div className="text-xs text-muted-foreground">
                {review.claim_labels.length > 0
                  ? `${review.claim_labels.length} claim verdicts (${supported} supported) · `
                  : ""}
                {review.escalation_status ? `escalation ${review.escalation_status.replace("_", " ")}` : "no escalation"}
              </div>
            </li>
          );
        })}
        {audit.corrections.map((correction) => (
          <li key={correction.id} className="space-y-1 px-4 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">Correction</span>
              {correction.corrected_outcome ? (
                <span className="text-xs text-muted-foreground">
                  · correct outcome: {correction.corrected_outcome}
                </span>
              ) : null}
              <span className="ml-auto text-xs text-muted-foreground">
                {new Date(correction.created_at).toLocaleString()}
              </span>
            </div>
            <p className="text-[13px] leading-6 text-foreground/85">{correction.note}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
