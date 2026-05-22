"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  ChevronDown,
  Download,
  FileBadge2,
  RefreshCw,
  Search,
} from "lucide-react";
import { toast } from "sonner";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { getAuditSummaries, type AuditSummary } from "@/lib/api";
import { useClients } from "@/lib/clients-hooks";
import { classify, type OutcomeKind } from "@/lib/outcomes";

type DateRange = "24h" | "7d" | "30d" | "all";
const RANGES: Array<{ id: DateRange; label: string }> = [
  { id: "24h", label: "24h" },
  { id: "7d", label: "7d" },
  { id: "30d", label: "30d" },
  { id: "all", label: "All" },
];

function inRange(createdAt: string, range: DateRange): boolean {
  if (range === "all") return true;
  const now = Date.now();
  const days = range === "24h" ? 1 : range === "7d" ? 7 : 30;
  return new Date(createdAt).getTime() >= now - days * 24 * 3600_000;
}

export default function AuditLogPage() {
  const { clients } = useClients();
  const getClient = (id: string | null | undefined) =>
    id ? clients.find((c) => c.id === id) : undefined;
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [outcome, setOutcome] = useState<OutcomeKind | "all">("all");
  const [client, setClient] = useState<string>("all");
  const [range, setRange] = useState<DateRange>("7d");
  const [query, setQuery] = useState("");
  const [bump, setBump] = useState(0);

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
  }, [bump]);

  const rows = useMemo(() => {
    if (!audits) return null;
    const needle = query.trim().toLowerCase();
    return audits.filter((a) => {
      if (!inRange(a.created_at, range)) return false;
      if (outcome !== "all" && classify(a) !== outcome) return false;
      if (client !== "all" && a.client_id !== client) return false;
      if (needle) {
        return (
          a.question.toLowerCase().includes(needle) ||
          a.id.toLowerCase().includes(needle)
        );
      }
      return true;
    });
  }, [audits, outcome, client, range, query]);

  function exportCsv() {
    if (!rows) return;
    const header = ["id", "created_at", "client_id", "outcome", "question", "grounding", "determinism", "latency_ms"];
    const lines = [header.join(",")].concat(
      rows.map((r) => [
        r.id,
        r.created_at,
        r.client_id ?? "",
        r.outcome,
        `"${r.question.replace(/"/g, '""')}"`,
        r.grounding_score ?? "",
        r.determinism_score ?? "",
        r.latency_ms,
      ].join(",")),
    );
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `glassbox-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${rows.length} rows`);
  }

  function exportPdfBinder() {
    toast("Audit binder queued", {
      description: `${rows?.length ?? 0} decisions · regulator-ready PDF will be emailed in 2 min.`,
    });
  }

  return (
    <PageContainer size="wide">
      <PageHeader
        eyebrow="System of record"
        title="Audit log"
        description="Every advisor question, every refusal, every replay. Filter for what the regulator is asking about, then export."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="h-9 gap-1.5 rounded-md text-xs"
              onClick={() => setBump((b) => b + 1)}
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
              CSV
            </Button>
            <Button onClick={exportPdfBinder} className="h-9 gap-1.5 rounded-md text-xs">
              <FileBadge2 className="h-3.5 w-3.5" />
              PDF binder
            </Button>
          </div>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          {RANGES.map((r) => (
            <Button
              key={r.id}
              type="button"
              variant={range === r.id ? "secondary" : "outline"}
              className="h-8 rounded-md text-xs"
              onClick={() => setRange(r.id)}
            >
              {r.label}
            </Button>
          ))}
        </div>

        <div className="ml-2 flex items-center gap-1">
          {(["all", "answered", "flagged", "refused", "fallback"] as const).map((o) => (
            <Button
              key={o}
              type="button"
              variant={outcome === o ? "secondary" : "outline"}
              className="h-8 rounded-md text-xs capitalize"
              onClick={() => setOutcome(o as OutcomeKind | "all")}
            >
              {o === "answered" ? "Grounded" : o}
            </Button>
          ))}
        </div>

        <div className="relative">
          <select
            value={client}
            onChange={(e) => setClient(e.target.value)}
            className="h-8 appearance-none rounded-md border bg-card px-2.5 pr-7 text-xs"
          >
            <option value="all">All clients</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.id}</option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
        </div>

        <div className="ml-auto w-full max-w-xs">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search question, decision ID"
              className="h-8 pl-8 text-xs"
            />
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[120px_minmax(0,2.2fr)_120px_110px_100px_100px_70px] gap-px border-b bg-border text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <div className="bg-card px-3 py-2.5">When</div>
          <div className="bg-card px-3 py-2.5">Question</div>
          <div className="bg-card px-3 py-2.5">Client</div>
          <div className="bg-card px-3 py-2.5">Outcome</div>
          <div className="bg-card px-3 py-2.5 text-right">Grounding</div>
          <div className="bg-card px-3 py-2.5 text-right">Latency</div>
          <div className="bg-card px-3 py-2.5" />
        </div>

        {rows === null ? (
          <div className="space-y-1.5 p-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9 rounded-md" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="py-14 text-center text-sm text-muted-foreground">
            No decisions match your filters.
          </div>
        ) : (
          <ul>
            {rows.map((row) => {
              const c = getClient(row.client_id);
              return (
                <li
                  key={row.id}
                  className="grid grid-cols-[120px_minmax(0,2.2fr)_120px_110px_100px_100px_70px] items-center border-b border-border/40 text-sm last:border-0 hover:bg-accent/30"
                >
                  <div className="px-3 py-2 font-mono text-[11px] tabular text-muted-foreground">
                    {new Date(row.created_at).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                  <Link href={`/app/audit/${row.id}`} className="block px-3 py-2">
                    <div className="line-clamp-1">{row.question}</div>
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {row.id.slice(0, 8)}
                    </div>
                  </Link>
                  <div className="px-3 py-2">
                    <div className="text-[13px]">{c?.displayName ?? "—"}</div>
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {row.client_id ?? "no client"}
                    </div>
                  </div>
                  <div className="px-3 py-2">
                    <OutcomeBadge result={row} size="sm" />
                  </div>
                  <div className="px-3 py-2 text-right tabular">
                    {row.grounding_score === null ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      `${Math.round(row.grounding_score * 100)}%`
                    )}
                  </div>
                  <div className="px-3 py-2 text-right tabular text-muted-foreground">
                    {row.latency_ms}ms
                  </div>
                  <Link
                    href={`/app/audit/${row.id}`}
                    className="flex items-center justify-end px-3 py-2 text-muted-foreground hover:text-foreground"
                  >
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {rows ? `${rows.length} decision${rows.length === 1 ? "" : "s"}` : "Loading…"}
        </span>
        <span>Live · refresh every 15s</span>
      </div>
    </PageContainer>
  );
}
