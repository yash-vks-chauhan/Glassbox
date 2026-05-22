"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, ScanSearch } from "lucide-react";

import { ask, type AskResponse } from "@/lib/api";
import { type ClientRecord } from "@/lib/clients";
import { AssistantMessage } from "@/components/conversation/AssistantMessage";
import { Composer } from "@/components/conversation/Composer";
import { EvidencePanel } from "@/components/conversation/EvidencePanel";
import type { CitationRef } from "@/components/conversation/InlineCitation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Message = {
  id: string;
  role: "user" | "assistant";
  text?: string;
  result?: AskResponse;
  latencyMs?: number;
  groundingScore?: number | null;
  citations?: CitationRef[];
  timestamp: string;
};

type Props = {
  client: ClientRecord;
};

const SUGGESTIONS = [
  "Can client move 40% into fund F100?",
  "Is fund F100 suitable for this client?",
  "Summarise this client's mandate constraints.",
];

function decorateCitations(result: AskResponse, answerText: string | null): CitationRef[] {
  const text = answerText ?? "";
  // If the model already emitted [1], [2] tokens, keep them.
  const tokens = Array.from(text.matchAll(/\[(\d+)\]/g)).map((m) => Number(m[1]));
  const uniqueTokens = Array.from(new Set(tokens));
  if (uniqueTokens.length && result.citations.length >= uniqueTokens.length) {
    return uniqueTokens.map((n, i) => {
      const c = result.citations[Math.min(i, result.citations.length - 1)];
      return {
        index: n,
        sourceId: c.source_id,
        sourceType: c.source_type,
        snippet: c.snippet,
      };
    });
  }
  // Otherwise number sequentially from the citations array.
  return result.citations.map((c, i) => ({
    index: i + 1,
    sourceId: c.source_id,
    sourceType: c.source_type,
    snippet: c.snippet,
  }));
}

function injectCitationTokens(text: string, count: number): string {
  if (!text) return text;
  if (/\[\d+\]/.test(text)) return text;
  if (count === 0) return text;
  // Append a footnote run at the end so users have a clickable target.
  const tokens = Array.from({ length: count }, (_, i) => `[${i + 1}]`).join("");
  // If sentence ends with a period, drop tokens before it.
  if (/[.!?]\s*$/.test(text)) {
    return text.replace(/([.!?])\s*$/, ` ${tokens}$1`);
  }
  return `${text} ${tokens}`;
}

