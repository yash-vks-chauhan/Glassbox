"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import {
  downloadAuditExport,
  searchAudit,
  type AuditQuery,
  type AuditSummary,
} from "@/lib/api";
import { hasAtLeastRole, useAuth } from "@/lib/auth-context";
import { useClients } from "@/lib/clients-hooks";

const PAGE_SIZE = 50;

type DateRange = "24h" | "7d" | "30d" | "all";
const RANGES: Array<{ id: DateRange; label: string; days: number | null }> = [
  { id: "24h", label: "24h", days: 1 },
  { id: "7d", label: "7d", days: 7 },
  { id: "30d", label: "30d", days: 30 },
  { id: "all", label: "All", days: null },
];

type Outcome = NonNullable<AuditQuery["outcome"]>;
const OUTCOMES: Array<{ id: Outcome | "all"; label: string }> = [
  { id: "all", label: "All" },
  { id: "answered", label: "Grounded" },
  { id: "flagged", label: "Flagged" },
  { id: "refused", label: "Refused" },
  { id: "fallback", label: "Fallback" },
];

type Filters = {
  range: DateRange;
  outcome: Outcome | "all";
  client: string;
  lowGrounding: boolean;
  q: string;
};

function filtersFromParams(params: URLSearchParams): Filters {
  const range = params.get("range");
  const outcome = params.get("outcome");
  return {
    range: RANGES.some((r) => r.id === range) ? (range as DateRange) : "7d",
    outcome: OUTCOMES.some((o) => o.id === outcome) ? (outcome as Outcome) : "all",
    client: params.get("client") ?? "all",
    lowGrounding: params.get("grounding") === "low",
    q: params.get("q") ?? "",
  };
}

function toQuery(filters: Filters): AuditQuery {
  const days = RANGES.find((r) => r.id === filters.range)?.days ?? null;
  return {
    since: days === null ? undefined : new Date(Date.now() - days * 24 * 3600_000).toISOString(),
    outcome: filters.outcome === "all" ? undefined : filters.outcome,
    client_id: filters.client === "all" ? undefined : filters.client,
    grounding: filters.lowGrounding ? "low" : undefined,
    q: filters.q.trim() || undefined,
  };
}

export default function AuditLogPage() {
  return (
    <Suspense fallback={<AuditLogSkeleton />}>
      <AuditLog />
    </Suspense>
  );
}

