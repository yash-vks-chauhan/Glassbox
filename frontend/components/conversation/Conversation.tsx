"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, ScanSearch } from "lucide-react";

import {
  askStream,
  createEscalation,
  type AskResponse,
  type AskStreamEvent,
  type Escalation,
} from "@/lib/api";
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
  error?: string;
  escalation?: Escalation | null;
  escalating?: boolean;
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

function decorateCitations(result: AskResponse): CitationRef[] {
  const seen = new Set<string>();
  const refs: CitationRef[] = [];
  result.citations.forEach((c) => {
    const key = `${c.source_id}:${c.source_type}:${c.snippet}`;
    if (seen.has(key)) return;
    seen.add(key);
    refs.push({
      index: refs.length + 1,
      sourceId: c.source_id,
      sourceType: c.source_type,
      snippet: c.snippet,
    });
  });
  return refs;
}

function injectCitationTokens(text: string, count: number): string {
  if (!text) return text;
  if (/\[(?:\d+|[A-Z][A-Z0-9_-]+)\]/.test(text)) return text;
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
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
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
    setStreamStatus("Request accepted");
    const t0 = performance.now();
    try {
      const result = await askStream(
        { question: text, client_id: client.id },
        (event) => setStreamStatus(statusForEvent(event)),
      );
      const latencyMs = result.trust.total_ms ?? Math.round(performance.now() - t0);
      const decorated = decorateCitations(result);
      const answerWithTokens = result.answer
        ? injectCitationTokens(result.answer, decorated.length)
        : null;
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
      const message = err instanceof Error ? err.message : "Backend unavailable.";
      setMessages((m) => [
        ...m,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          error: message,
          timestamp: new Date().toISOString(),
        },
      ]);
      toast.error("Request failed", {
        description: message,
      });
    } finally {
      setLoading(false);
      setStreamStatus(null);
    }
  }

  function updateMessage(
    decisionId: string,
    patch: Partial<Pick<Message, "escalation" | "escalating">>,
  ) {
    setMessages((items) =>
      items.map((item) =>
        item.result?.decision_id === decisionId ? { ...item, ...patch } : item,
      ),
    );
  }

  async function handleEscalate(result: AskResponse) {
    updateMessage(result.decision_id, { escalating: true });
    try {
      const escalation = await createEscalation({
        decision_id: result.decision_id,
        reason: result.outcome === "flagged" ? "flagged_decision_review" : "insufficient_evidence_review",
        note: result.refusal_reason ?? result.answer ?? null,
      });
      updateMessage(result.decision_id, { escalation, escalating: false });
      toast.success("Escalation opened", {
        description: `Compliance owns it now · SLA ${new Date(escalation.sla_due_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}`,
      });
    } catch (err) {
      updateMessage(result.decision_id, { escalating: false });
      toast.error("Escalation failed", {
        description: err instanceof Error ? err.message : "Could not create escalation.",
      });
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
              return m.error ? (
                <InlineErrorMessage key={m.id} message={m.error} />
              ) : (
                <AssistantMessage
                  key={m.id}
                  result={m.result!}
                  latencyMs={m.latencyMs}
                  groundingScore={m.groundingScore}
                  citations={m.citations ?? []}
                  escalation={m.escalation}
                  escalating={m.escalating}
                  onFocusSource={(id) => {
                    setFocusedSourceId(id);
                    setPanelOpen(true);
                  }}
                  onEscalate={() => handleEscalate(m.result!)}
                  onMarkResolved={() => toast.success("Marked resolved")}
                />
              );
            })}

            {loading ? <Thinking status={streamStatus} /> : null}
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

function InlineErrorMessage({ message }: { message: string }) {
  return (
    <div className="rounded-r-lg border border-l-[3px] border-l-destructive bg-card p-4 text-sm">
      <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        GlassBox · request failed
      </div>
      <p className="mt-2 text-foreground">
        I could not complete that request. {message}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        The question stayed in the thread so an advisor can retry or escalate with context.
      </p>
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

function Thinking({ status }: { status: string | null }) {
  return (
    <div className="flex items-center gap-3 px-3">
      <span className="inline-flex h-2 w-2 animate-pulse rounded-full" style={{ background: "hsl(var(--state-grounded))" }} />
      <span className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">
        {status ?? "Retrieving sources, verifying claims..."}
      </span>
    </div>
  );
}

function statusForEvent(event: AskStreamEvent): string {
  if (event.event === "accepted") return "Request accepted";
  if (event.event === "retrieval_done") return "Evidence retrieved";
  if (event.event === "generation_started") return "Generating grounded answer";
  if (event.event === "verification_done") return "Verifying citations";
  if (event.event === "final") return "Final decision ready";
  return "Request failed";
}
