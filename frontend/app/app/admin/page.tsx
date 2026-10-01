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
  getSystemInfo,
  getDeterminismSchedule,
  listDeterminismRuns,
  saveDeterminismSchedule,
  startDeterminismRun,
  type AuditVerifyReport,
  type ByoKey,
  type LlmStatus,
  type ModelEvalRun,
  type ModelHealth,
  type ModelLeaderboard,
  type ProductionModelStatus,
  type SystemInfo,
  type DeterminismRun,
  type DeterminismSchedule,
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
  const productionChecklist = buildProductionChecklist(productionStatus, health, status);

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

  async function runEval(gate: "fast" | "full") {
    setEvaluating(true);
    try {
      const limit = gate === "full" ? productionStatus?.required_eval_questions ?? 183 : 40;
      const leaderboardRows = await runModelEval(limit, 2, gate, selectedRoute ? [selectedRoute] : undefined);
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
      toast.success(gate === "full" ? "Full model gate completed" : "Fast model gate completed");
    } catch (error) {
      toast.error("Eval failed", {
        description: error instanceof Error ? error.message : "Model evaluation could not run.",
      });
    } finally {
      setEvaluating(false);
    }
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
                  value={
                    status.local_evidence_mode
                      ? "Private local evidence mode"
                      : status.local_llm
                        ? "Local deterministic demo mode"
                        : "Model router"
                  }
                />
                <Row
                  label="Model"
                  value={
                    status.local_evidence_mode ? (
                      "No paid model required"
                    ) : (
                      <code className="font-mono text-[12px]">{status.configured_model}</code>
                    )
                  }
                />
                <Row
                  label="OpenRouter key"
                  value={
                    status.local_evidence_mode
                      ? "not required"
                      : status.has_openrouter_key
                        ? "configured"
                        : "not configured"
                  }
                />
                <Row
                  label="Models endpoint"
                  value={
                    status.models_endpoint_reachable === null
                      ? "not used"
                      : status.models_endpoint_reachable
                        ? "reachable"
                        : "offline"
                  }
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
                      {productionStatus.local_evidence_mode
                        ? "Local evidence mode is ready"
                        : productionStatus.product_inference_allowed
                        ? "Production inference is allowed"
                        : "Production inference is blocked"}
                    </div>
                    <StatusPill ok={productionStatus.product_inference_allowed} />
                  </div>
                  <div className="mt-1 text-xs">
                    {productionStatus.local_evidence_mode
                      ? "Private, source-backed decisions run without paid model calls."
                      : productionStatus.active_route ??
                        productionStatus.blocked_reason ??
                        "No active production route."}
                  </div>
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  {productionChecklist.map((item) => (
                    <ChecklistItem key={item.label} {...item} />
                  ))}
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  <MetricCard
                    label="Production mode"
                    value={productionStatus.production_mode ? "on" : "off"}
                  />
                  <MetricCard
                    label={productionStatus.local_evidence_mode ? "Hosted gate" : "Full gate"}
                    value={
                      productionStatus.local_evidence_mode
                        ? "not required"
                        : `${productionStatus.required_eval_questions} cases`
                    }
                  />
                  <MetricCard
                    label="Eval freshness"
                    value={
                      productionStatus.local_evidence_mode
                        ? "not required"
                        : `${productionStatus.eval_freshness_hours}h`
                    }
                  />
                  <MetricCard
                    label="Recent eval required"
                    value={
                      productionStatus.local_evidence_mode
                        ? "no"
                        : productionStatus.require_recent_eval
                          ? "yes"
                          : "no"
                    }
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
                            route.ready_for_inference ? "state-grounded" : "state-flagged",
                          )}
                        >
                          {route.ready_for_inference
                            ? productionStatus.local_evidence_mode
                              ? "Local evidence"
                              : "Ready"
                            : route.approved_for_inference
                              ? "Approved · smoke failing"
                              : "Blocked"}
                        </span>
                        <span className="font-medium">{route.label}</span>
                        <code className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
                          {route.model}
                        </code>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {route.smoke_error ||
                          route.blocked_reason ||
                          route.approval.reason ||
                          "Waiting for eval gate."}
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
                        {row.smoke_error || row.error || row.blocked_reason || "Listed and chat-usable."}
                      </div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <div>{row.latency_ms ?? "—"}ms list</div>
                      <div>{row.smoke_latency_ms ?? "—"}ms smoke</div>
                      <div>
                        {row.model === "glassbox-evidence-engine"
                          ? "Private evidence engine"
                          : row.production_eligible
                            ? "Product eligible"
                            : "Demo/fallback only"}
                      </div>
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
                    onClick={() => runEval("fast")}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    {evaluating ? "Scoring" : "Fast gate"}
                  </Button>
                  <Button
                    variant="default"
                    size="sm"
                    className="h-7 gap-1.5 rounded-md text-xs"
                    disabled={evaluating || !selectedRoute}
                    onClick={() => runEval("full")}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Full gate
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
                {status?.local_evidence_mode
                  ? "Optional. Private local evidence mode does not need a paid model key."
                  : "Enrol an OpenRouter key once. The backend encrypts it and only shows metadata here."}
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

          <DeterminismCard />
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

          <SystemCards />
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

