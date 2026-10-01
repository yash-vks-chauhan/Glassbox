"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock4,
  FileText,
  XCircle,
} from "lucide-react";

import { OutcomeBadge } from "@/components/OutcomeBadge";
import { getAudit, type AuditDetail } from "@/lib/api";
import { hasAtLeastRole, useAuth } from "@/lib/auth-context";
import { ClientRecord, getClient } from "@/lib/clients";
import { cn } from "@/lib/utils";

export default function AuditReplayPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [audit, setAudit] = useState<AuditDetail | null>(null);
  const [client, setClient] = useState<ClientRecord | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setAudit(null);
    setClient(undefined);

    getAudit(id)
      .then(async (row) => {
        const loadedClient = row.client_id ? await getClient(row.client_id) : undefined;
        if (!active) return;
        setAudit(row);
        setClient(loadedClient);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Replay unavailable.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [id]);

  return (
    <div className="mx-auto max-w-[1480px] px-5 py-5 lg:px-8 lg:py-6">
      <div className="mb-4 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link href="/app/audit" className="hover:text-foreground">
          Audit log
        </Link>
        <ChevronRight className="h-3 w-3 opacity-60" />
        <span className="font-mono text-foreground/80">{id.slice(0, 8)}</span>
      </div>

      {loading ? (
        <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
          Loading decision replay...
        </div>
      ) : error || !audit ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error ?? "No audit record exists for this decision ID."}
        </div>
      ) : (
        <AuditReplay audit={audit} client={client} />
      )}
    </div>
  );
}

