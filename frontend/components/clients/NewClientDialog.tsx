"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  ClientRecord,
  RiskProfile,
  addClient,
  loadAllClients,
  nextClientId,
} from "@/lib/clients";
import { cn } from "@/lib/utils";

const RISK_LABELS: Array<{ id: RiskProfile; label: string; hint: string }> = [
  { id: "conservative", label: "Conservative", hint: "Capital preservation" },
  { id: "moderate", label: "Moderate", hint: "Balanced growth" },
  { id: "aggressive", label: "Aggressive", hint: "Long horizon, equity-heavy" },
];

type FormState = {
  id: string;
  displayName: string;
  household: string;
  advisor: string;
  riskProfile: RiskProfile;
  aumEur: string;
  jurisdictions: string;
  maxSinglePositionPct: string;
  minLiquidWithin30dPct: string;
  ipsVersion: string;
  ipsUpdatedAt: string;
  excludedSectors: string;
  excludedRegions: string;
};

function emptyForm(suggestedId: string): FormState {
  const today = new Date().toISOString().slice(0, 10);
  return {
    id: suggestedId,
    displayName: "",
    household: "",
    advisor: "",
    riskProfile: "moderate",
    aumEur: "",
    jurisdictions: "",
    maxSinglePositionPct: "25",
    minLiquidWithin30dPct: "15",
    ipsVersion: "v1.0",
    ipsUpdatedAt: today,
    excludedSectors: "",
    excludedRegions: "",
  };
}

function parseList(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

function asPctNumber(raw: string, fallback: number): number {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0 || n > 100) return fallback;
  return Math.round(n);
}

function asAumNumber(raw: string): number {
  const cleaned = raw.replace(/[,\s€]/g, "");
  const n = Number(cleaned);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.round(n);
}

type Props = {
  trigger?: React.ReactElement;
  onCreated?: (client: ClientRecord) => void;
};