function buildProductionChecklist(
  productionStatus: ProductionModelStatus | null,
  health: ModelHealth[] | null,
  status: LlmStatus | null,
) {
  const readyRoute = productionStatus?.ready_routes[0] ?? null;
  const activeRoute = productionStatus?.active_route ?? readyRoute ?? productionStatus?.approved_routes[0] ?? null;
  const activeHealth = activeRoute ? health?.find((row) => row.route === activeRoute) : null;
  if (productionStatus?.local_evidence_mode) {
    return [
      {
        label: "Endpoint usable",
        ok: true,
        detail: `${productionStatus.active_route ?? "local:glassbox-evidence-engine"} is ready locally.`,
      },
      {
        label: "Local evidence engine ready",
        ok: true,
        detail: "Uses retrieved sources, policy checks, claim verification, and audit replay.",
      },
      {
        label: "Full eval fresh",
        ok: true,
        detail: "Hosted model gate is not required for private local evidence mode.",
      },
      {
        label: "Hosted model gate skipped",
        ok: true,
        detail: "No paid provider route or APPROVED_MODELS promotion is required.",
      },
      {
        label: "Production mode on",
        ok: Boolean(productionStatus.production_mode),
        detail: productionStatus.production_mode
          ? "Product mode is on for non-LLM guardrails."
          : "Local evidence mode is active; product mode can still be enabled for deployment.",
      },
    ];
  }
  const chatUsable = Boolean(
    readyRoute || activeHealth?.chat_usable || productionStatus?.routes.some((route) => route.ready_for_inference),
  );
  const hasConfiguredRoute = health?.some((row) => row.production_eligible && row.configured) ?? false;
  const approvedRoute = productionStatus?.approved_routes[0] ?? null;
  return [
    {
      label: "Endpoint usable",
      ok: chatUsable,
      detail: chatUsable
        ? `${readyRoute ?? activeRoute} completed a chat smoke test.`
        : activeRoute
          ? `${activeRoute} has not passed chat smoke.`
          : "No product route has passed chat smoke.",
    },
    {
      label: "Key or local route configured",
      ok: Boolean(status?.has_openrouter_key || hasConfiguredRoute),
      detail: status?.has_openrouter_key ? "OpenRouter key metadata is present." : "Using non-hosted candidate route configuration.",
    },
    {
      label: "Full eval fresh",
      ok: Boolean(approvedRoute),
      detail: approvedRoute
        ? `${approvedRoute} has a fresh passing full eval.`
        : productionStatus
          ? `${productionStatus.required_eval_questions} cases required.`
          : "Production status unavailable.",
    },
    {
      label: "Approved route promoted",
      ok: Boolean(approvedRoute),
      detail: approvedRoute ?? "No approved route active.",
    },
    {
      label: "Production mode on",
      ok: Boolean(productionStatus?.production_mode),
      detail: productionStatus?.production_mode ? "Product gate is enforcing approvals." : "Demo/router mode is active.",
    },
  ];
}