function AuditReplay({
  audit,
  client,
}: {
  audit: AuditDetail;
  client: ClientRecord | undefined;
}) {
  const claimsKept = audit.decision_claims.filter((c) => c.kept).length;
  const claimsDropped = audit.decision_claims.filter((c) => !c.kept).length;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Decision replay
          </div>
          <h1 className="font-serif text-2xl font-semibold tracking-tight">{audit.question}</h1>
          {audit.retrieval_question ? (
            <p className="text-sm text-muted-foreground">
              Follow-up answered as:{" "}
              <span className="text-foreground/85">{audit.retrieval_question}</span>
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{new Date(audit.created_at).toLocaleString()}</span>
            <span>·</span>
            <span className="tabular">{audit.latency_ms}ms latency</span>
            <span>·</span>
            <span className="font-mono">{audit.id}</span>
            {audit.thread_id ? (
              <>
                <span>·</span>
                <Link href={`/app/threads/${audit.thread_id}`} className="hover:text-foreground">
                  Open thread
                </Link>
              </>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <OutcomeBadge result={audit} />
          <Link
            href="/app/audit"
            className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs hover:bg-accent/30"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to log
          </Link>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-4">
          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              {audit.final_answer ? "Final answer" : "Refusal shown to the advisor"}
            </header>
            <div className="p-4 text-[14px] leading-7">
              {audit.final_answer ??
                audit.refusal_reason ?? (
                  <span className="text-muted-foreground">
                    Refused before answer generation. Decisions recorded before refusal texts were
                    stored don&apos;t carry the message that was shown.
                  </span>
                )}
            </div>
          </section>

          <section className="rounded-xl border bg-card">
            <header className="flex items-center justify-between border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <span>Claim audit</span>
              <span className="tabular normal-case">{claimsKept} kept · {claimsDropped} dropped</span>
            </header>
            {audit.decision_claims.length === 0 ? (
              <div className="px-4 py-6 text-sm text-muted-foreground">No claims emitted.</div>
            ) : (
              <ul className="divide-y divide-border/60">
                {audit.decision_claims.map((claim, i) => (
                  <li key={i} className="grid grid-cols-[24px_1fr] gap-3 px-4 py-3">
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
                    <div>
                      <p className="text-[13px] leading-6">{claim.claim_text}</p>
                      <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
                        <span className={cn("rounded-sm border px-1.5 py-0.5", claim.kept ? "state-grounded" : "state-refused")}>
                          {claim.kept ? "kept" : "dropped"}
                        </span>
                        <span className={cn("rounded-sm border px-1.5 py-0.5", claim.verified ? "state-grounded" : "state-flagged")}>
                          {claim.verified ? "verified" : "unverified"}
                        </span>
                        <span className="font-mono">{claim.cited_source_id ?? "no source"}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Retrieved evidence
            </header>
            <ul className="divide-y divide-border/60">
              {audit.retrieved_chunks.map((chunk, i) => (
                <li key={i} className="px-4 py-3">
                  <div className="mb-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <FileText className="h-3 w-3" />
                    <span className="font-mono uppercase tracking-[0.12em]">{chunk.source_type}</span>
                    <span className="font-mono text-foreground/80">{chunk.source_id}</span>
                    <span className="ml-auto tabular">score {chunk.score.toFixed(3)}</span>
                  </div>
                  <p className="text-[13px] leading-6 text-foreground/85">{chunk.chunk_text}</p>
                </li>
              ))}
              {audit.retrieved_chunks.length === 0 ? (
                <li className="px-4 py-6 text-sm text-muted-foreground">No retrieved evidence stored.</li>
              ) : null}
            </ul>
          </section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-[5.5rem] lg:self-start">
          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Trust
            </header>
            <dl className="divide-y divide-border/60 text-sm">
              <Stat label="Grounding score" value={audit.grounding_score} />
              <DefRow label="Model route">
                <code className="font-mono text-[11px]">{audit.llm_model ?? "—"}</code>
              </DefRow>
              <DefRow label="Claims kept / total">
                {claimsKept} of {audit.decision_claims.length || 0}
              </DefRow>
              <DefRow label="Sources retrieved">
                {audit.retrieved_chunks.length}
              </DefRow>
              <DefRow label="Latency">
                <span className="tabular">{audit.latency_ms}ms</span>
              </DefRow>
            </dl>
          </section>

          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Context
            </header>
            <dl className="divide-y divide-border/60 text-sm">
              <DefRow label="Client">
                {client ? (
                  <Link className="hover:text-foreground" href={`/app/clients/${client.id}`}>
                    {client.id} · {client.displayName}
                  </Link>
                ) : (
                  audit.client_id ?? "—"
                )}
              </DefRow>
              <DefRow label="When">
                <span className="inline-flex items-center gap-1.5">
                  <Clock4 className="h-3 w-3 text-muted-foreground" />
                  {new Date(audit.created_at).toLocaleString()}
                </span>
              </DefRow>
              <DefRow label="Asked by">{audit.asked_by ?? "system"}</DefRow>
              <DefRow label="Decision ID">
                <code className="font-mono text-[11px]">{audit.id}</code>
              </DefRow>
              <DefRow label="Row hash">
                <code className="break-all font-mono text-[10px]" title={`prev ${audit.prev_hash ?? "—"}`}>
                  {audit.row_hash ? `${audit.row_hash.slice(0, 16)}…` : "not chained"}
                </code>
              </DefRow>
            </dl>
          </section>

          <OversightPanel audit={audit} />

          <section className="rounded-xl border bg-card p-4 text-[12px] leading-6 text-muted-foreground">
            <div className="mb-1 text-[10px] uppercase tracking-[0.14em]">Audit completeness</div>
            <p>
              The question, the evidence retrieved, every claim kept or dropped, and the trust
              scores are stored exactly as recorded, and the row is linked into the workspace hash
              chain. Reviews and corrections are appended alongside; the decision never changes.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

const ASSESSMENT_LABEL: Record<string, string> = {
  correct: "AI was correct",
  needs_signoff: "Correct, needs sign-off",
  incorrect: "AI was wrong",
  insufficient_evidence: "Insufficient evidence",
};

function OversightPanel({ audit }: { audit: AuditDetail }) {
  const { role } = useAuth();
  const canReview = hasAtLeastRole(role, "compliance");
  const escalation = audit.active_escalation;
  return (
    <section className="rounded-xl border bg-card">
      <header className="flex items-center justify-between border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Human oversight
        {canReview ? (
          <Link href={`/app/review/${audit.id}`} className="normal-case tracking-normal text-primary">
            Review →
          </Link>
        ) : null}
      </header>
      <div className="space-y-3 px-4 py-3 text-sm">
        <div className="text-muted-foreground">
          {escalation
            ? `Escalation ${escalation.status.replace("_", " ")} · ${escalation.priority} priority · SLA ${new Date(escalation.sla_due_at).toLocaleString()}`
            : "No open escalation."}
        </div>
        {audit.reviews.length === 0 && audit.corrections.length === 0 ? (
          <div className="text-xs text-muted-foreground">Not reviewed yet.</div>
        ) : null}
        {audit.reviews.map((review) => (
          <div key={review.id} className="rounded-md border bg-background/60 px-3 py-2">
            <div className="font-medium">{ASSESSMENT_LABEL[review.assessment] ?? review.assessment}</div>
            <div className="text-xs text-muted-foreground">
              {review.reviewer_email ?? "reviewer"} · {new Date(review.created_at).toLocaleString()}
            </div>
            {review.notes ? <p className="mt-1 text-[13px] leading-6">{review.notes}</p> : null}
          </div>
        ))}
        {audit.corrections.map((correction) => (
          <div key={correction.id} className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2">
            <div className="font-medium">
              Correction{correction.corrected_outcome ? ` · should be ${correction.corrected_outcome}` : ""}
            </div>
            <p className="mt-1 text-[13px] leading-6">{correction.note}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | null;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">
        <span className="tabular text-foreground">
          {value === null ? "—" : `${Math.round(value * 100)}%`}
        </span>
        {hint ? <span className="ml-2 text-[11px] text-muted-foreground">{hint}</span> : null}
      </span>
    </div>
  );
}

function DefRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right text-foreground">{children}</span>
    </div>
  );
}
