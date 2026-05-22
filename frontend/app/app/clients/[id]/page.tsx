"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  ArrowUpRight,
  CalendarDays,
  Check,
  FileText,
  Globe2,
  MessageSquarePlus,
  ShieldCheck,
} from "lucide-react";

import { ButtonLink } from "@/components/ButtonLink";
import { ClientContextBar } from "@/components/clients/ClientContextBar";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { ClientMissingState } from "@/components/clients/ClientMissingState";
import { getAuditSummaries, type AuditSummary } from "@/lib/api";
import { formatAUM, useClient } from "@/lib/clients";
import { classify } from "@/lib/outcomes";
import { Skeleton } from "@/components/ui/skeleton";

export default function ClientDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { client, isHydrated } = useClient(id);
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);

  useEffect(() => {
    if (!client) return;
    let active = true;
    getAuditSummaries(200)
      .then((rows) => {
        if (active) setAudits(rows.filter((r) => r.client_id === client.id));
      })
      .catch(() => {
        if (active) setAudits([]);
      });
    return () => {
      active = false;
    };
  }, [client?.id]);

  if (!client) {
    if (!isHydrated) return <ClientLoadingState />;
    return <ClientMissingState id={id} />;
  }

  const stats = useMemo(() => {
    if (!audits) return null;
    const total = audits.length;
    const flagged = audits.filter((a) => classify(a) === "flagged").length;
    const refused = audits.filter((a) => classify(a) === "refused").length;
    const grounded = audits.filter((a) => classify(a) === "answered").length;
    return { total, flagged, refused, grounded };
  }, [audits]);

  return (
    <>
      <ClientContextBar client={client} openFlagCount={stats?.flagged ?? 0} activeTab="overview" />
      <div className="mx-auto max-w-[1480px] px-5 py-6 lg:px-8 lg:py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-serif text-xl font-semibold tracking-tight">Overview</h2>
          <ButtonLink href={`/app/clients/${client.id}/ask`} className="h-9 gap-1.5 rounded-md">
            <MessageSquarePlus className="h-3.5 w-3.5" />
            New conversation
          </ButtonLink>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-4">
              <Kpi label="Decisions" value={stats?.total ?? "—"} />
              <Kpi label="Grounded" value={stats?.grounded ?? "—"} tone="grounded" />
              <Kpi label="Flagged" value={stats?.flagged ?? "—"} tone="flagged" />
              <Kpi label="Refused" value={stats?.refused ?? "—"} tone="refused" />
            </div>

            <section className="rounded-xl border bg-card">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Recent decisions
                </h3>
                <Link href="/app/audit" className="text-xs text-muted-foreground hover:text-foreground">
                  View audit log →
                </Link>
              </div>
              {audits === null ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 rounded-md" />
                  ))}
                </div>
              ) : audits.length === 0 ? (
                <div className="px-4 py-10 text-center text-sm text-muted-foreground">
                  No decisions logged yet for {client.id}.{" "}
                  <Link className="text-primary" href={`/app/clients/${client.id}/ask`}>
                    Start a conversation →
                  </Link>
                </div>
              ) : (
                <ul className="divide-y divide-border/60">
                  {audits.slice(0, 10).map((a) => (
                    <li key={a.id}>
                      <Link
                        href={`/app/audit/${a.id}`}
                        className="flex items-center gap-3 px-4 py-2.5 hover:bg-accent/30"
                      >
                        <span className="font-mono text-[11px] text-muted-foreground tabular">
                          {new Date(a.created_at).toLocaleString([], {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                        <span className="flex-1 truncate text-sm">{a.question}</span>
                        <OutcomeBadge result={a} size="sm" />
                        <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <aside className="space-y-4">
            <section className="rounded-xl border bg-card p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Mandate
                </h3>
                <span className="rounded-sm border bg-card px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  IPS {client.ipsVersion}
                </span>
              </div>
              <dl className="space-y-2.5 text-sm">
                <Row label="AUM">{formatAUM(client.aumEur)}</Row>
                <Row label="Risk profile" capitalize>{client.riskProfile}</Row>
                <Row label="Single position cap">{client.maxSinglePositionPct}%</Row>
                <Row label="Liquidity floor (30d)">{client.minLiquidWithin30dPct}%</Row>
                <Row label="Jurisdictions">
                  <span className="inline-flex items-center gap-1 text-foreground">
                    <Globe2 className="h-3 w-3 text-muted-foreground" />
                    {client.jurisdictions.join(", ")}
                  </span>
                </Row>
              </dl>

              <div className="mt-4 grid gap-2 border-t pt-3">
                <ListLabel icon={ShieldCheck} title="Excluded sectors" items={client.excludedSectors} />
                <ListLabel icon={AlertOctagon} title="Excluded regions" items={client.excludedRegions} />
              </div>
            </section>

            <section className="rounded-xl border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                <FileText className="h-3.5 w-3.5" />
                Documents in scope
              </div>
              <ul className="space-y-1.5 text-sm">
                <DocRow id={`IPS_${client.id}`} label="Investment Policy Statement" date={client.ipsUpdatedAt} />
                <DocRow id="F100" label="Factsheet — Global Tech Equity" date="2024-10-31" />
                <DocRow id="F200" label="Factsheet — Liquid Core Bond" date="2024-10-31" />
                <DocRow id="REG_SUITABILITY" label="Regulation snippet — Suitability" date="2024-09-01" />
              </ul>
            </section>
          </aside>
        </div>
      </div>
    </>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "grounded" | "flagged" | "refused" | "fallback";
}) {
  return (
    <div className="rounded-xl border bg-card p-3">
      <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="font-serif text-2xl font-semibold tabular">{value}</span>
        {tone ? (
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: `hsl(var(--state-${tone}))` }}
          />
        ) : null}
      </div>
    </div>
  );
}

function Row({
  label,
  children,
  capitalize,
}: {
  label: string;
  children: React.ReactNode;
  capitalize?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={capitalize ? "capitalize" : ""}>{children}</dd>
    </div>
  );
}

function ListLabel({
  icon: Icon,
  title,
  items,
}: {
  icon: typeof ShieldCheck;
  title: string;
  items: string[];
}) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="h-3 w-3" />
        {title}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.length ? (
          items.map((it) => (
            <span
              key={it}
              className="rounded-sm border bg-card px-1.5 py-0.5 text-[11px] capitalize text-foreground/80"
            >
              {it.replace("_", " ")}
            </span>
          ))
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </div>
    </div>
  );
}

function ClientLoadingState() {
  return (
    <div className="mx-auto max-w-[1480px] px-5 py-6 lg:px-8 lg:py-8">
      <Skeleton className="mb-4 h-10 w-72 rounded-md" />
      <div className="grid gap-4 lg:grid-cols-[1.8fr_1fr]">
        <Skeleton className="h-96 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    </div>
  );
}

function DocRow({ id, label, date }: { id: string; label: string; date: string }) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-md border bg-background px-2.5 py-1.5">
      <div className="min-w-0">
        <div className="font-mono text-[11px] text-muted-foreground">{id}</div>
        <div className="truncate text-[13px]">{label}</div>
      </div>
      <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
        <CalendarDays className="h-3 w-3" />
        {new Date(date).toLocaleDateString()}
      </span>
    </li>
  );
}