function AuditLog() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = useMemo(() => filtersFromParams(searchParams), [searchParams]);
  const { clients } = useClients();
  const { role } = useAuth();
  const canExport = hasAtLeastRole(role, "compliance");
  const getClient = (id: string | null | undefined) =>
    id ? clients.find((c) => c.id === id) : undefined;

  const [rows, setRows] = useState<AuditSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exporting, setExporting] = useState<"csv" | "pdf" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(filters.q);
  // The last q this page wrote to the URL; any other change came from outside
  // (e.g. the global search) and should replace what's in the box.
  const pushedQuery = useRef(filters.q);
  // The query used for the rows on screen, so "Load more" and exports
  // match them even though "since" is relative to the moment of loading.
  const activeQuery = useRef<AuditQuery>(toQuery(filters));

  const setFilters = useCallback(
    (patch: Partial<Filters>) => {
      const next = { ...filters, ...patch };
      const params = new URLSearchParams();
      if (next.range !== "7d") params.set("range", next.range);
      if (next.outcome !== "all") params.set("outcome", next.outcome);
      if (next.client !== "all") params.set("client", next.client);
      if (next.lowGrounding) params.set("grounding", "low");
      if (next.q.trim()) params.set("q", next.q.trim());
      pushedQuery.current = next.q.trim();
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [filters, pathname, router],
  );

  const load = useCallback(async () => {
    const query = toQuery(filters);
    activeQuery.current = query;
    setRows(null);
    try {
      const page = await searchAudit(query, { limit: PAGE_SIZE, offset: 0 });
      setRows(page.rows);
      setTotal(page.total);
      setError(null);
    } catch (err) {
      setRows([]);
      setTotal(0);
      setError(err instanceof Error ? err.message : "Could not load the audit log");
    }
  }, [filters]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (filters.q !== pushedQuery.current) {
      pushedQuery.current = filters.q;
      setSearch(filters.q);
    }
  }, [filters.q]);

  // Debounce the search box into the URL.
  useEffect(() => {
    if (search === filters.q) return;
    const t = window.setTimeout(() => setFilters({ q: search }), 300);
    return () => window.clearTimeout(t);
  }, [search, filters.q, setFilters]);

  async function loadMore() {
    if (!rows) return;
    setLoadingMore(true);
    try {
      const page = await searchAudit(activeQuery.current, {
        limit: PAGE_SIZE,
        offset: rows.length,
      });
      setRows([...rows, ...page.rows]);
      setTotal(page.total);
    } catch (err) {
      toast.error("Could not load more decisions", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setLoadingMore(false);
    }
  }

  async function exportAs(format: "csv" | "pdf") {
    setExporting(format);
    try {
      const filename = await downloadAuditExport(format, activeQuery.current);
      toast.success(`Downloaded ${filename}`, {
        description: `${total} decision${total === 1 ? "" : "s"} · this export is recorded in the security log.`,
      });
    } catch (err) {
      toast.error("Export failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setExporting(null);
    }
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
              onClick={() => void load()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
            {canExport ? (
              <>
                <Button
                  variant="outline"
                  className="h-9 gap-1.5 rounded-md text-xs"
                  disabled={exporting !== null || total === 0}
                  onClick={() => void exportAs("csv")}
                >
                  <Download className="h-3.5 w-3.5" />
                  {exporting === "csv" ? "Exporting…" : "CSV"}
                </Button>
                <Button
                  className="h-9 gap-1.5 rounded-md text-xs"
                  disabled={exporting !== null || total === 0}
                  onClick={() => void exportAs("pdf")}
                >
                  <FileBadge2 className="h-3.5 w-3.5" />
                  {exporting === "pdf" ? "Building binder…" : "PDF binder"}
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          {RANGES.map((r) => (
            <Button
              key={r.id}
              type="button"
              variant={filters.range === r.id ? "secondary" : "outline"}
              className="h-8 rounded-md text-xs"
              onClick={() => setFilters({ range: r.id })}
            >
              {r.label}
            </Button>
          ))}
        </div>

        <div className="ml-2 flex items-center gap-1">
          {OUTCOMES.map((o) => (
            <Button
              key={o.id}
              type="button"
              variant={filters.outcome === o.id ? "secondary" : "outline"}
              className="h-8 rounded-md text-xs"
              onClick={() => setFilters({ outcome: o.id })}
            >
              {o.label}
            </Button>
          ))}
          <Button
            type="button"
            variant={filters.lowGrounding ? "secondary" : "outline"}
            className="h-8 rounded-md text-xs"
            aria-pressed={filters.lowGrounding}
            onClick={() => setFilters({ lowGrounding: !filters.lowGrounding })}
          >
            Grounding &lt; 60%
          </Button>
        </div>

        <div className="relative">
          <select
            value={filters.client}
            onChange={(e) => setFilters({ client: e.target.value })}
            aria-label="Client"
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
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search question, decision ID"
              aria-label="Search the audit log"
              className="h-8 pl-8 text-xs"
            />
          </div>
        </div>
      </div>

      {error ? (
        <div className="mb-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

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
            No decisions match. Loosen the filters, or try a wider date range.
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
                    aria-label={`Open decision ${row.id.slice(0, 8)}`}
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
          {rows === null
            ? "Loading…"
            : `Showing ${rows.length} of ${total} decision${total === 1 ? "" : "s"}`}
        </span>
        {rows && rows.length < total ? (
          <Button
            variant="outline"
            className="h-8 rounded-md text-xs"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore ? "Loading…" : `Load ${Math.min(PAGE_SIZE, total - rows.length)} more`}
          </Button>
        ) : null}
      </div>
    </PageContainer>
  );
}

function AuditLogSkeleton() {
  return (
    <PageContainer size="wide">
      <Skeleton className="mb-4 h-16 w-full rounded-lg" />
      <Skeleton className="h-96 w-full rounded-lg" />
    </PageContainer>
  );
}
