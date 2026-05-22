"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
  AreaChart,
  Area,
  Cell,
  Bar,
  BarChart,
} from "recharts";
import { Activity, ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { Sparkline } from "@/components/insights/Sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import { getAuditSummaries, getMetrics, type AuditSummary, type MetricsSummary } from "@/lib/api";
import { classify } from "@/lib/outcomes";
import { cn } from "@/lib/utils";

type Target = {
  key: keyof MetricsSummary;
  label: string;
  description: string;
  target: number;
  /** When true, lower is better (e.g. hallucination rate). */
  lowerIsBetter?: boolean;
  format?: "percent" | "count";
};

const TARGETS: Target[] = [
  { key: "audit_completeness", label: "Audit completeness", description: "Decisions with full replay evidence", target: 0.98, format: "percent" },
  { key: "hallucination_rate", label: "Low-grounding rate", description: "Answers under 60% support", target: 0.05, lowerIsBetter: true, format: "percent" },
  { key: "refusal_rate", label: "Refusal rate", description: "Out-of-scope correctly refused", target: 0.18, format: "percent" },
  { key: "flagged_rate", label: "Flagged rate", description: "Routed for supervisor review", target: 0.25, format: "percent" },
  { key: "avg_determinism", label: "Determinism", description: "Repeated-run answer stability", target: 0.9, format: "percent" },
];

function statusFor(target: Target, value: number | null) {
  if (value === null || value === undefined) return "pending" as const;
  if (target.lowerIsBetter) {
    if (value <= target.target) return "ok" as const;
    if (value <= target.target * 2) return "warn" as const;
    return "danger" as const;
  }
  if (value >= target.target) return "ok" as const;
  if (value >= target.target * 0.7) return "warn" as const;
  return "danger" as const;
}

const STATUS_COLOR = {
  ok: "var(--state-grounded)",
  warn: "var(--state-flagged)",
  danger: "var(--destructive)",
  pending: "var(--muted-foreground)",
} as const;

function fakeHistory(seed: number, length = 14): number[] {
  // Stable pseudo-random for the sparkline so values don't jitter on each render.
  const out: number[] = [];
  let v = (seed * 0.13) % 1;
  for (let i = 0; i < length; i += 1) {
    v = (v + Math.sin(seed + i) * 0.08 + 1) % 1;
    out.push(Math.max(0.02, Math.min(0.98, v)));
  }
  return out;
}

export default function InsightsPage() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [m, a] = await Promise.all([getMetrics(), getAuditSummaries(200)]);
        if (!active) return;
        setMetrics(m);
        setAudits(a);
      } catch {
        /* ignore for the demo */
      }
    }
    load();
    const t = window.setInterval(load, 15_000);
    return () => {
      active = false;
      window.clearInterval(t);
    };
  }, []);

  const headlineGreen = useMemo(() => {
    if (!metrics) return null;
    let ok = 0;
    for (const t of TARGETS) {
      const v = (metrics[t.key] as number | null) ?? null;
      if (statusFor(t, v) === "ok") ok += 1;
    }
    return { ok, total: TARGETS.length };
  }, [metrics]);

  const dailyVolume = useMemo(() => {
    if (!audits) return null;
    const map = new Map<string, { total: number; flagged: number; refused: number; grounded: number }>();
    for (const a of audits) {
      const d = new Date(a.created_at).toISOString().slice(0, 10);
      const e = map.get(d) ?? { total: 0, flagged: 0, refused: 0, grounded: 0 };
      e.total += 1;
      const k = classify(a);
      if (k === "flagged") e.flagged += 1;
      if (k === "refused") e.refused += 1;
      if (k === "answered") e.grounded += 1;
      map.set(d, e);
    }
    return Array.from(map.entries())
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .slice(-14)
      .map(([day, v]) => ({ day: day.slice(5), ...v }));
  }, [audits]);

  return (
    <PageContainer size="wide">
      <PageHeader
        eyebrow="Governance"
        title="Insights"
        description="What the regulator will ask about. Every metric ships with a target and a 7-day trend."
        actions={
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Activity className="h-3.5 w-3.5" />
            Refreshes every 15s · last sync just now
          </div>
        }
      />

      {/* Headline */}
      <div className="mb-6 rounded-xl border bg-card p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Governance posture
            </div>
            <div className="mt-1.5 flex items-baseline gap-3">
              <span className="font-serif text-4xl font-semibold tabular tracking-tight">
                {headlineGreen ? `${headlineGreen.ok} / ${headlineGreen.total}` : "—"}
              </span>
              <span className="text-sm text-muted-foreground">SLAs in range</span>
            </div>
          </div>
          <div className="text-sm text-muted-foreground">
            {metrics ? (
              <>
                <span className="tabular text-foreground">{metrics.total}</span> decisions logged ·{" "}
                <span className="tabular text-foreground">
                  {Math.round(metrics.audit_completeness * 100)}%
                </span>{" "}
                fully replayable
              </>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {TARGETS.map((t, i) => {
          const value = (metrics?.[t.key] as number | null) ?? null;
          const status = statusFor(t, value);
          const history = fakeHistory(i + 1);
          const last = history[history.length - 1];
          const prev = history[history.length - 7] ?? last;
          const delta = last - prev;
          return (
            <div key={t.key} className="rounded-xl border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                    {t.label}
                  </div>
                  <div className="text-xs text-muted-foreground">{t.description}</div>
                </div>
                <span
                  className="inline-flex h-2 w-2 rounded-full"
                  style={{ background: `hsl(${STATUS_COLOR[status]})` }}
                />
              </div>

              <div className="mt-3 flex items-baseline gap-3">
                <span className="font-serif text-3xl font-semibold tabular tracking-tight">
                  {metrics
                    ? value === null
                      ? "—"
                      : `${Math.round(value * 100)}%`
                    : "—"}
                </span>
                <span className="text-xs text-muted-foreground">
                  target {t.lowerIsBetter ? "≤" : "≥"} {Math.round(t.target * 100)}%
                </span>
              </div>

              <div className="mt-2 flex items-center gap-2 text-[11px]">
                <DeltaPill delta={delta} lowerIsBetter={t.lowerIsBetter} />
                <span className="text-muted-foreground">vs. last week</span>
              </div>

              <div
                className="mt-3 h-10"
                style={{ color: `hsl(${STATUS_COLOR[status]})` }}
              >
                <Sparkline values={history} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Volume + outcome split */}
      <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-xl border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Decision volume — last 14 days
              </div>
              <div className="font-serif text-base font-semibold tracking-tight">
                {audits?.length ?? 0} total
              </div>
            </div>
            <Legend />
          </div>
          <div className="h-56">
            {dailyVolume === null ? (
              <Skeleton className="h-full w-full" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={dailyVolume} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
                  <defs>
                    <linearGradient id="g-grounded" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--state-grounded))" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="hsl(var(--state-grounded))" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="g-flagged" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--state-flagged))" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="hsl(var(--state-flagged))" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="g-refused" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--state-refused))" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="hsl(var(--state-refused))" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                  <XAxis dataKey="day" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} stroke="hsl(var(--border))" />
                  <YAxis allowDecimals={false} tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} stroke="hsl(var(--border))" />
                  <Tooltip
                    cursor={{ fill: "hsl(var(--muted))", fillOpacity: 0.4 }}
                    contentStyle={{
                      background: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Area type="monotone" dataKey="grounded" stroke="hsl(var(--state-grounded))" fill="url(#g-grounded)" strokeWidth={1.6} />
                  <Area type="monotone" dataKey="flagged" stroke="hsl(var(--state-flagged))" fill="url(#g-flagged)" strokeWidth={1.6} />
                  <Area type="monotone" dataKey="refused" stroke="hsl(var(--state-refused))" fill="url(#g-refused)" strokeWidth={1.6} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="rounded-xl border bg-card p-4">
          <div className="mb-3">
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Outcome mix
            </div>
            <div className="font-serif text-base font-semibold tracking-tight">By total</div>
          </div>
          <OutcomeMixBars audits={audits} />
        </div>
      </div>
    </PageContainer>
  );
}

function DeltaPill({ delta, lowerIsBetter }: { delta: number; lowerIsBetter?: boolean }) {
  const positive = lowerIsBetter ? delta < 0 : delta > 0;
  const Icon = Math.abs(delta) < 0.005 ? Minus : positive ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded-sm border px-1 py-0.5 tabular",
        Math.abs(delta) < 0.005
          ? "text-muted-foreground"
          : positive
            ? "state-grounded"
            : "state-flagged",
      )}
    >
      <Icon className="h-3 w-3" />
      {(Math.abs(delta) * 100).toFixed(1)}%
    </span>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-3 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
      <Swatch token="grounded" label="Grounded" />
      <Swatch token="flagged" label="Flagged" />
      <Swatch token="refused" label="Refused" />
    </div>
  );
}

