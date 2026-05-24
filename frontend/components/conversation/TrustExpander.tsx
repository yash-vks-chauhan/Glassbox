"use client";

import { useState } from "react";
import { ChevronDown, Hash, Layers, Sigma } from "lucide-react";

import type { AskResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  result: AskResponse;
  latencyMs?: number;
  groundingScore?: number | null;
};

function fmtPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function fmtMs(value: number | null | undefined) {
  return typeof value === "number" ? `${value}ms` : "—";
}

export function TrustMetaBar({ result, latencyMs, groundingScore }: Props) {
  const [open, setOpen] = useState(false);
  const sourceCount = result.citations.length;
  const grounding = groundingScore ?? result.trust.grounding_score;

  return (
    <div
      className={cn(
        "rounded-md border border-border/60 bg-card/60 text-[11px] transition-colors",
        open && "bg-card",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left uppercase tracking-[0.14em] text-muted-foreground hover:text-foreground"
      >
        <Trust kind={result.outcome as "answered" | "flagged" | "refused" | "fallback"} />
        <Separator />
        <span>{sourceCount} source{sourceCount === 1 ? "" : "s"}</span>
        {latencyMs ? (
          <>
            <Separator />
            <span className="tabular">{latencyMs}ms</span>
          </>
        ) : null}
        <Separator />
        <span className="truncate font-mono normal-case">
          #{result.decision_id.slice(0, 8)}
        </span>
        <ChevronDown
          className={cn(
            "ml-auto h-3 w-3 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open ? (
        <div className="grid gap-2 border-t border-border/60 p-2.5 text-[12px] normal-case">
          <Row icon={Sigma} label="Grounding score" value={fmtPct(grounding)} />
          <Row
            icon={Layers}
            label="Determinism"
            value={fmtPct(result.trust.determinism_score)}
            hint="Nightly job · 24h avg"
          />
          <Row
            icon={Hash}
            label="Model route"
            value={
              <code className="font-mono text-[11px] text-foreground">
                {result.trust.model_route ?? "not reported"}
              </code>
            }
          />
          <Row
            icon={Layers}
            label="Latency path"
            value={`${fmtMs(result.trust.retrieval_ms)} retrieve · ${fmtMs(result.trust.generation_ms)} generate · ${fmtMs(result.trust.verification_ms)} verify`}
          />
          <Row
            icon={Sigma}
            label="Evidence quality"
            value={fmtPct(result.trust.evidence_quality)}
            hint={result.trust.cache_hit ? "cache hit" : "fresh retrieval"}
          />
          <Row
            icon={Hash}
            label="Decision ID"
            value={
              <code className="font-mono text-[11px] text-foreground">
                {result.decision_id}
              </code>
            }
          />
          <a
            href={`/app/audit/${result.decision_id}`}
            className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline"
          >
            Open full replay →
          </a>
        </div>
      ) : null}
    </div>
  );
}

function Separator() {
  return <span className="text-border">·</span>;
}

function Trust({ kind }: { kind: "answered" | "flagged" | "refused" | "fallback" }) {
  const tokenMap = { answered: "grounded", flagged: "flagged", refused: "refused", fallback: "fallback" } as const;
  const labelMap = {
    answered: "Grounded",
    flagged: "Flagged",
    refused: "Refused",
    fallback: "Fallback",
  };
  const token = tokenMap[kind] ?? "refused";
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: `hsl(var(--state-${token}))` }}
      />
      {labelMap[kind] ?? "Refused"}
    </span>
  );
}

function Row({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Sigma;
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        <Icon className="h-3 w-3" />
        <span>{label}</span>
      </span>
      <span className="text-right">
        <span className="text-foreground tabular">{value}</span>
        {hint ? <span className="ml-1.5 text-[11px]">{hint}</span> : null}
      </span>
    </div>
  );
}
