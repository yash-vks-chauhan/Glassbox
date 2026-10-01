"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
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
import {
  getMetrics,
  getMetricsTimeseries,
  type MetricsPoint,
  type MetricsSummary,
  type MetricsTimeseries,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const TREND_DAYS = 14;

type RateKey =
  | "audit_completeness"
  | "hallucination_rate"
  | "refusal_rate"
  | "flagged_rate"
  | "avg_determinism";

type Target = {
  key: RateKey;
  label: string;
  description: string;
  target: number;
  /** When true, lower is better (e.g. hallucination rate). */
  lowerIsBetter?: boolean;
  /** Audit log filtered to the decisions behind this metric. */
  href?: string;
};

const TARGETS: Target[] = [
  { key: "audit_completeness", label: "Audit completeness", description: "Decisions with full replay evidence", target: 0.98, href: "/app/audit?range=7d" },
  { key: "hallucination_rate", label: "Low-grounding rate", description: "Answers under 60% support", target: 0.05, lowerIsBetter: true, href: "/app/audit?grounding=low&range=7d" },
  { key: "refusal_rate", label: "Refusal rate", description: "Out-of-scope correctly refused", target: 0.18, href: "/app/audit?outcome=refused&range=7d" },
  { key: "flagged_rate", label: "Flagged rate", description: "Routed for supervisor review", target: 0.25, href: "/app/audit?outcome=flagged&range=7d" },
  { key: "avg_determinism", label: "Determinism", description: "Repeated-run answer stability", target: 0.9 },
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

function mean(values: Array<number | null>): number | null {
  const present = values.filter((v): v is number => v !== null);
  return present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
}

/** Last-7-day average minus the 7 days before it; null without both weeks. */
function weekOverWeek(points: MetricsPoint[], key: RateKey): number | null {
  const values = points.map((p) => p[key]);
  const current = mean(values.slice(-7));
  const previous = mean(values.slice(-14, -7));
  return current === null || previous === null ? null : current - previous;
}

function formatAge(seconds: number) {
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

export default function InsightsPage() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [series, setSeries] = useState<MetricsTimeseries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncedAt, setSyncedAt] = useState<number | null>(null);
  const [nowMs, setNowMs] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [m, s] = await Promise.all([getMetrics(), getMetricsTimeseries(TREND_DAYS)]);
        if (!active) return;
        setMetrics(m);
        setSeries(s);
        setSyncedAt(Date.now());
        setError(null);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load metrics");
      }
    }
    load();
    const poll = window.setInterval(load, 15_000);
    const tick = window.setInterval(() => setNowMs(Date.now()), 5_000);
    return () => {
      active = false;
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, []);

  const headline = useMemo(() => {
    if (!metrics) return null;
    const ok = TARGETS.filter((t) => statusFor(t, metrics[t.key] ?? null) === "ok").length;
    return { ok, total: TARGETS.length };
  }, [metrics]);

  const volume = useMemo(
    () =>
      series?.points.map((p) => ({
        day: p.date.slice(5),
        grounded: p.answered,
        flagged: p.flagged,
        refused: p.refused,
        fallback: p.fallback,
      })) ?? null,
    [series],
  );
  const volumeTotal = series?.points.reduce((sum, p) => sum + p.total, 0) ?? 0;
  const syncLabel =
    syncedAt === null ? "Loading…" : `Updated ${formatAge(Math.max(0, Math.round(((nowMs ?? syncedAt) - syncedAt) / 1000)))}`;

  return (
    <PageContainer size="wide">
      <PageHeader
        eyebrow="Governance"
        title="Insights"
        description={`What the regulator will ask about. Every metric has a target and a ${TREND_DAYS}-day daily trend; click one to see the decisions behind it.`}
        actions={
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Activity className="h-3.5 w-3.5" />
            Refreshes every 15s · {syncLabel}
          </div>
        }
      />

      {error ? (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="mb-6 rounded-xl border bg-card p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Governance posture
            </div>
            <div className="mt-1.5 flex items-baseline gap-3">
              <span className="font-serif text-4xl font-semibold tabular tracking-tight">
                {headline ? `${headline.ok} / ${headline.total}` : "—"}
              </span>
              <span className="text-sm text-muted-foreground">targets met</span>
            </div>
          </div>
          <div className="text-sm text-muted-foreground">
            {metrics ? (
              <>
                <span className="tabular text-foreground">{metrics.total}</span> decisions logged ·{" "}
                <span className="tabular text-foreground">
                  {Math.round(metrics.audit_completeness * 100)}%
                </span>{" "}
                fully replayable ·{" "}
                <span className="tabular text-foreground">{metrics.reviews}</span> reviews ·{" "}
                <span className="tabular text-foreground">{metrics.labelled_claims}</span> labelled claims
              </>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {TARGETS.map((t) => {
          const value = metrics ? (metrics[t.key] ?? null) : null;
          const status = statusFor(t, value);
          const history = series?.points.map((p) => p[t.key]) ?? [];
          const delta = series ? weekOverWeek(series.points, t.key) : null;
          const body = (
            <>
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
                  {value === null ? "—" : `${Math.round(value * 100)}%`}
                </span>
                <span className="text-xs text-muted-foreground">
                  target {t.lowerIsBetter ? "≤" : "≥"} {Math.round(t.target * 100)}%
                </span>
              </div>

              <div className="mt-2 flex items-center gap-2 text-[11px]">
                {delta === null ? (
                  <span className="text-muted-foreground">Not enough history for a weekly comparison</span>
                ) : (
                  <>
                    <DeltaPill delta={delta} lowerIsBetter={t.lowerIsBetter} />
                    <span className="text-muted-foreground">vs. the previous 7 days</span>
                  </>
                )}
              </div>

              <div className="mt-3 h-10" style={{ color: `hsl(${STATUS_COLOR[status]})` }}>
                {series ? (
                  <Sparkline
                    values={history}
                    domain={[0, 1]}
                    label={`${t.label}, daily over the last ${TREND_DAYS} days`}
                  />
                ) : (
                  <Skeleton className="h-full w-full" />
                )}
              </div>
            </>
          );
          return t.href ? (
            <Link
              key={t.key}
              href={t.href}
              className="rounded-xl border bg-card p-4 transition-shadow hover:shadow-sm"
            >
              {body}
            </Link>
          ) : (
            <div key={t.key} className="rounded-xl border bg-card p-4">
              {body}
            </div>
          );
        })}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-xl border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Decision volume — last {TREND_DAYS} days
              </div>
              <div className="font-serif text-base font-semibold tracking-tight">
                {volumeTotal} total
              </div>
            </div>
            <Legend />
          </div>
          <div className="h-56">
            {volume === null ? (
              <Skeleton className="h-full w-full" />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={volume} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
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
                  <Area type="monotone" dataKey="grounded" name="Grounded" stroke="hsl(var(--state-grounded))" fill="url(#g-grounded)" strokeWidth={1.6} />
                  <Area type="monotone" dataKey="flagged" name="Flagged" stroke="hsl(var(--state-flagged))" fill="url(#g-flagged)" strokeWidth={1.6} />
                  <Area type="monotone" dataKey="refused" name="Refused" stroke="hsl(var(--state-refused))" fill="url(#g-refused)" strokeWidth={1.6} />
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
            <div className="font-serif text-base font-semibold tracking-tight">All decisions</div>
          </div>
          <OutcomeMixBars counts={metrics?.outcome_counts ?? null} />
        </div>
      </div>
    </PageContainer>
  );
}

function DeltaPill({ delta, lowerIsBetter }: { delta: number; lowerIsBetter?: boolean }) {
  const flat = Math.abs(delta) < 0.005;
  const improving = lowerIsBetter ? delta < 0 : delta > 0;
  const Icon = flat ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded-sm border px-1 py-0.5 tabular",
        flat ? "text-muted-foreground" : improving ? "state-grounded" : "state-flagged",
      )}
    >
      <Icon className="h-3 w-3" />
      {(Math.abs(delta) * 100).toFixed(1)} pts
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

function OutcomeMixBars({ counts }: { counts: MetricsSummary["outcome_counts"] | null }) {
  if (!counts) {
    return <Skeleton className="h-48 w-full" />;
  }
  const data = [
    { key: "Grounded", value: counts.answered, color: "var(--state-grounded)" },
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