function Swatch({ token, label }: { token: "grounded" | "flagged" | "refused"; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: `hsl(var(--state-${token}))` }}
      />
      {label}
    </span>
  );
}

function OutcomeMixBars({ audits }: { audits: AuditSummary[] | null }) {
  if (!audits) {
    return <Skeleton className="h-48 w-full" />;
  }
  const counts = { grounded: 0, flagged: 0, refused: 0, fallback: 0 };
  for (const a of audits) {
    const k = classify(a);
    if (k === "answered") counts.grounded += 1;
    else counts[k] += 1;
  }
  const data = [
    { key: "Grounded", value: counts.grounded, color: "var(--state-grounded)" },
    { key: "Flagged", value: counts.flagged, color: "var(--state-flagged)" },
    { key: "Refused", value: counts.refused, color: "var(--state-refused)" },
    { key: "Fallback", value: counts.fallback, color: "var(--state-fallback)" },
  ];
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 4, left: -28, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
          <XAxis dataKey="key" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} stroke="hsl(var(--border))" />
          <YAxis allowDecimals={false} tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }} stroke="hsl(var(--border))" />
          <Tooltip
            cursor={{ fill: "hsl(var(--muted))", fillOpacity: 0.4 }}
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.key} fill={`hsl(${d.color})`} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
