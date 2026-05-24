"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  History,
  KeyRound,
  ListChecks,
  RefreshCw,
  Settings2,
  Sigma,
  Sliders,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  verifyAuditChain,
  getLlmStatus,
  getModelEvalRuns,
  getModelHealth,
  getModelLeaderboard,
  getProductionModelStatus,
  runModelEval,
  listByoKeys,
  saveByoKey,
  deleteByoKey,
  type AuditVerifyReport,
  type ByoKey,
  type LlmStatus,
  type ModelEvalRun,
  type ModelHealth,
  type ModelLeaderboard,
  type ProductionModelStatus,
} from "@/lib/api";
import { UsersCard } from "@/components/admin/UsersCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { hasAtLeastRole, useAuth } from "@/lib/auth-context";

export default function AdminPage() {
  const { role } = useAuth();
  const allowed = hasAtLeastRole(role, "admin");
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [health, setHealth] = useState<ModelHealth[] | null>(null);
  const [productionStatus, setProductionStatus] = useState<ProductionModelStatus | null>(null);
  const [productionStatusError, setProductionStatusError] = useState<string | null>(null);
  const [leaderboard, setLeaderboard] = useState<ModelLeaderboard | null>(null);
  const [runHistory, setRunHistory] = useState<ModelEvalRun[] | null>(null);
  const [selectedRoute, setSelectedRoute] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [byoKeys, setByoKeys] = useState<ByoKey[] | null>(null);
  const [byoKey, setByoKey] = useState("");
  const [savingByoKey, setSavingByoKey] = useState(false);
  const [temp, setTemp] = useState("0.1");

  useEffect(() => {
    if (!allowed) return;
    getLlmStatus()
      .then((next) => {
        setStatus(next);
        setStatusError(null);
      })
      .catch((error) => {
        setStatus(null);
        setStatusError(error instanceof Error ? error.message : "Could not load inference status.");
      });
    refreshModels();
    refreshByoKeys();
  }, [allowed]);

  const selectedModel =
    leaderboard?.models.find((row) => row.route === selectedRoute) ??
    leaderboard?.models[0] ??
    null;

  async function refreshModels() {
    setEvaluating(true);
    try {
      const [healthRows, leaderboardRows, historyRows, productionRows] = await Promise.all([
        getModelHealth().catch(() => []),
        getModelLeaderboard(40, 2).catch(() => null),
        getModelEvalRuns(12).catch(() => []),
        getProductionModelStatus().catch((error) => {
          setProductionStatusError(error instanceof Error ? error.message : "Could not load production model status.");
          return null;
        }),
      ]);
      setHealth(healthRows);
      setLeaderboard(leaderboardRows);
      setRunHistory(historyRows);
      setProductionStatus(productionRows);
      if (productionRows) setProductionStatusError(null);
      if (leaderboardRows?.models.length) {
        setSelectedRoute((current) => current ?? leaderboardRows.models[0].route);
      }
    } finally {
      setEvaluating(false);
    }
  }

  async function runFastEval() {
    setEvaluating(true);
    try {
      const leaderboardRows = await runModelEval(40, 2, "fast");
      const [historyRows, productionRows] = await Promise.all([
        getModelEvalRuns(12).catch(() => []),
        getProductionModelStatus().catch((error) => {
          setProductionStatusError(error instanceof Error ? error.message : "Could not load production model status.");
          return null;
        }),
      ]);
      setLeaderboard(leaderboardRows);
      setRunHistory(historyRows);
      setProductionStatus(productionRows);
      if (productionRows) setProductionStatusError(null);
      if (leaderboardRows.models.length) {
        setSelectedRoute(leaderboardRows.models[0].route);
      }
      toast.success("Fast model gate completed");
    } catch (error) {
      toast.error("Eval failed", {
        description: error instanceof Error ? error.message : "Model evaluation could not run.",
      });
    } finally {
      setEvaluating(false);
    }
  }

  function saveSettingsToast() {
    toast.success("Settings saved");
  }

  async function refreshByoKeys() {
    try {
      setByoKeys(await listByoKeys());
    } catch {
      setByoKeys([]);
    }
  }

  async function saveOpenRouterKey() {
    const trimmed = byoKey.trim();
    if (!trimmed) {
      toast.error("Enter an OpenRouter API key first.");
      return;
    }
    setSavingByoKey(true);
    try {
      await saveByoKey({ provider: "openrouter", api_key: trimmed });
      setByoKey("");
      await refreshByoKeys();
      toast.success("OpenRouter key saved", {
        description: "Future ask requests will load it server-side.",
      });
    } catch (error) {
      toast.error("Could not save key", {
        description: error instanceof Error ? error.message : "Backend rejected the key.",
      });
    } finally {
      setSavingByoKey(false);
    }
  }

  async function removeByoKey(provider: string) {
    try {
      await deleteByoKey(provider);
      await refreshByoKeys();
      toast.success("Key removed");
    } catch (error) {
      toast.error("Could not remove key", {
        description: error instanceof Error ? error.message : "Backend rejected the request.",
      });
    }
  }

  if (!allowed) {
    return (
      <PageContainer>
        <PageHeader
          eyebrow="Org settings"
          title="Admin access required"
          description="This page is limited to tenant admins and owners."
        />
        <div className="rounded-lg border bg-card p-5 text-sm text-muted-foreground">
          Your current role cannot view model controls, user management, or audit
          verification tools.
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Org settings"
        title="Admin"
        description="Models, inference keys, determinism runs, and access — the controls advisors should never see."
      />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-4">
          <Section icon={Cpu} title="Inference">
            {statusError ? (
              <StatusError message={statusError} />
            ) : status === null ? (
              <Skeleton className="h-24 w-full rounded-md" />
            ) : (
              <div className="space-y-3">
                <Row
                  label="Mode"
                  value={status.local_llm ? "Local deterministic demo mode" : "Model router"}
                />
                <Row label="Model" value={<code className="font-mono text-[12px]">{status.configured_model}</code>} />
                <Row
                  label="OpenRouter key"
                  value={status.has_openrouter_key ? "configured" : "not configured"}
                />
                <Row
                  label="Models endpoint"
                  value={status.models_endpoint_reachable ? "reachable" : "offline"}
                />
              </div>
            )}
          </Section>

          <Section icon={CheckCircle2} title="Production model setup">
            {productionStatusError ? (
              <StatusError message={productionStatusError} />
            ) : productionStatus === null ? (
              <Skeleton className="h-40 w-full rounded-md" />
            ) : (
              <div className="space-y-3">
                <div
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm",
                    productionStatus.product_inference_allowed ? "state-grounded" : "state-flagged",
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="font-medium">
                      {productionStatus.product_inference_allowed
                        ? "Production inference is allowed"
                        : "Production inference is blocked"}
                    </div>
                    <StatusPill ok={productionStatus.product_inference_allowed} />
                  </div>
                  <div className="mt-1 text-xs">
                    {productionStatus.active_route ??
                      productionStatus.blocked_reason ??
                      "No active production route."}
                  </div>
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  <MetricCard
                    label="Production mode"
                    value={productionStatus.production_mode ? "on" : "off"}
                  />
                  <MetricCard
                    label="Full gate"
                    value={`${productionStatus.required_eval_questions} cases`}
                  />
                  <MetricCard
                    label="Eval freshness"
                    value={`${productionStatus.eval_freshness_hours}h`}
                  />
                  <MetricCard
                    label="Recent eval required"
                    value={productionStatus.require_recent_eval ? "yes" : "no"}
                  />
                </div>

                <div className="rounded-md border bg-background/60 px-3 py-2">
                  <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    Promotion env
                  </div>
                  <code className="mt-1 block break-all font-mono text-[11px]">
                    {productionStatus.approved_models_env}
                  </code>
                </div>

                <div className="space-y-2">
                  {productionStatus.routes.map((route) => (
                    <div
                      key={route.route}
                      className="rounded-md border bg-background/60 px-3 py-2 text-sm"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
                            route.approved_for_inference ? "state-grounded" : "state-flagged",
                          )}
                        >
                          {route.approved_for_inference ? "Approved" : "Blocked"}
                        </span>
                        <span className="font-medium">{route.label}</span>
                        <code className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
                          {route.model}
                        </code>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {route.blocked_reason || route.approval.reason || "Waiting for eval gate."}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Section>

          <Section icon={Activity} title="Model router health">
            {health === null ? (
              <Skeleton className="h-36 w-full rounded-md" />
            ) : (
              <div className="space-y-2">
                {health.map((row) => (
                  <div
                    key={row.route}
                    className="grid gap-2 rounded-md border bg-background/60 p-3 text-sm md:grid-cols-[1fr_auto]"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusPill ok={row.healthy && row.available} />
                        <span className="font-medium">{row.label}</span>
                        <code className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
                          {row.model}
                        </code>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {row.error || row.blocked_reason || "Configured and reachable."}
                      </div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <div>{row.latency_ms ?? "—"}ms</div>
                      <div>{row.production_eligible ? "Product eligible" : "Demo/fallback only"}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section icon={Sigma} title="Model evaluation leaderboard">
            {leaderboard === null ? (
              <Skeleton className="h-48 w-full rounded-md" />
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    {leaderboard.evaluated_questions} of {leaderboard.dataset_size} benchmark
                    questions scored · {leaderboard.dataset_version}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 rounded-md text-xs"
                    disabled={evaluating}
                    onClick={runFastEval}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    {evaluating ? "Scoring" : "Run eval"}
                  </Button>
                  <span>
                    Pass requires outcome ≥ {pct(leaderboard.thresholds.min_outcome_accuracy)},
                    citations ≥ {pct(leaderboard.thresholds.min_citation_accuracy)}, advisor quality ≥{" "}
                    {pct(leaderboard.thresholds.min_advisor_quality)}, p95 ≤{" "}
                    {leaderboard.thresholds.max_p95_latency_ms}ms
                  </span>
                </div>
                <div className="overflow-hidden rounded-lg border">
                  <div className="grid grid-cols-[minmax(0,1.2fr)_54px_56px_56px_56px_56px_56px_56px_62px_68px_56px_88px] gap-px bg-border text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <Cell>Model</Cell>
                    <Cell align="right">Score</Cell>
                    <Cell align="right">Outcome</Cell>
                    <Cell align="right">Cites</Cell>
                    <Cell align="right">Retrieve</Cell>
                    <Cell align="right">Faith</Cell>
                    <Cell align="right">Refuse</Cell>
                    <Cell align="right">Inject</Cell>
                    <Cell align="right">Advisor</Cell>
                    <Cell align="right">Halluc.</Cell>
                    <Cell align="right">p95</Cell>
                    <Cell>Status</Cell>
                  </div>
                  {leaderboard.models.map((row) => (
                    <button
                      key={row.route}
                      className={cn(
                        "grid w-full grid-cols-[minmax(0,1.2fr)_54px_56px_56px_56px_56px_56px_56px_62px_68px_56px_88px] gap-px bg-border text-left text-xs",
                        selectedModel?.route === row.route && "outline outline-2 outline-primary/30",
                      )}
                      onClick={() => setSelectedRoute(row.route)}
                    >
                      <Cell>
                        <div className="truncate font-medium">{row.label}</div>
                        <div className="truncate font-mono text-[10px] text-muted-foreground">
                          {row.model}
                        </div>
                        {row.error ? (
                          <div className="mt-1 line-clamp-1 text-[10px] text-muted-foreground">
                            {row.error}
                          </div>
                        ) : null}
                      </Cell>
                      <Cell align="right">{pct(row.overall_score)}</Cell>
                      <Cell align="right">{pct(row.outcome_accuracy)}</Cell>
                      <Cell align="right">{pct(row.citation_accuracy)}</Cell>
                      <Cell align="right">{pct(row.retrieval_recall)}</Cell>
                      <Cell align="right">{pct(row.faithfulness_score)}</Cell>
                      <Cell align="right">{pct(row.refusal_correctness)}</Cell>
                      <Cell align="right">{pct(row.prompt_injection_resistance)}</Cell>
                      <Cell align="right">{pct(row.advisor_quality_score)}</Cell>
                      <Cell align="right">{pct(row.hallucination_rate)}</Cell>
                      <Cell align="right">{row.p95_latency_ms ?? "—"}ms</Cell>
                      <Cell>
                        <span
                          className={cn(
                            "inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
                            row.production_ready ? "state-grounded" : "state-flagged",
                          )}
                        >
                          {row.production_ready ? "Approved" : row.status}
                        </span>
                      </Cell>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Section>

          <Section icon={ListChecks} title="Category gates and failure drilldown">
            {selectedModel ? (
              <div className="space-y-4">
                <div className="grid gap-2 md:grid-cols-4">
                  <MetricCard label="Answerability" value={pct(selectedModel.answerability_accuracy)} />
                  <MetricCard label="Numeric compliance" value={pct(selectedModel.numeric_compliance_accuracy)} />
                  <MetricCard label="Advisor quality" value={pct(selectedModel.advisor_quality_score)} />
                  <MetricCard label="p50 / p95 latency" value={`${selectedModel.p50_latency_ms ?? "—"} / ${selectedModel.p95_latency_ms ?? "—"}ms`} />
                </div>

                <div className="grid gap-2 md:grid-cols-3">
                  {Object.entries(selectedModel.failure_buckets).map(([bucket, count]) => (
                    <div key={bucket} className="rounded-md border bg-background/60 px-3 py-2 text-sm">
                      <div className="font-medium">{bucket.replaceAll("_", " ")}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{count} failures</div>
                    </div>
                  ))}
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  {Object.entries(selectedModel.category_scores).map(([category, score]) => (
                    <div key={category} className="rounded-md border bg-background/60 px-3 py-2">
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium">{category.replaceAll("_", " ")}</span>
                        <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", score.score >= (leaderboard?.thresholds.min_category_score ?? 0.75) ? "state-grounded" : "state-flagged")}>
                          {pct(score.score)}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {score.count} cases · {pct(score.pass_rate)} clean pass rate
                      </div>
                    </div>
                  ))}
                </div>

                {selectedModel.failure_examples.length === 0 ? (
                  <div className="rounded-md border state-grounded px-3 py-2 text-sm">
                    No sampled failures for this model route.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {selectedModel.failure_examples.map((failure) => (
                      <div key={`${selectedModel.route}-${failure.case_id}`} className="rounded-md border bg-background/60 p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <AlertTriangle className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="font-mono text-[11px] text-muted-foreground">
                            {failure.case_id}
                          </span>
                          <span className="rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em]">
                            {failure.category}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            expected {failure.expected_outcome}, got {failure.actual_outcome}
                          </span>
                        </div>
                        <div className="mt-2 font-medium">{failure.question}</div>
                        <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                          {failure.failure_reasons.slice(0, 4).map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                        <div className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                          {failure.answer || failure.refusal_reason || "No answer returned."}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <Skeleton className="h-36 w-full rounded-md" />
            )}
          </Section>

          <Section icon={KeyRound} title="Bring your own key">
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Enrol an OpenRouter key once. The backend encrypts it and only shows metadata here.
              </p>
              {byoKeys === null ? (
                <Skeleton className="h-12 w-full rounded-md" />
              ) : byoKeys.length > 0 ? (
                <div className="space-y-2">
                  {byoKeys.map((key) => (
                    <div
                      key={key.provider}
                      className="flex items-center justify-between gap-3 rounded-md border bg-background/60 px-3 py-2 text-sm"
                    >
                      <div>
                        <div className="font-medium capitalize">{key.provider}</div>
                        <div className="text-xs text-muted-foreground">
                          key ends {key.last4 ? `...${key.last4}` : "unknown"} · {key.kid}
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="h-7 w-7"
                        aria-label={`Remove ${key.provider} key`}
                        onClick={() => removeByoKey(key.provider)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-md border bg-background/60 px-3 py-2 text-sm text-muted-foreground">
                  No personal inference key enrolled.
                </div>
              )}
              <div className="grid gap-1.5">
                <Label
                  htmlFor="byo"
                  className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                >
                  OpenRouter API key
                </Label>
                <Input
                  id="byo"
                  type="password"
                  value={byoKey}
                  onChange={(e) => setByoKey(e.target.value)}
                  placeholder="sk-or-…"
                />
              </div>
              <Button
                onClick={saveOpenRouterKey}
                disabled={savingByoKey}
                variant="outline"
                className="h-9 rounded-md text-xs"
              >
                {savingByoKey ? "Saving" : "Save OpenRouter key"}
              </Button>
            </div>
          </Section>

          <Section icon={Sigma} title="Determinism harness">
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Runs the same set of canary questions N times against the active model and posts
                the drift to Insights. Not exposed to advisors.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <FormRow label="Schedule">
                  <Input defaultValue="Daily · 02:00 UTC" />
                </FormRow>
                <FormRow label="Runs per query">
                  <Input defaultValue="5" />
                </FormRow>
                <FormRow label="Alternate model">
                  <Input placeholder="claude-3.5-sonnet" />
                </FormRow>
                <FormRow label="Temperature">
                  <Input value={temp} onChange={(e) => setTemp(e.target.value)} />
                </FormRow>
              </div>
              <div className="flex items-center gap-3">
                <Switch defaultChecked />
                <span className="text-sm text-muted-foreground">Auto-publish to Insights</span>
              </div>
              <Button className="h-9 rounded-md text-xs" onClick={saveSettingsToast}>
                Save schedule
              </Button>
            </div>
          </Section>
        </div>

        <aside className="space-y-4">
          <UsersCard />
          <AuditVerifyCard />

          <Section icon={History} title="Eval run history">
            {runHistory === null ? (
              <Skeleton className="h-32 w-full rounded-md" />
            ) : runHistory.length === 0 ? (
              <p className="text-xs text-muted-foreground">No persisted eval runs yet.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {runHistory.slice(0, 8).map((run) => (
                  <li key={run.run_id ?? run.route} className="rounded-md border bg-background/60 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{run.label}</span>
                      <span className={cn("rounded-full border px-2 py-0.5 text-[10px] uppercase", run.production_ready ? "state-grounded" : "state-flagged")}>
                        {pct(run.overall_score)}
                      </span>
                    </div>
                    <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                      {run.model}
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      {run.created_at ? new Date(run.created_at).toLocaleString() : "Just now"}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section icon={Sliders} title="Guardrails">
            <ul className="space-y-3 text-sm">
              <Guardrail label="Refuse on missing source" defaultOn />
              <Guardrail label="Chain-of-Verification pass" defaultOn />
              <Guardrail label="Log every claim drop" defaultOn />
              <Guardrail label="Suggest escalation on flags" defaultOn />
              <Guardrail label="Allow advisor BYO key" />
            </ul>
          </Section>

          <Section icon={Settings2} title="System">
            <dl className="space-y-3 text-sm">
              <Row label="Region" value="EU-west · Frankfurt" />
              <Row label="Audit retention" value="7 years" />
              <Row label="Rate limit" value="60 req / advisor / min" />
            </dl>
          </Section>
        </aside>
      </div>
    </PageContainer>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Cpu;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border bg-card">
      <header className="flex items-center gap-2 border-b px-4 py-2.5">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          {title}
        </span>
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

function AuditVerifyCard() {
  const [report, setReport] = useState<AuditVerifyReport | null>(null);
  const [loading, setLoading] = useState(false);

  async function runVerify() {
    setLoading(true);
    try {
      setReport(await verifyAuditChain());
      toast.success("Audit chain verified");
    } catch (error) {
      toast.error("Audit verification failed", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void runVerify();
  }, []);

  return (
    <Section icon={ListChecks} title="Audit verify">
      {report === null && loading ? (
        <Skeleton className="h-28 w-full rounded-md" />
      ) : report ? (
        <div className="space-y-3 text-sm">
          <div
            className={cn(
              "rounded-md border px-3 py-2",
              report.ok ? "state-grounded" : "state-flagged",
            )}
          >
            <div className="font-medium">
              {report.ok ? "Hash chain intact" : "Hash chain break detected"}
            </div>
            <div className="mt-1 text-xs">
              {report.verified} of {report.total} decisions verified.
            </div>
          </div>
          {report.first_break_decision_id ? (
            <div className="rounded-md border bg-background/60 px-3 py-2 text-xs text-muted-foreground">
              First break: <code>{report.first_break_decision_id}</code>
              <br />
              {report.first_break_reason}
            </div>
          ) : null}
          <Row
            label="Tail hash"
            value={
              <code className="max-w-[150px] truncate font-mono text-[11px]">
                {report.tail_hash ?? "—"}
              </code>
            }
          />
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-full gap-1.5 rounded-md text-xs"
            onClick={runVerify}
            disabled={loading}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {loading ? "Verifying" : "Verify again"}
          </Button>
        </div>
      ) : (
        <Button
          variant="outline"
          size="sm"
          className="h-8 w-full gap-1.5 rounded-md text-xs"
          onClick={runVerify}
          disabled={loading}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Verify chain
        </Button>
      )}
    </Section>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-sm font-medium tabular-nums">{value}</div>
    </div>
  );
}

function StatusError({ message }: { message: string }) {
  return (
    <div className="rounded-md border state-flagged px-3 py-2 text-sm">
      <div className="font-medium">Status unavailable</div>
      <div className="mt-1 text-xs">{message}</div>
    </div>
  );
}

function StatusPill({ ok }: { ok: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
        ok ? "state-grounded" : "state-flagged",
      )}
    >
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {ok ? "Healthy" : "Check"}
    </span>
  );
}

function Cell({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <div
      className={cn(
        "min-w-0 bg-card px-3 py-2",
        align === "right" && "text-right tabular-nums",
      )}
    >
      {children}
    </div>
  );
}

function pct(value: number | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function Guardrail({ label, defaultOn = false }: { label: string; defaultOn?: boolean }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-md border bg-background/60 px-3 py-2">
      <span>{label}</span>
      <Switch defaultChecked={defaultOn} />
    </li>
  );
}
