"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, MessageSquarePlus, RotateCcw, ScanSearch } from "lucide-react";

import {
  ApiError,
  RateLimitedError,
  UnauthorizedError,
  askStream,
  createEscalation,
  getThread,
  listThreads,
  updateThread,
  type AskResponse,
  type AskStreamEvent,
  type ThreadDetail,
  type ThreadSummary,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
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
  /** For a follow-up: the standalone question it was answered as. */
  interpretedAs?: string | null;
  result?: AskResponse;
  latencyMs?: number;
  groundingScore?: number | null;
  citations?: CitationRef[];
  error?: string;
  errorTitle?: string;
  retryQuestion?: string;
  escalation?: { status: string } | null;
  escalating?: boolean;
  timestamp: string;
};

type Props = {
  client: ClientRecord;
  /** The open thread, or null for a new conversation. */
  threadId: string | null;
  onThreadChange: (threadId: string | null) => void;
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

function assistantMessage(result: AskResponse, timestamp: string, latencyMs?: number): Message {
  const citations = decorateCitations(result);
  return {
    id: result.decision_id,
    role: "assistant",
    result: {
      ...result,
      answer: result.answer ? injectCitationTokens(result.answer, citations.length) : null,
    },
    latencyMs: latencyMs ?? result.trust.total_ms ?? undefined,
    groundingScore: result.trust.grounding_score,
    citations,
    timestamp,
  };
}

function messagesFromThread(thread: ThreadDetail): Message[] {
  return thread.messages.flatMap((m) => [
    {
      id: `u-${m.decision_id}`,
      role: "user" as const,
      text: m.question,
      interpretedAs: m.retrieval_question,
      timestamp: m.created_at,
    },
    {
      ...assistantMessage({ ...m, thread_id: thread.id }, m.created_at),
      escalation: m.escalation,
    },
  ]);
}

/** The conversation on screen and the thread it belongs to. */
type View = {
  threadId: string | null;
  messages: Message[];
  /** Set when this component has just saved a new conversation as
   * `threadId`: until the URL catches up, a null `threadId` prop still
   * means this conversation. */
  awaitingUrl: boolean;
};

const NEW_VIEW: View = { threadId: null, messages: [], awaitingUrl: false };
const NO_MESSAGES: Message[] = [];

function shows(view: View, threadId: string | null): boolean {
  return view.threadId === threadId || (view.awaitingUrl && threadId === null);
}

let messageSeq = 0;
function nextMessageId(prefix: string): string {
  messageSeq += 1;
  return `${prefix}-${messageSeq}`;
}

function fetchThreads(clientId: string): Promise<ThreadSummary[]> {
  return listThreads({ client_id: clientId }).catch(() => []);
}

function initials(name: string | null | undefined, email: string | undefined) {
  const source = name?.trim() || email?.split("@")[0] || "";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase() || "?";
}

export function Conversation({ client, threadId, onThreadChange }: Props) {
  const { user } = useAuth();
  const [view, setView] = useState<View>(NEW_VIEW);
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [focusedSourceId, setFocusedSourceId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);

  // The URL caught up with a conversation saved here, so from now on a
  // null threadId means a new conversation again.
  if (view.awaitingUrl && view.threadId === threadId) {
    setView({ ...view, awaitingUrl: false });
  }
  const current = shows(view, threadId);
  const messages = current ? view.messages : NO_MESSAGES;
  const loadingThread = !current && threadId !== null;

  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, loading]);

  useEffect(() => {
    let active = true;
    fetchThreads(client.id).then((rows) => {
      if (active) setThreads(rows);
    });
    return () => {
      active = false;
    };
  }, [client.id]);

  async function refreshThreads() {
    setThreads(await fetchThreads(client.id));
  }

  // Open the thread in the URL, unless it is already on screen.
  useEffect(() => {
    if (current || threadId === null) return;
    let active = true;
    getThread(threadId)
      .then((thread) => {
        if (active) setView({ threadId, messages: messagesFromThread(thread), awaitingUrl: false });
      })
      .catch((err) => {
        if (!active) return;
        toast.error("Could not open thread", {
          description: err instanceof Error ? err.message : undefined,
        });
        onThreadChange(null);
      });
    return () => {
      active = false;
    };
  }, [current, threadId, onThreadChange]);

  // Put a conversation that was just saved as a thread into the URL.
  useEffect(() => {
    if (view.awaitingUrl && threadId === null && view.threadId) onThreadChange(view.threadId);
  }, [view.awaitingUrl, view.threadId, threadId, onThreadChange]);

  const activeThread = threads?.find((t) => t.id === threadId) ?? null;

  const lastAssistant = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant"),
    [messages],
  );
  const evidenceCitations = lastAssistant?.citations ?? [];

  async function handleSubmit(text: string) {
    // Ask in the conversation on screen, which may be a just-saved thread
    // the URL hasn't caught up with yet.
    const askThreadId = current ? view.threadId : null;
    const userMsg: Message = {
      id: nextMessageId("u"),
      role: "user",
      text,
      timestamp: new Date().toISOString(),
    };
    // If another thread was opened while waiting, the reply doesn't belong there.
    const holdsQuestion = (v: View) => v.messages.some((m) => m.id === userMsg.id);
    setView((v) =>
      shows(v, threadId)
        ? { ...v, messages: [...v.messages, userMsg] }
        : { ...NEW_VIEW, messages: [userMsg] },
    );
    setLoading(true);
    setStreamStatus("Request accepted");
    const t0 = performance.now();
    try {
      const result = await askStream(
        { question: text, client_id: client.id, thread_id: askThreadId },
        (event) => setStreamStatus(statusForEvent(event)),
      );
      const latencyMs = result.trust.total_ms ?? Math.round(performance.now() - t0);
      const reply = assistantMessage(result, new Date().toISOString(), latencyMs);
      const startedThread = askThreadId === null ? result.thread_id : null;
      setView((v) =>
        holdsQuestion(v)
          ? {
              threadId: startedThread ?? v.threadId,
              awaitingUrl: startedThread ? true : v.awaitingUrl,
              messages: [
                ...v.messages.map((item) =>
                  item.id === userMsg.id ? { ...item, interpretedAs: result.retrieval_question } : item,
                ),
                reply,
              ],
            }
          : v,
      );
      void refreshThreads();
      toast.success(`Decision ${result.outcome}`, {
        description: `Logged as ${result.decision_id.slice(0, 8)}.`,
      });
    } catch (err) {
      const { title, message } = describeAskError(err);
      const errorMsg: Message = {
        id: nextMessageId("err"),
        role: "assistant",
        error: message,
        errorTitle: title,
        retryQuestion: text,
        timestamp: new Date().toISOString(),
      };
      setView((v) => (holdsQuestion(v) ? { ...v, messages: [...v.messages, errorMsg] } : v));
      toast.error(title, {
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
    setView((v) => ({
      ...v,
      messages: v.messages.map((item) =>
        item.result?.decision_id === decisionId ? { ...item, ...patch } : item,
      ),
    }));
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
      void refreshThreads();
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

  async function handleResolveThread() {
    if (!threadId) return;
    try {
      await updateThread(threadId, { status: "resolved" });
      toast.success("Thread marked resolved", {
        description: "Asking a new question here reopens it.",
      });
      void refreshThreads();
    } catch (err) {
      toast.error("Could not resolve thread", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }

  function startNewThread() {
    setView(NEW_VIEW);
    onThreadChange(null);
  }

  return (
    <div className="flex h-[calc(100vh-9.5rem)] w-full">
      {/* Threads rail */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/40 xl:flex">
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          Threads
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-[11px] normal-case tracking-normal"
            onClick={startNewThread}
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            New
          </Button>
        </div>
        <ul className="flex-1 space-y-0.5 overflow-auto p-1.5 text-sm">
          {threadId === null ? (
            <li className="rounded-md bg-accent/60 px-2.5 py-1.5">
              <div className="text-[13px] font-medium">New conversation</div>
              <div className="text-[11px] text-muted-foreground">Starts when you ask</div>
            </li>
          ) : null}
          {threads === null ? (
            <li className="px-2.5 py-1.5 text-[11px] text-muted-foreground">Loading…</li>
          ) : threads.length === 0 && threadId === null ? null : (
            threads.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => onThreadChange(t.id)}
                  className={cn(
                    "w-full rounded-md px-2.5 py-1.5 text-left transition-colors",
                    t.id === threadId ? "bg-accent/60" : "hover:bg-accent/30",
                  )}
                >
                  <div className="line-clamp-2 text-[13px] font-medium leading-5">{t.title}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <ThreadStatusDot status={t.status} />
                    {t.status} · {t.message_count} question{t.message_count === 1 ? "" : "s"}
                  </div>
                </button>
              </li>
            ))
          )}
        </ul>
      </aside>

      {/* Conversation column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-5 py-5 lg:px-8"
        >
          <div className="mx-auto max-w-3xl space-y-4">
            {loadingThread ? (
              <div className="text-center text-sm text-muted-foreground">Loading thread…</div>
            ) : messages.length === 0 ? (
              <EmptyState clientName={client.displayName} />
            ) : null}

            {messages.map((m) => {
              if (m.role === "user") {
                return (
                  <div key={m.id} className="flex items-start gap-3">
                    <span
                      className="mt-1 inline-flex h-6 w-6 items-center justify-center rounded-md bg-secondary text-[10px] font-medium text-secondary-foreground"
                      title={user?.email}
                    >
                      {initials(user?.display_name, user?.email)}
                    </span>
                    <div className="flex-1 rounded-r-lg border border-l-[3px] border-l-primary/60 bg-background p-3 text-[14px] leading-7">
                      <p>{m.text}</p>
                      {m.interpretedAs ? (
                        <div className="mt-1 text-[12px] leading-5 text-muted-foreground">
                          Answered as: <span className="text-foreground/80">{m.interpretedAs}</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              }
              return m.error ? (
                <InlineErrorMessage
                  key={m.id}
                  title={m.errorTitle}
                  message={m.error}
                  retryQuestion={m.retryQuestion}
                  onRetry={handleSubmit}
                />
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
                  threadResolved={activeThread?.status === "resolved"}
                  onMarkResolved={threadId ? handleResolveThread : undefined}
                />
              );
            })}

            {loading ? <Thinking status={streamStatus} /> : null}
          </div>
        </div>

        <div className="border-t bg-background/85 px-5 pb-5 pt-3 lg:px-8 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <div className="mx-auto max-w-3xl">
            <Composer
              disabled={loading || loadingThread}
              onSubmit={handleSubmit}
              suggestions={messages.length === 0 && !loadingThread ? SUGGESTIONS : []}
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

function ThreadStatusDot({ status }: { status: ThreadSummary["status"] }) {
  const color =
    status === "escalated"
      ? "var(--state-flagged)"
      : status === "resolved"
        ? "var(--state-grounded)"
        : "var(--muted-foreground)";
  return <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: `hsl(${color})` }} />;
}

function InlineErrorMessage({
  title = "GlassBox · request failed",
  message,
  retryQuestion,
  onRetry,
}: {
  title?: string;
  message: string;
  retryQuestion?: string;
  onRetry: (question: string) => void;
}) {
  return (
    <div className="rounded-r-lg border border-l-[3px] border-l-destructive bg-card p-4 text-sm">
      <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {title}
      </div>
      <p className="mt-2 text-foreground">
        {message}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {retryQuestion ? (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 rounded-md text-xs"
            onClick={() => onRetry(retryQuestion)}
          >
            <RotateCcw className="h-3 w-3" />
            Retry
          </Button>
        ) : null}
        <span className="text-xs text-muted-foreground">
          The question stayed in the thread with its context.
        </span>
      </div>
    </div>
  );
}

function describeAskError(err: unknown): { title: string; message: string } {
  if (err instanceof RateLimitedError) {
    return {
      title: "GlassBox · rate limited",
      message: `The ask tier is temporarily full. Retry in about ${err.retryAfter} second${err.retryAfter === 1 ? "" : "s"}.`,
    };
  }
  if (err instanceof UnauthorizedError) {
    return {
      title: "GlassBox · session expired",
      message: "Sign in again, then retry the saved question from this thread.",
    };
  }
  if (err instanceof ApiError && err.status === 503) {
    return {
      title: "GlassBox · model route unavailable",
      message:
        typeof err.detail === "object" && err.detail && "detail" in err.detail
          ? String((err.detail as { detail?: unknown }).detail)
          : "Production inference is blocked or the active model route is unavailable.",
    };
  }
  return {
    title: "GlassBox · request failed",
    message: err instanceof Error ? err.message : "Backend unavailable.",
  };
}

function EmptyState({ clientName }: { clientName: string }) {
  return (
    <div className="rounded-xl border border-dashed bg-card/40 p-8 text-center">
      <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-secondary text-primary">
        <ScanSearch className="h-5 w-5" />
      </div>
      <h2 className="font-serif text-[18px] font-semibold tracking-tight">
        Ask anything within {clientName}&apos;s mandate.
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
