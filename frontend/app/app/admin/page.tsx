"use client";

import { useEffect, useState } from "react";
import { Cpu, KeyRound, Settings2, Sigma, Sliders, Users } from "lucide-react";
import { toast } from "sonner";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { getLlmStatus, type LlmStatus } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

export default function AdminPage() {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [byoKey, setByoKey] = useState("");
  const [temp, setTemp] = useState("0.1");

  useEffect(() => {
    getLlmStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  function save() {
    toast.success("Settings saved");
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
            {status === null ? (
              <Skeleton className="h-24 w-full rounded-md" />
            ) : (
              <div className="space-y-3">
                <Row
                  label="Mode"
                  value={status.local_llm ? "Local deterministic fallback" : "OpenRouter hosted"}
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

          <Section icon={KeyRound} title="Bring your own key">
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Use a stronger model for sensitive desks. Keys never leave this browser tab unless
                you confirm.
              </p>
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
              <Button onClick={save} variant="outline" className="h-9 rounded-md text-xs">
                Save key
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
              <Button className="h-9 rounded-md text-xs" onClick={save}>
                Save schedule
              </Button>
            </div>
          </Section>
        </div>

        <aside className="space-y-4">
          <Section icon={Users} title="Roles">
            <p className="text-xs text-muted-foreground">
              Switch role using the dropdown in the topbar. Real RBAC ships with Firm tier.
            </p>
            <ul className="mt-3 space-y-2 text-sm">
              <li className="rounded-md border bg-background/60 px-3 py-2">
                <div className="font-medium">Advisor</div>
                <div className="text-xs text-muted-foreground">
                  Home, Clients, Threads, Library
                </div>
              </li>
              <li className="rounded-md border bg-background/60 px-3 py-2">
                <div className="font-medium">Compliance</div>
                <div className="text-xs text-muted-foreground">
                  Review queue, Audit log, Insights
                </div>
              </li>
              <li className="rounded-md border bg-background/60 px-3 py-2">
                <div className="font-medium">Admin</div>
                <div className="text-xs text-muted-foreground">Models, keys, RBAC (this page)</div>
              </li>
            </ul>
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

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
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