function ChecklistItem({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className={cn("rounded-md border px-3 py-2 text-sm", ok ? "state-grounded" : "state-flagged")}>
      <div className="flex items-center gap-2 font-medium">
        {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
        {label}
      </div>
      <div className="mt-1 text-xs">{detail}</div>
    </div>
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

/** The nightly determinism harness: schedule (saved per workspace), a
 * "Run now" button, and the latest runs with per-question scores. */
function DeterminismCard() {
  const [schedule, setSchedule] = useState<DeterminismSchedule | null>(null);
  const [form, setForm] = useState<DeterminismSchedule | null>(null);
  const [runs, setRuns] = useState<DeterminismRun[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    getDeterminismSchedule()
      .then((row) => {
        setSchedule(row);
        setForm(row);
      })
      .catch(() => setSchedule(null));
    listDeterminismRuns(8)
      .then(setRuns)
      .catch(() => setRuns([]));
  }, []);

  const dirty =
    !!form &&
    !!schedule &&
    (form.enabled !== schedule.enabled ||
      form.hour_utc !== schedule.hour_utc ||
      form.runs_per_question !== schedule.runs_per_question ||
      form.sample_size !== schedule.sample_size);

  async function save() {
    if (!form) return;
    setSaving(true);
    try {
      const saved = await saveDeterminismSchedule({
        enabled: form.enabled,
        hour_utc: form.hour_utc,
        runs_per_question: form.runs_per_question,
        sample_size: form.sample_size,
      });
      setSchedule(saved);
      setForm(saved);
      toast.success("Determinism schedule saved");
    } catch (error) {
      toast.error("Could not save the schedule", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  async function runNow() {
    setRunning(true);
    try {
      const run = await startDeterminismRun();
      setRuns((current) => [run, ...(current ?? [])].slice(0, 8));
      setExpanded(run.id);
      toast.success("Determinism run finished", {
        description:
          run.avg_score === null
            ? "No questions to sample yet."
            : `${run.question_count} questions · average ${Math.round(run.avg_score * 100)}%`,
      });
    } catch (error) {
      toast.error("Run failed", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setRunning(false);
    }
  }

  const localHour = (hourUtc: number) =>
    new Date(Date.UTC(2000, 0, 1, hourUtc)).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <Section icon={Sigma} title="Determinism harness">
      {form === null ? (
        <Skeleton className="h-40 w-full rounded-md" />
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Each run asks a sample of this workspace&apos;s recent questions several times and scores
            how much the answers drift. Runs never add decisions to the audit log; results feed the
            Determinism metric on Insights.
          </p>
          <div className="flex items-center gap-3">
            <Switch
              checked={form.enabled}
              onCheckedChange={(enabled) => setForm({ ...form, enabled })}
              aria-label="Run nightly"
            />
            <span className="text-sm">Run nightly</span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <FormRow label="Hour (UTC)">
              <select
                value={form.hour_utc}
                onChange={(e) => setForm({ ...form, hour_utc: Number(e.target.value) })}
                className="h-9 w-full rounded-md border bg-card px-2 text-sm"
                aria-label="Hour (UTC)"
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </FormRow>
            <FormRow label="Runs / question">
              <Input
                type="number"
                min={2}
                max={10}
                value={form.runs_per_question}
                onChange={(e) =>
                  setForm({ ...form, runs_per_question: Math.max(2, Math.min(10, Number(e.target.value) || 2)) })
                }
              />
            </FormRow>
            <FormRow label="Questions">
              <Input
                type="number"
                min={1}
                max={25}
                value={form.sample_size}
                onChange={(e) =>
                  setForm({ ...form, sample_size: Math.max(1, Math.min(25, Number(e.target.value) || 1)) })
                }
              />
            </FormRow>
          </div>
          <p className="text-xs text-muted-foreground">
            {form.enabled
              ? `Runs daily at ${String(form.hour_utc).padStart(2, "0")}:00 UTC (${localHour(form.hour_utc)} your time).`
              : "Nightly runs are off; you can still run it manually."}
            {schedule?.next_run_at && form.enabled && !dirty
              ? ` Next run ${new Date(schedule.next_run_at) <= new Date() ? "is due now" : new Date(schedule.next_run_at).toLocaleString()}.`
              : ""}
          </p>
          <div className="flex gap-2">
            <Button onClick={save} disabled={!dirty || saving} className="h-9 rounded-md text-xs">
              {saving ? "Saving…" : "Save schedule"}
            </Button>
            <Button variant="outline" onClick={runNow} disabled={running} className="h-9 rounded-md text-xs">
              {running ? "Running…" : "Run now"}
            </Button>
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Recent runs</div>
            {runs === null ? (
              <Skeleton className="h-16 w-full rounded-md" />
            ) : runs.length === 0 ? (
              <p className="text-xs text-muted-foreground">No runs yet.</p>
            ) : (
              <ul className="divide-y divide-border/60 rounded-md border text-sm">
                {runs.map((run) => (
                  <li key={run.id}>
                    <button
                      type="button"
                      onClick={() => setExpanded(expanded === run.id ? null : run.id)}
                      className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-accent/30"
                    >
                      <span className="text-xs text-muted-foreground">
                        {new Date(run.created_at).toLocaleString()}
                      </span>
                      <span className="text-xs text-muted-foreground">{run.triggered_by}</span>
                      <span className="ml-auto text-xs text-muted-foreground">
                        {run.question_count} question{run.question_count === 1 ? "" : "s"}
                      </span>
                      <span className="w-12 text-right font-medium tabular">
                        {run.status === "failed"
                          ? "failed"
                          : run.avg_score === null
                            ? "—"
                            : `${Math.round(run.avg_score * 100)}%`}
                      </span>
                    </button>
                    {expanded === run.id ? (
                      <div className="space-y-1 border-t bg-background/60 px-3 py-2 text-xs">
                        {run.error ? <p className="text-destructive">{run.error}</p> : null}
                        {run.results.map((item, i) => (
                          <div key={i} className="flex items-baseline justify-between gap-3">
                            <span className="min-w-0 truncate" title={item.question}>
                              {item.client_id ? `${item.client_id} · ` : ""}
                              {item.question}
                            </span>
                            <span className="shrink-0 tabular text-muted-foreground">
                              {Math.round(item.score * 100)}% · {item.distinct_answers} distinct
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}

/**
 * Guardrails and system facts as the backend reports them. Nothing here is
 * editable in the browser: each guardrail names the environment variable
 * that controls it, or is always on.
 */
function SystemCards() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSystemInfo()
      .then(setInfo)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load system info"));
  }, []);

  if (error) {
    return (
      <Section icon={Settings2} title="System">
        <p className="text-sm text-destructive">{error}</p>
      </Section>
    );
  }
  if (!info) {
    return (
      <Section icon={Settings2} title="System">
        <Skeleton className="h-40 w-full rounded-md" />
      </Section>
    );
  }
  return (
    <>
      <Section icon={Sliders} title="Guardrails">
        <ul className="space-y-2 text-sm">
          {info.guardrails.map((g) => (
            <li
              key={g.key}
              className="flex items-start justify-between gap-3 rounded-md border bg-background/60 px-3 py-2"
            >
              <span className="min-w-0">
                <span className="block">{g.label}</span>
                <span className="block text-xs text-muted-foreground">
                  {[g.detail, g.setting ? `set via ${g.setting}` : "always on"]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <span
                className={cn(
                  "mt-0.5 shrink-0 rounded-sm px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em]",
                  g.enabled
                    ? "bg-[hsl(var(--state-grounded)/0.12)] text-[hsl(var(--state-grounded))]"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {g.enabled ? "On" : "Off"}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Section icon={Settings2} title="System">
        <dl className="space-y-3 text-sm">
          <Row label="Version" value={info.version} />
          <Row label="Environment" value={info.environment} />
          <Row label="Database" value={info.database} />
          <Row label="Inference" value={info.inference_route ?? info.inference_mode} />
          <Row label="Embeddings" value={info.embedding_backend} />
          <Row
            label="Rate limits / min"
            value={`ask ${info.rate_limits.ask_per_min} · auth ${info.rate_limits.auth_per_min} · other ${info.rate_limits.default_per_min}`}
          />
          <Row label="Audit retention" value={info.audit_retention} />
        </dl>
      </Section>
    </>
  );
}