export function Conversation({ client }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [focusedSourceId, setFocusedSourceId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, loading]);

  const lastAssistant = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant"),
    [messages],
  );
  const evidenceCitations = lastAssistant?.citations ?? [];

  async function handleSubmit(text: string) {
    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: "user",
      text,
      timestamp: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    setLoading(true);
    const t0 = performance.now();
    try {
      const result = await ask({ question: text, client_id: client.id });
      const latencyMs = Math.round(performance.now() - t0);
      const answerWithTokens = result.answer
        ? injectCitationTokens(result.answer, result.citations.length)
        : null;
      const decorated = decorateCitations(result, answerWithTokens);
      const enriched: AskResponse = { ...result, answer: answerWithTokens };
      setMessages((m) => [
        ...m,
        {
          id: result.decision_id,
          role: "assistant",
          result: enriched,
          latencyMs,
          groundingScore: result.trust.grounding_score,
          citations: decorated,
          timestamp: new Date().toISOString(),
        },
      ]);
      toast.success(`Decision ${result.outcome}`, {
        description: `Logged as ${result.decision_id.slice(0, 8)}.`,
      });
    } catch (err) {
      toast.error("Request failed", {
        description: err instanceof Error ? err.message : "Backend unavailable.",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-[calc(100vh-9.5rem)] w-full">
      {/* Threads rail */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/40 xl:flex">
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          Threads
          <Button variant="ghost" size="icon-sm" className="h-6 w-6">+</Button>
        </div>
        <ul className="flex-1 overflow-auto p-1.5 text-sm">
          <li>
            <button className="w-full rounded-md bg-accent/60 px-2.5 py-1.5 text-left">
              <div className="text-[13px] font-medium">Current conversation</div>
              <div className="text-[11px] text-muted-foreground">
                {messages.length === 0 ? "No messages" : `${messages.length} messages`}
              </div>
            </button>
          </li>
          <li className="mt-1 px-2.5 py-1 text-[11px] text-muted-foreground">
            Previous conversations will appear here.
          </li>
        </ul>
      </aside>

      {/* Conversation column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-5 py-5 lg:px-8"
        >
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.length === 0 ? (
              <EmptyState clientName={client.displayName} />
            ) : null}

            {messages.map((m) => {
              if (m.role === "user") {
                return (
                  <div key={m.id} className="flex items-start gap-3">
                    <span className="mt-1 inline-flex h-6 w-6 items-center justify-center rounded-md bg-secondary text-[10px] font-medium text-secondary-foreground">
                      SK
                    </span>
                    <div className="flex-1 rounded-r-lg border border-l-[3px] border-l-primary/60 bg-background p-3 text-[14px] leading-7">
                      {m.text}
                    </div>
                  </div>
                );
              }
              return (
                <AssistantMessage
                  key={m.id}
                  result={m.result!}
                  latencyMs={m.latencyMs}
                  groundingScore={m.groundingScore}
                  citations={m.citations ?? []}
                  onFocusSource={(id) => {
                    setFocusedSourceId(id);
                    setPanelOpen(true);
                  }}
                  onEscalate={() => toast("Escalation routed", { description: "Compliance · DACH desk" })}
                  onMarkResolved={() => toast.success("Marked resolved")}
                />
              );
            })}

            {loading ? <Thinking /> : null}
          </div>
        </div>

        <div className="border-t bg-background/85 px-5 pb-5 pt-3 lg:px-8 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <div className="mx-auto max-w-3xl">
            <Composer
              disabled={loading}
              onSubmit={handleSubmit}
              suggestions={messages.length === 0 ? SUGGESTIONS : []}
              placeholder={`Ask about ${client.displayName} (${client.id})…`}
            />
          </div>
        </div>
      </div>

      {/* Evidence panel */}
      <div
        className={cn(
          "relative hidden shrink-0 border-l border-border/60 bg-card/30 lg:flex",
          panelOpen ? "w-[340px]" : "w-9",
        )}
      >
        <button
          type="button"
          onClick={() => setPanelOpen((v) => !v)}
          className="absolute top-3 -left-3 z-10 hidden h-6 w-6 items-center justify-center rounded-full border bg-card text-muted-foreground shadow-sm hover:text-foreground lg:flex"
          aria-label={panelOpen ? "Collapse evidence" : "Expand evidence"}
        >
          {panelOpen ? <ChevronRight className="h-3 w-3" /> : <ChevronLeft className="h-3 w-3" />}
        </button>
        {panelOpen ? (
          <EvidencePanel
            citations={evidenceCitations}
            focusedSourceId={focusedSourceId}
            onFocusChange={setFocusedSourceId}
          />
        ) : (
          <div className="flex h-full items-start justify-center pt-3 text-muted-foreground">
            <ScanSearch className="h-4 w-4" />
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ clientName }: { clientName: string }) {
  return (
    <div className="rounded-xl border border-dashed bg-card/40 p-8 text-center">
      <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-secondary text-primary">
        <ScanSearch className="h-5 w-5" />
      </div>
      <h2 className="font-serif text-[18px] font-semibold tracking-tight">
        Ask anything within {clientName}'s mandate.
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
        Every answer cites the IPS clauses, factsheets, and regulatory snippets it relied on.
        Out-of-scope questions are refused — not invented.
      </p>
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex items-center gap-3 px-3">
      <span className="inline-flex h-2 w-2 animate-pulse rounded-full" style={{ background: "hsl(var(--state-grounded))" }} />
      <span className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">
        Retrieving sources, verifying claims…
      </span>
    </div>
  );
}