export function NewClientDialog({ trigger, onCreated }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const suggestedId = useMemo(() => nextClientId(loadAllClients()), [open]);
  const [form, setForm] = useState<FormState>(() => emptyForm(suggestedId));

  useEffect(() => {
    if (open) setForm(emptyForm(suggestedId));
  }, [open, suggestedId]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const errors = useMemo(() => {
    const e: Partial<Record<keyof FormState, string>> = {};
    if (!/^[A-Za-z0-9_-]{3,12}$/.test(form.id))
      e.id = "3–12 chars, letters/numbers only.";
    if (!form.displayName.trim()) e.displayName = "Required.";
    if (!form.household.trim()) e.household = "Required.";
    if (!form.advisor.trim()) e.advisor = "Required.";
    return e;
  }, [form]);

  const valid = Object.keys(errors).length === 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;

    const record: ClientRecord = {
      id: form.id.trim().toUpperCase(),
      displayName: form.displayName.trim(),
      household: form.household.trim(),
      advisor: form.advisor.trim(),
      riskProfile: form.riskProfile,
      aumEur: asAumNumber(form.aumEur),
      jurisdictions: parseList(form.jurisdictions).map((j) => j.toUpperCase()),
      maxSinglePositionPct: asPctNumber(form.maxSinglePositionPct, 25),
      minLiquidWithin30dPct: asPctNumber(form.minLiquidWithin30dPct, 15),
      ipsVersion: form.ipsVersion.trim() || "v1.0",
      ipsUpdatedAt: form.ipsUpdatedAt || new Date().toISOString().slice(0, 10),
      excludedSectors: parseList(form.excludedSectors),
      excludedRegions: parseList(form.excludedRegions),
    };

    try {
      addClient(record);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add client");
      return;
    }

    toast.success(`${record.id} added to roster`, {
      description: `${record.displayName} · IPS ${record.ipsVersion}`,
    });
    setOpen(false);
    onCreated?.(record);
    router.push(`/app/clients/${record.id}`);
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          trigger ?? (
            <Button className="h-9 gap-1.5 rounded-md">
              <Plus className="h-3.5 w-3.5" />
              New client
            </Button>
          )
        }
      />
      <SheetContent
        side="right"
        className="flex w-full max-w-[480px] flex-col gap-0 p-0 sm:max-w-[480px]"
      >
        <SheetHeader className="border-b px-5 py-4">
          <SheetTitle className="font-serif text-lg font-semibold tracking-tight">
            Add a client to the roster
          </SheetTitle>
          <SheetDescription>
            Stored locally for the session. In production, client master data
            comes from your CRM.
          </SheetDescription>
        </SheetHeader>

        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
            <FieldGroup title="Identification">
              <Row>
                <Field label="Client ID" error={errors.id}>
                  <Input
                    value={form.id}
                    onChange={(e) => update("id", e.target.value.toUpperCase())}
                    placeholder={suggestedId}
                    className="font-mono"
                  />
                </Field>
                <Field label="Advisor" error={errors.advisor}>
                  <Input
                    value={form.advisor}
                    onChange={(e) => update("advisor", e.target.value)}
                    placeholder="S. Kühn"
                  />
                </Field>
              </Row>
              <Field label="Display name" error={errors.displayName}>
                <Input
                  value={form.displayName}
                  onChange={(e) => update("displayName", e.target.value)}
                  placeholder="Müller Family Office"
                />
              </Field>
              <Field label="Household" error={errors.household}>
                <Input
                  value={form.household}
                  onChange={(e) => update("household", e.target.value)}
                  placeholder="DACH · Zurich"
                />
              </Field>
            </FieldGroup>

            <FieldGroup title="Mandate">
              <Field label="Risk profile">
                <div className="grid grid-cols-3 gap-1.5">
                  {RISK_LABELS.map((opt) => {
                    const active = form.riskProfile === opt.id;
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        onClick={() => update("riskProfile", opt.id)}
                        className={cn(
                          "rounded-md border px-2.5 py-2 text-left text-sm transition-colors",
                          active
                            ? "border-primary/40 bg-accent/50"
                            : "bg-background hover:bg-accent/30",
                        )}
                      >
                        <div className="font-medium">{opt.label}</div>
                        <div className="text-[11px] text-muted-foreground">{opt.hint}</div>
                      </button>
                    );
                  })}
                </div>
              </Field>

              <Row>
                <Field label="AUM (EUR)">
                  <Input
                    inputMode="numeric"
                    value={form.aumEur}
                    onChange={(e) => update("aumEur", e.target.value)}
                    placeholder="18000000"
                  />
                </Field>
                <Field label="Jurisdictions">
                  <Input
                    value={form.jurisdictions}
                    onChange={(e) => update("jurisdictions", e.target.value)}
                    placeholder="CH, US"
                  />
                </Field>
              </Row>

              <Row>
                <Field label="Single position cap (%)">
                  <Input
                    inputMode="numeric"
                    value={form.maxSinglePositionPct}
                    onChange={(e) => update("maxSinglePositionPct", e.target.value)}
                  />
                </Field>
                <Field label="Liquidity floor 30d (%)">
                  <Input
                    inputMode="numeric"
                    value={form.minLiquidWithin30dPct}
                    onChange={(e) => update("minLiquidWithin30dPct", e.target.value)}
                  />
                </Field>
              </Row>
            </FieldGroup>

            <FieldGroup title="Exclusions">
              <Field
                label="Excluded sectors"
                hint="Comma-separated · e.g. tobacco, firearms"
              >
                <Input
                  value={form.excludedSectors}
                  onChange={(e) => update("excludedSectors", e.target.value)}
                  placeholder="tobacco, firearms"
                />
                {parseList(form.excludedSectors).length > 0 ? (
                  <ChipPreview items={parseList(form.excludedSectors)} />
                ) : null}
              </Field>
              <Field
                label="Excluded regions"
                hint="Comma-separated · e.g. russia, sanctioned_markets"
              >
                <Input
                  value={form.excludedRegions}
                  onChange={(e) => update("excludedRegions", e.target.value)}
                  placeholder="russia"
                />
                {parseList(form.excludedRegions).length > 0 ? (
                  <ChipPreview items={parseList(form.excludedRegions)} />
                ) : null}
              </Field>
            </FieldGroup>

            <FieldGroup title="Investment Policy Statement">
              <Row>
                <Field label="Version">
                  <Input
                    value={form.ipsVersion}
                    onChange={(e) => update("ipsVersion", e.target.value)}
                    placeholder="v1.0"
                    className="font-mono"
                  />
                </Field>
                <Field label="Updated">
                  <Input
                    type="date"
                    value={form.ipsUpdatedAt}
                    onChange={(e) => update("ipsUpdatedAt", e.target.value)}
                  />
                </Field>
              </Row>
            </FieldGroup>
          </div>

          <SheetFooter className="border-t p-4">
            <div className="flex w-full items-center justify-between gap-2">
              <SheetClose
                render={
                  <Button type="button" variant="ghost" className="h-9 rounded-md">
                    Cancel
                  </Button>
                }
              />
              <Button type="submit" disabled={!valid} className="h-9 rounded-md">
                Add client
              </Button>
            </div>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function FieldGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h3 className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3">{children}</div>;
}

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </Label>
      {children}
      {error ? (
        <div className="text-[11px] text-destructive">{error}</div>
      ) : hint ? (
        <div className="text-[11px] text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}

function ChipPreview({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((it) => (
        <span
          key={it}
          className="inline-flex items-center gap-1 rounded-sm border bg-card px-1.5 py-0.5 text-[11px] capitalize"
        >
          {it.replace("_", " ")}
        </span>
      ))}
    </div>
  );
}
