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
import { getClient } from "@/lib/clients";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function AuditReplayPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let audit: AuditDetail | null = null;
  let error: string | null = null;
  try {
    audit = await getAudit(id);
  } catch (err) {
    error = err instanceof Error ? err.message : "Replay unavailable.";
  }

  return (
    <div className="mx-auto max-w-[1480px] px-5 py-5 lg:px-8 lg:py-6">
      <div className="mb-4 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link href="/app/audit" className="hover:text-foreground">
          Audit log
        </Link>
        <ChevronRight className="h-3 w-3 opacity-60" />
        <span className="font-mono text-foreground/80">{id.slice(0, 8)}</span>
      </div>

      {error || !audit ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error ?? "No audit record exists for this decision ID."}
        </div>
      ) : (
        <AuditReplay audit={audit} />
      )}
    </div>
  );
}

function AuditReplay({ audit }: { audit: AuditDetail }) {
  const client = getClient(audit.client_id);
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
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{new Date(audit.created_at).toLocaleString()}</span>
            <span>·</span>
            <span className="tabular">{audit.latency_ms}ms latency</span>
            <span>·</span>
            <span className="font-mono">{audit.id}</span>
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
              Final answer
            </header>
            <div className="p-4 text-[14px] leading-7">
              {audit.final_answer ?? (
                <span className="text-muted-foreground">
                  Refused or escalated before answer generation.
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
              <Stat label="Determinism" value={audit.determinism_score} hint="Nightly job" />
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
              <DefRow label="Decision ID">
                <code className="font-mono text-[11px]">{audit.id}</code>
              </DefRow>
            </dl>
          </section>

          <section className="rounded-xl border bg-card p-4 text-[12px] leading-6 text-muted-foreground">
            <div className="mb-1 text-[10px] uppercase tracking-[0.14em]">Audit completeness</div>
            <p>
              Question, retrieval, claim verification, and trust metrics are stored for this
              decision. Replay is fully reproducible.
            </p>
          </section>
        </aside>
      </div>
    </div>
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
