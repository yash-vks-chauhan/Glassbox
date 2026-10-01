"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  ClipboardList,
  FileWarning,
  Inbox,
  ScanLine,
  Sparkles,
} from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import {
  getAuditSummaries,
  getMetrics,
  listEscalations,
  listLibrary,
  type AuditSummary,
  type Escalation,
  type LibraryDocument,
  type MetricsSummary,
} from "@/lib/api";
import { KIND_LABEL, libraryHref } from "@/lib/library";
import { hasAtLeastRole, useAuth } from "@/lib/auth-context";
import { useClients } from "@/lib/clients-hooks";
import { Skeleton } from "@/components/ui/skeleton";

const ACTIVE_ESCALATION = new Set<Escalation["status"]>(["open", "in_review"]);

function greetingFor(hour: number) {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function HomePage() {
  const { clients } = useClients();
  const { role, user } = useAuth();
  // `/metrics/summary` is compliance+; advisors would otherwise get a noisy
  // 403 banner on every 15-second poll. Skip the call entirely for them.
  const canSeeMetrics = hasAtLeastRole(role, "compliance");
  const isReviewer = canSeeMetrics;
  const getClient = (id: string | null | undefined) =>
    id ? clients.find((c) => c.id === id) : undefined;
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [escalations, setEscalations] = useState<Escalation[] | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [documents, setDocuments] = useState<LibraryDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [todayLabel, setTodayLabel] = useState("Today");
  const [greeting, setGreeting] = useState("Welcome");
  const [nowMs, setNowMs] = useState<number | null>(null);

  useEffect(() => {
    // Rendered after mount so server and client agree, in the viewer's own
    // locale and time zone.
    const now = new Date();
    setTodayLabel(
      new Intl.DateTimeFormat(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      }).format(now),
    );
    setGreeting(greetingFor(now.getHours()));
    setNowMs(now.getTime());
    listLibrary()
      .then(setDocuments)
      .catch(() => setDocuments([]));

    let active = true;
    async function load() {
      try {
        const [recent, queue] = await Promise.all([
          getAuditSummaries(30),
          listEscalations(200),
        ]);
        if (!active) return;
        setAudits(recent);
        setEscalations(queue);
        if (canSeeMetrics) {
          const m = await getMetrics();
          if (!active) return;
          setMetrics(m);
        }
        setNowMs(Date.now());
        setError(null);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load home");
      }
    }
    load();
    const t = window.setInterval(load, 15_000);
    return () => {
      active = false;
      window.clearInterval(t);
    };
  }, [canSeeMetrics]);

  // Escalations are scoped by the API: reviewers see the tenant's queue,
  // advisors see the ones they raised.
  const queue = useMemo(() => {
    if (!escalations || nowMs === null) return null;
    const active = escalations.filter((e) => ACTIVE_ESCALATION.has(e.status));
    return {
      active: active.length,
      mine: active.filter((e) => e.assigned_to_user_id === user?.user_id).length,
      unclaimed: active.filter((e) => !e.assigned_to_user_id).length,
      breached: active.filter((e) => new Date(e.sla_due_at).getTime() < nowMs).length,
    };
  }, [escalations, nowMs, user?.user_id]);

  // Most recently updated approved documents (only those that carry a date).
  const recentDocuments = useMemo(
    () =>
      (documents ?? [])
        .filter((d) => d.updated_on)
        .sort((a, b) => (a.updated_on! < b.updated_on! ? 1 : -1))
        .slice(0, 4),
    [documents],
  );

  const firstName =
    user?.display_name?.trim().split(/\s+/)[0] || user?.email.split("@")[0] || "";

  return (
    <PageContainer>
      <PageHeader
        eyebrow={"Operational view"}
        title={
          <span className="flex items-baseline gap-2">
            {firstName ? `${greeting}, ${firstName}` : greeting}
            <span className="font-sans text-sm font-normal text-muted-foreground">
              · {todayLabel}
            </span>
          </span>
        }
        description="Your queue, watchlist, and recent activity. Take one action; that's enough to start the day."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <KpiCard
          icon={ClipboardList}
          label={isReviewer ? "Open escalations" : "My open escalations"}
          value={queue?.active ?? "—"}
          hint={
            queue
              ? isReviewer
                ? `${queue.mine} assigned to you · ${queue.unclaimed} unclaimed`
                : "Waiting on a compliance reviewer"
              : null
          }
          href={isReviewer ? "/app/review" : "/app/audit"}
        />
        <KpiCard
          icon={FileWarning}
          label="Past their review SLA"
          value={queue?.breached ?? "—"}
          hint="Target: 0. Open escalations whose SLA deadline has passed"
          href={isReviewer ? "/app/review" : "/app/audit"}
        />
        <KpiCard
          icon={ScanLine}
          label="IPS updated past 7 days"
          value={
            nowMs === null
              ? "—"
              : clients.filter((c) =>
                  new Date(c.ipsUpdatedAt).getTime() >
                  nowMs - 7 * 24 * 3600_000,
                ).length
          }
          hint="Re-check answers issued before the update"
          href="/app/library"
        />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <section>
          <SectionHeading title="Recent activity" link={{ href: "/app/audit", label: "View audit log" }} />
          {error ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
              {error}
            </div>
          ) : audits === null ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14 rounded-md" />
              ))}
            </div>
          ) : (
            <ul className="divide-y divide-border/60 overflow-hidden rounded-lg border bg-card">
              {audits.slice(0, 8).map((a) => {
                const c = getClient(a.client_id);
                return (
                  <li key={a.id}>
                    <Link
                      href={`/app/audit/${a.id}`}
                      className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-accent/40"
                    >
                      <span className="font-mono text-[11px] tabular text-muted-foreground">
                        {new Date(a.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                      <span className="flex-1 truncate text-sm">
                        <span className="text-muted-foreground">
                          {c?.displayName ?? a.client_id ?? "no client"} ·{" "}
                        </span>
                        {a.question}
                      </span>
                      <OutcomeBadge result={a} size="sm" />
                      <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section>
          <SectionHeading title="Watchlist" link={{ href: "/app/clients", label: "Open clients" }} />
          <ul className="space-y-2">
            {clients.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/app/clients/${c.id}`}
                  className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5 transition-colors hover:bg-accent/40"
                >
                  <span
                    className="flex h-9 w-9 items-center justify-center rounded-md text-[11px] font-medium tabular"
                    style={{
                      background: "hsl(var(--secondary))",
                      color: "hsl(var(--secondary-foreground))",
                    }}
                  >
                    {c.id}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{c.displayName}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {c.household} · IPS {c.ipsVersion} · {c.advisor}
                    </div>
                  </div>
                  <span className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    {c.riskProfile}
                  </span>
                </Link>
              </li>
            ))}
          </ul>

          <div className="mt-6 rounded-lg border bg-card/60 p-4">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              <Sparkles className="h-3 w-3" /> Recently updated documents
            </div>
            {documents === null ? (
              <Skeleton className="h-16 rounded-md" />
            ) : recentDocuments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No dated document updates yet.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {recentDocuments.map((d) => (
                  <li key={d.source_id} className="flex items-baseline justify-between gap-3">
                    <Link href={libraryHref(d.source_id)} className="min-w-0 truncate hover:underline">
                      {d.title}
                    </Link>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {KIND_LABEL[d.source_type]} · {d.updated_on}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      {metrics ? (
        <div className="mt-6 rounded-lg border border-dashed bg-card/40 px-4 py-2.5 text-xs text-muted-foreground">
          <Inbox className="mr-1.5 inline h-3 w-3" />
          {metrics.total} decisions logged · grounding gaps {Math.round(metrics.hallucination_rate * 100)}% ·
          audit completeness {Math.round(metrics.audit_completeness * 100)}%
        </div>
      ) : null}
    </PageContainer>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  hint,
  href,
}: {
  icon: typeof Inbox;
  label: string;
  value: number | string;
  hint?: string | null;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group block rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground/80 transition-colors group-hover:text-foreground" />
      </div>
      <div className="flex items-baseline justify-between">
        <span className="font-serif text-3xl font-semibold tabular tracking-tight">{value}</span>
        <ArrowUpRight className="h-4 w-4 text-muted-foreground/0 transition-colors group-hover:text-foreground" />
      </div>
      {hint ? <div className="mt-1.5 text-xs text-muted-foreground">{hint}</div> : null}
    </Link>
  );
}

function SectionHeading({ title, link }: { title: string; link?: { href: string; label: string } }) {
  return (
    <div className="mb-3 flex items-end justify-between">
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</h2>
      {link ? (
        <Link href={link.href} className="text-xs text-muted-foreground hover:text-foreground">
          {link.label} →
        </Link>
      ) : null}
    </div>
  );
}
