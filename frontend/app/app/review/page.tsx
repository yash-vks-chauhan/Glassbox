"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  ChevronDown,
  Download,
  Filter,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { listEscalations, updateEscalation, type Escalation } from "@/lib/api";
import { useClients } from "@/lib/clients-hooks";
import { type OutcomeKind } from "@/lib/outcomes";
import { cn } from "@/lib/utils";

type SlaState = { ageMin: number; label: string; tone: "ok" | "warn" | "danger" };

function sla(slaDueAt: string): SlaState {
  const deltaMin = Math.floor((new Date(slaDueAt).getTime() - Date.now()) / 60_000);
  if (deltaMin >= 120) return { ageMin: deltaMin, label: `${formatAge(deltaMin)} left`, tone: "ok" };
  if (deltaMin >= 0) return { ageMin: deltaMin, label: `${formatAge(deltaMin)} left`, tone: "warn" };
  return { ageMin: Math.abs(deltaMin), label: `breached ${formatAge(Math.abs(deltaMin))}`, tone: "danger" };
}

function formatAge(min: number): string {
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

const OUTCOMES: Array<{ id: OutcomeKind | "all"; label: string }> = [
  { id: "all", label: "All" },
  { id: "flagged", label: "Flagged" },
  { id: "refused", label: "Refused" },
  { id: "fallback", label: "Fallback" },
];

export default function ReviewQueuePage() {
  const { clients } = useClients();
  const getClient = (id: string | null | undefined) =>
    id ? clients.find((c) => c.id === id) : undefined;
  const [escalations, setEscalations] = useState<Escalation[] | null>(null);
  const [filter, setFilter] = useState<OutcomeKind | "all">("flagged");
  const [clientId, setClientId] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    listEscalations(200)
      .then((rows) => {
        if (active) setEscalations(rows);
      })
      .catch(() => {
        if (active) setEscalations([]);
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  const rows = useMemo(() => {
    if (!escalations) return null;
    const needle = query.trim().toLowerCase();
    return escalations
      .filter((a) => {
        const kind = escalationOutcome(a);
        if (filter !== "all" && kind !== filter) return false;
        if (filter === "all" && kind === "answered") return false;
        if (clientId !== "all" && a.client_id !== clientId) return false;
        if (needle) {
          const c = getClient(a.client_id);
          return (
            (a.question ?? "").toLowerCase().includes(needle) ||
            (c?.displayName ?? "").toLowerCase().includes(needle) ||
            a.id.toLowerCase().includes(needle)
          );
        }
        return true;
      })
      .sort((a, b) =>
        new Date(a.sla_due_at).getTime() - new Date(b.sla_due_at).getTime(),
      );
  }, [escalations, filter, clientId, query]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAll() {
    if (!rows) return;
    if (selected.size === rows.length) setSelected(new Set());
    else setSelected(new Set(rows.map((r) => r.id)));
  }

  function exportCsv() {
    if (!rows) return;
    const header = ["escalation_id", "decision_id", "created_at", "sla_due_at", "client_id", "status", "outcome", "question", "grounding", "latency_ms"];
    const lines = [header.join(",")].concat(
      rows.map((r) => {
        const cells = [
          r.id,
          r.decision_id,
          r.created_at,
          r.sla_due_at,
          r.client_id ?? "",
          r.status,
          r.decision_outcome ?? "",
          `"${(r.question ?? "").replace(/"/g, '""')}"`,
          r.grounding_score ?? "",
          r.latency_ms ?? "",
        ];
        return cells.join(",");
      }),
    );
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `glassbox-review-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function bulkUpdate(status: Escalation["status"], label: string) {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    try {
      const updated = await Promise.all(
        ids.map((id) =>
          updateEscalation(id, {
            status,
            note: label,
          }),
        ),
      );
      const byId = new Map(updated.map((row) => [row.id, row]));
      setEscalations((current) =>
        current?.map((row) => byId.get(row.id) ?? row) ?? current,
      );
      setSelected(new Set());
      toast.success(label, {
        description: `${updated.length} escalation${updated.length === 1 ? "" : "s"} updated.`,
      });
    } catch (error) {
      toast.error("Could not update review queue", {
        description: error instanceof Error ? error.message : "Escalation update failed.",
      });
    }
  }

  return (
    <PageContainer size="wide">
      <PageHeader
        eyebrow="Compliance · Supervisor view"
        title="Review queue"
        description="Flagged and refused decisions waiting on a human. Sort, claim, decide — every action lands in the audit log."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="h-9 gap-1.5 rounded-md text-xs"
              onClick={() => setRefreshKey((k) => k + 1)}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
            <Button
              variant="outline"
              className="h-9 gap-1.5 rounded-md text-xs"
              onClick={exportCsv}
            >
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </Button>
          </div>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <Filter className="h-3 w-3" /> Filter
        </span>
        {OUTCOMES.map((o) => (
          <Button
            key={o.id}
            type="button"
            variant={filter === o.id ? "secondary" : "outline"}
            className="h-8 rounded-md text-xs"
            onClick={() => setFilter(o.id)}
          >
            {o.label}
          </Button>
        ))}
        <div className="ml-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>Client</span>
          <div className="relative">
            <select
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="h-8 appearance-none rounded-md border bg-card px-2.5 pr-7 text-xs"
            >
              <option value="all">All</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.id} · {c.displayName}</option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          </div>
        </div>
        <div className="ml-auto w-full max-w-xs">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search question, ID, client"
            className="h-8 text-xs"
          />
        </div>
      </div>

      {selected.size > 0 ? (
        <div className="mb-2 flex items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs">
          <span className="font-medium">{selected.size} selected</span>
          <Button variant="outline" size="sm" className="h-7 rounded-md text-xs" onClick={() => bulkUpdate("in_review", "Claimed for review")}>Claim</Button>
          <Button variant="outline" size="sm" className="h-7 rounded-md text-xs" onClick={() => bulkUpdate("resolved", "Marked reviewed")}>Mark reviewed</Button>
          <button className="ml-auto text-muted-foreground" onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[36px_88px_minmax(0,2fr)_120px_120px_120px_100px_60px] gap-px border-b bg-border text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <div className="bg-card px-3 py-2.5">
            <Checkbox
              checked={rows ? selected.size === rows.length && rows.length > 0 : false}
              onCheckedChange={toggleAll}
              aria-label="Select all"
            />
          </div>
          <div className="bg-card px-3 py-2.5">When</div>
          <div className="bg-card px-3 py-2.5">Question</div>
          <div className="bg-card px-3 py-2.5">Client</div>
          <div className="bg-card px-3 py-2.5">Status</div>
          <div className="bg-card px-3 py-2.5 text-right">Grounding</div>
          <div className="bg-card px-3 py-2.5">SLA</div>
          <div className="bg-card px-3 py-2.5" />
        </div>

        {rows === null ? (
          <div className="space-y-1.5 p-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 rounded-md" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <Empty />
        ) : (
          <ul>
            {rows.map((row) => {
              const c = getClient(row.client_id);
              const s = sla(row.sla_due_at);
              return (
                <li
                  key={row.id}
                  className="grid grid-cols-[36px_88px_minmax(0,2fr)_120px_120px_120px_100px_60px] items-center border-b border-border/40 text-sm last:border-0 hover:bg-accent/30"
                >
                  <div className="px-3 py-2.5">
                    <Checkbox
                      checked={selected.has(row.id)}
                      onCheckedChange={() => toggle(row.id)}
                      aria-label={`Select ${row.id}`}
                    />
                  </div>
                  <div className="px-3 py-2.5 font-mono text-[11px] tabular text-muted-foreground">
                    {new Date(row.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                  <Link href={`/app/review/${row.decision_id}`} className="block px-3 py-2.5">
                    <div className="line-clamp-1">{row.question ?? "Decision needs review"}</div>
                    <div className="text-[11px] text-muted-foreground">
                      <span className="font-mono">{row.decision_id.slice(0, 8)}</span>
                      {" · "}
                      {row.latency_ms ?? "—"}ms
                    </div>
                  </Link>
                  <div className="px-3 py-2.5">
                    <div className="text-[13px]">{c?.displayName ?? "—"}</div>
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {row.client_id ?? "no client"}
                    </div>
                  </div>
                  <div className="px-3 py-2.5">
                    <div className="flex flex-col gap-1">
                      <span className={cn("w-fit rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.08em]", row.status === "open" ? "state-flagged" : row.status === "resolved" ? "state-grounded" : "bg-background")}>
                        {row.status.replaceAll("_", " ")}
                      </span>
                      <OutcomeBadge result={{ outcome: row.decision_outcome ?? "flagged" }} size="sm" />
                    </div>
                  </div>
                  <div className="px-3 py-2.5 text-right tabular">
                    {row.grounding_score === null ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <span
                        className={cn(
                          "tabular",
                          row.grounding_score < 0.6 && "text-flagged-soft-foreground",
                        )}
                      >
                        {Math.round(row.grounding_score * 100)}%
                      </span>
                    )}
                  </div>
                  <div
                    className={cn(
                      "px-3 py-2.5 text-[12px]",
                      s.tone === "ok" && "text-muted-foreground",
                      s.tone === "warn" && "text-flagged-soft-foreground",
                      s.tone === "danger" && "text-destructive",
                    )}
                  >
                    {s.label}
                  </div>
                  <Link
                    href={`/app/review/${row.decision_id}`}
                    className="flex items-center justify-end px-3 py-2.5 text-muted-foreground hover:text-foreground"
                  >
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </PageContainer>
  );
}

function escalationOutcome(row: Escalation): OutcomeKind | "answered" {
  const outcome = row.decision_outcome;
  if (outcome === "flagged" || outcome === "refused" || outcome === "fallback" || outcome === "answered") {
    return outcome;
  }
  return "flagged";
}

function Empty() {
  return (
    <div className="flex flex-col items-center gap-2 py-14 text-center text-sm text-muted-foreground">
      <ShieldCheck className="h-5 w-5 opacity-50" />
      <p>No decisions need review with these filters.</p>
      <Link href="/app/audit" className="text-primary">
        View the full audit log →
      </Link>
    </div>
  );
}
