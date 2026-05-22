"use client";

import { useEffect, useRef } from "react";
import { ChevronRight, FileText } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { CitationRef } from "@/components/conversation/InlineCitation";

type Props = {
  citations: CitationRef[];
  focusedSourceId?: string | null;
  onFocusChange?: (sourceId: string) => void;
};

export function EvidencePanel({ citations, focusedSourceId, onFocusChange }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!focusedSourceId || !containerRef.current) return;
    const target = containerRef.current.querySelector<HTMLElement>(
      `[data-source-id="${focusedSourceId}"]`,
    );
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.animate(
        [
          { background: "hsl(var(--accent))" },
          { background: "transparent" },
        ],
        { duration: 1100, easing: "ease-out" },
      );
    }
  }, [focusedSourceId]);

  if (!citations.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-muted-foreground">
        <FileText className="h-5 w-5 opacity-40" />
        <p>No evidence has been retrieved yet.</p>
        <p className="text-xs">
          Ask a grounded question and the cited sources will land here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b px-4 py-2.5">
        <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Evidence
        </div>
        <div className="text-[11px] tabular text-muted-foreground">
          {citations.length} source{citations.length === 1 ? "" : "s"}
        </div>
      </header>
      <ScrollArea className="flex-1">
        <div ref={containerRef} className="space-y-3 p-3">
          {citations.map((citation) => (
            <button
              key={`${citation.sourceId}-${citation.index}`}
              type="button"
              data-source-id={citation.sourceId}
              onClick={() => onFocusChange?.(citation.sourceId)}
              className={cn(
                "block w-full rounded-md border bg-card p-3 text-left transition-colors",
                focusedSourceId === citation.sourceId
                  ? "border-primary/40 bg-accent/60"
                  : "hover:bg-accent/30",
              )}
            >
              <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <span
                    className="inline-flex h-[14px] min-w-[14px] items-center justify-center rounded-[3px] border bg-card px-[3px] text-[10px] font-medium leading-none text-primary"
                  >
                    {citation.index}
                  </span>
                  <span className="font-mono">{citation.sourceType}</span>
                  <span className="font-mono normal-case text-foreground/80">
                    {citation.sourceId}
                  </span>
                </div>
                <ChevronRight className="h-3 w-3 opacity-50" />
              </div>
              <p className="text-[13px] leading-6 text-foreground/85">{citation.snippet}</p>
            </button>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
