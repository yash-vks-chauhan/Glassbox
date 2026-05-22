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
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { getAudit, type AuditDetail } from "@/lib/api";
import { useClients } from "@/lib/clients";
import { classify } from "@/lib/outcomes";
import { cn } from "@/lib/utils";

type ReviewerOutcome = "correct" | "needs-signoff" | "wrong" | "escalate";

const REASON_CODES = [
  "Concentration breach (IPS)",
  "Liquidity floor (IPS)",
  "Sector exclusion (IPS)",
  "Region exclusion (IPS)",
  "Cross-border tax — out of scope",
  "Suitability — risk mismatch",
  "Other",
];

export default function ReviewDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { clients } = useClients();
  const [audit, setAudit] = useState<AuditDetail | null | "loading">("loading");
  const [outcome, setOutcome] = useState<ReviewerOutcome>("needs-signoff");
  const [reason, setReason] = useState(REASON_CODES[0]);
  const [notes, setNotes] = useState("");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    getAudit(id)
      .then(setAudit)
      .catch(() => setAudit(null));
  }, [id]);

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
  const kind = classify(audit);

  function submit() {
    setSubmitted(true);
    toast.success("Review submitted", {
      description: `${outcome} · ${reason}. Reviewer label saved.`,
    });
  }

  const elapsed = Math.floor((Date.now() - new Date(audit.created_at).getTime()) / 60_000);

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
                {audit.decision_claims.map((claim, i) => (
                  <li key={`${claim.claim_text}-${i}`} className="grid grid-cols-[24px_1fr_auto] items-start gap-3 px-4 py-3">
                    <span
                      className={cn(
                        "mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full",
                      )}
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
                    <div>
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
                        <span className="font-mono">
                          {claim.cited_source_id ?? "no source"}
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
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
                    <span className="ml-auto tabular">
                      score {chunk.score.toFixed(3)}
                    </span>
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
                  elapsed < 120 ? "text-muted-foreground" : "text-flagged-soft-foreground",
                )}
              >
                <Clock4 className="h-3 w-3" />
                {elapsed < 240 ? `${Math.max(0, 240 - elapsed)}m to SLA` : "SLA breached"}
              </span>
            </header>

            <div className="space-y-4 p-4">
              <div className="space-y-2">
                <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                  Outcome assessment
                </Label>
                <div className="grid gap-1.5">
                  {([
                    { id: "correct", label: "AI was correct" },
                    { id: "needs-signoff", label: "Correct, needs supervisor sign-off" },
                    { id: "wrong", label: "AI was wrong — override below" },
                    { id: "escalate", label: "Insufficient evidence — escalate" },
                  ] as Array<{ id: ReviewerOutcome; label: string }>).map((o) => (
                    <label
                      key={o.id}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm",
                        outcome === o.id
                          ? "border-primary/40 bg-accent/40"
                          : "border-border bg-background/60",
                      )}
                    >
                      <input
                        type="radio"
                        checked={outcome === o.id}
                        onChange={() => setOutcome(o.id)}
                        name="outcome"
                        className="accent-primary"
                      />
                      {o.label}
                    </label>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <Label
                  htmlFor="reason"
                  className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                >
                  Reason code
                </Label>
                <select
                  id="reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="h-9 w-full rounded-md border bg-card px-2.5 text-sm"
                >
                  {REASON_CODES.map((r) => (
                    <option key={r}>{r}</option>
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
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Add advisor-visible reasoning here."
                />
              </div>

              <div className="flex gap-2">
                <Button onClick={submit} disabled={submitted} className="h-9 flex-1 rounded-md">
                  {submitted ? "Submitted" : "Submit review"}
                </Button>
                <Button variant="outline" className="h-9 rounded-md">
                  Save draft
                </Button>
              </div>

              {submitted ? (
                <div className="rounded-md state-grounded border px-2.5 py-2 text-[11px]">
                  Review label feeding the grounding scorer training set.
                </div>
              ) : (
                <div className="rounded-md border border-dashed bg-card/40 px-2.5 py-2 text-[11px] text-muted-foreground">
                  Reviewer labels train the grounding scorer overnight.
                </div>
              )}
            </div>
          </div>
          <div className="mt-3 rounded-xl border bg-card/40 p-3 text-[11px] text-muted-foreground">
            <AlertCircle className="mr-1.5 inline h-3 w-3" />
            This decision will remain in the audit log regardless of reviewer outcome.
          </div>
        </aside>
      </div>
    </div>
  );
}
