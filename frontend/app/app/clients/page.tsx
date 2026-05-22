"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, MapPin, Search } from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { NewClientDialog } from "@/components/clients/NewClientDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { formatAUM, useClients } from "@/lib/clients";
import { getAuditSummaries, type AuditSummary } from "@/lib/api";
import { classify } from "@/lib/outcomes";
import { cn } from "@/lib/utils";

export default function ClientsListPage() {
  const { clients } = useClients();
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState<"all" | "conservative" | "moderate" | "aggressive">("all");

  useEffect(() => {
    let active = true;
    getAuditSummaries(200)
      .then((rows) => {
        if (active) setAudits(rows);
      })
      .catch(() => {
        if (active) setAudits([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return clients.filter((c) => {
      if (risk !== "all" && c.riskProfile !== risk) return false;
      if (!needle) return true;
      return (
        c.displayName.toLowerCase().includes(needle) ||
        c.id.toLowerCase().includes(needle) ||
        c.household.toLowerCase().includes(needle)
      );
    });
  }, [clients, query, risk]);

  const statsByClient = useMemo(() => {
    const map = new Map<string, { total: number; flagged: number; lastAt: string | null }>();
    if (!audits) return map;
    for (const a of audits) {
      if (!a.client_id) continue;
      const prev = map.get(a.client_id) ?? { total: 0, flagged: 0, lastAt: null };
      prev.total += 1;
      if (classify(a) === "flagged") prev.flagged += 1;
      if (!prev.lastAt || a.created_at > prev.lastAt) prev.lastAt = a.created_at;
      map.set(a.client_id, prev);
    }
    return map;
  }, [audits]);

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Roster"
        title="Clients"
        description="Each conversation is anchored to a client. Every answer travels with their IPS version, jurisdiction, and exclusions."
        actions={<NewClientDialog />}
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative max-w-sm flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, ID, household"
            className="h-9 pl-8"
          />
        </div>
        <div className="flex gap-1.5">
          {(["all", "conservative", "moderate", "aggressive"] as const).map((r) => (
            <Button
              key={r}
              type="button"
              variant={risk === r ? "secondary" : "outline"}
              className="h-9 rounded-md text-xs capitalize"
              onClick={() => setRisk(r)}
            >
              {r}
            </Button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[1.6fr_0.8fr_0.8fr_0.8fr_0.6fr_0.5fr] gap-px border-b bg-border text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <div className="bg-card px-4 py-2.5">Client</div>
          <div className="bg-card px-4 py-2.5">AUM</div>
          <div className="bg-card px-4 py-2.5">Jurisdiction</div>
          <div className="bg-card px-4 py-2.5">IPS</div>
          <div className="bg-card px-4 py-2.5 tabular text-right">Decisions</div>
          <div className="bg-card px-4 py-2.5" />
        </div>
        {filtered.map((client) => {
          const stats = statsByClient.get(client.id);
          const flagged = stats?.flagged ?? 0;
          return (
            <Link
              key={client.id}
              href={`/app/clients/${client.id}`}
              className="grid grid-cols-[1.6fr_0.8fr_0.8fr_0.8fr_0.6fr_0.5fr] border-b border-border/50 last:border-0 hover:bg-accent/30"
            >
              <div className="flex items-center gap-3 px-4 py-3">
                <span
                  className="flex h-8 w-8 items-center justify-center rounded-md font-mono text-[11px] tabular"
                  style={{
                    background: "hsl(var(--secondary))",
                    color: "hsl(var(--secondary-foreground))",
                  }}
                >
                  {client.id}
                </span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">{client.displayName}</span>
                    <span
                      className={cn(
                        "rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground",
                      )}
                    >
                      {client.riskProfile}
                    </span>
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    Advisor {client.advisor}
                  </div>
                </div>
              </div>
              <div className="px-4 py-3 text-sm tabular">{formatAUM(client.aumEur)}</div>
              <div className="px-4 py-3 text-sm">
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <MapPin className="h-3 w-3" /> {client.jurisdictions.join(" · ")}
                </span>
              </div>
              <div className="px-4 py-3 text-sm">
                <div className="font-mono text-[12px]">{client.ipsVersion}</div>
                <div className="text-xs text-muted-foreground">
                  {new Date(client.ipsUpdatedAt).toLocaleDateString()}
                </div>
              </div>
              <div className="px-4 py-3 text-right text-sm tabular">
                {stats ? (
                  <>
                    <div>{stats.total}</div>
                    {flagged > 0 ? (
                      <div className="text-[11px]" style={{ color: "hsl(var(--state-flagged))" }}>
                        {flagged} flagged
                      </div>
                    ) : (
                      <div className="text-[11px] text-muted-foreground">0 flagged</div>
                    )}
                  </>
                ) : (
                  <Skeleton className="ml-auto h-3 w-10" />
                )}
              </div>
              <div className="flex items-center justify-end px-4 py-3 text-muted-foreground">
                <ArrowUpRight className="h-3.5 w-3.5" />
              </div>
            </Link>
          );
        })}
        {filtered.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-muted-foreground">
            No clients match your filters.
          </div>
        ) : null}
      </div>
    </PageContainer>
  );
}
