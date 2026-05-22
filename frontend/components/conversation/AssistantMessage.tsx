"use client";

import { ArrowUpRight, Copy, Flag, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import type { AskResponse } from "@/lib/api";
import { classify, outcomeMeta } from "@/lib/outcomes";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TrustMetaBar } from "@/components/conversation/TrustExpander";
import { renderTextWithCitations, type CitationRef } from "@/components/conversation/InlineCitation";

type AssistantMessageProps = {
  result: AskResponse;
  latencyMs?: number;
  groundingScore?: number | null;
  citations: CitationRef[];
  onFocusSource?: (sourceId: string) => void;
  onEscalate?: () => void;
  onMarkResolved?: () => void;
};

const TONE_TO_BORDER = {
  answered: "border-l-grounded",
  flagged: "border-l-flagged",
  refused: "border-l-refused",
  fallback: "border-l-fallback",
} as const;

export function AssistantMessage({
  result,
  latencyMs,
  groundingScore,
  citations,
  onFocusSource,
  onEscalate,
  onMarkResolved,
}: AssistantMessageProps) {
  const kind = classify(result);
  const meta = outcomeMeta(kind);

  function copy() {
    const text = result.answer ?? result.refusal_reason ?? "";
    navigator.clipboard.writeText(text).then(() => toast.success("Copied to clipboard"));
  }

  return (
    <article
      className={cn(
        "group relative rounded-r-lg border border-l-[3px] bg-card p-4 shadow-[0_1px_0_hsl(var(--border)/.4)]",
        TONE_TO_BORDER[kind],
      )}
      data-outcome={kind}
    >
      <div className="mb-1.5 flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-foreground">GlassBox</span>
          <span>·</span>
          <span className="normal-case">{meta.shortDescription}</span>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" className="h-6 w-6 opacity-0 group-hover:opacity-100" onClick={copy} aria-label="Copy">
            <Copy className="h-3 w-3" />
          </Button>
        </div>
      </div>

      <Body
        kind={kind}
        answer={result.answer}
        refusalReason={result.refusal_reason}
        citations={citations}
        onFocusSource={onFocusSource}
      />

      <div className="mt-3 grid gap-2.5">
        <TrustMetaBar
          result={result}
          latencyMs={latencyMs}
          groundingScore={groundingScore}
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {(kind === "flagged" || kind === "refused") && (
            <Button
              variant="default"
              size="sm"
              className="h-7 gap-1.5 rounded-md text-xs"
              onClick={onEscalate}
            >
              <ShieldAlert className="h-3 w-3" />
              Escalate to compliance
            </Button>
          )}
          {kind === "answered" && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 rounded-md text-xs"
              onClick={onMarkResolved}
            >
              <Flag className="h-3 w-3" />
              Mark resolved
            </Button>
          )}
          <a
            href={`/app/audit/${result.decision_id}`}
            className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
          >
            Open replay
            <ArrowUpRight className="h-3 w-3" />
          </a>
        </div>
      </div>
    </article>
  );
}

function Body({
  kind,
  answer,
  refusalReason,
  citations,
  onFocusSource,
}: {
  kind: "answered" | "flagged" | "refused" | "fallback";
  answer: string | null;
  refusalReason: string | null;
  citations: CitationRef[];
  onFocusSource?: (sourceId: string) => void;
}) {
  if (kind === "refused" && !answer) {
    return (
      <div className="space-y-2 text-[14px] leading-7">
        <p className="font-medium text-foreground">
          Out of approved scope.
        </p>
        <p className="text-muted-foreground">
          {refusalReason ??
            "The approved document set does not cover this question. Escalate to Compliance for a human review and source expansion."}
        </p>
      </div>
    );
  }

  return (
    <div className="text-[14px] leading-7 text-foreground/95">
      {answer ? renderTextWithCitations(answer, citations, onFocusSource) : refusalReason}
    </div>
  );
}
