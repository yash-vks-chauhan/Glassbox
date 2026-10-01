"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, MessageSquare, Search } from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { listThreads, type ThreadStatus, type ThreadSummary } from "@/lib/api";
import { useClients } from "@/lib/clients-hooks";
import { threadHref } from "@/lib/threads";
import { cn } from "@/lib/utils";

const STATUSES: Array<{ id: ThreadStatus | "all"; label: string }> = [
  { id: "all", label: "All" },
  { id: "open", label: "Open" },
  { id: "escalated", label: "Escalated" },
  { id: "resolved", label: "Resolved" },
];

const STATUS_TONE: Record<ThreadStatus, string> = {
  open: "bg-background",
  escalated: "state-flagged",
  resolved: "state-grounded",
};

export default function ThreadsPage() {
  const { clients } = useClients();
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [status, setStatus] = useState<ThreadStatus | "all">("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    setThreads(null);
    listThreads({ status: status === "all" ? undefined : status, limit: 200 })
      .then((rows) => active && setThreads(rows))
      .catch(() => active && setThreads([]));
    return () => {
      active = false;
    };
  }, [status]);

  const filtered = useMemo(() => {
    if (!threads) return null;
    const needle = query.trim().toLowerCase();
    if (!needle) return threads;
    return threads.filter((t) => {
      const client = clients.find((c) => c.id === t.client_id);
      return (
        t.title.toLowerCase().includes(needle) ||
        (t.last_question ?? "").toLowerCase().includes(needle) ||
        t.client_id.toLowerCase().includes(needle) ||
        (client?.displayName ?? "").toLowerCase().includes(needle)
      );
    });
  }, [threads, query, clients]);

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Conversations"
        title="Threads"
        description="Every conversation across your clients. Pick up where you left off; follow-up questions keep their context."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <Button
            key={s.id}
            type="button"
            variant={status === s.id ? "secondary" : "outline"}
            className="h-8 rounded-md text-xs"
            onClick={() => setStatus(s.id)}
          >
            {s.label}
          </Button>
        ))}
        <div className="relative ml-auto w-full max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title, question, client"
            aria-label="Search threads"
            className="h-9 pl-8"
          />
        </div>
      </div>

      {filtered === null ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed bg-card/40 p-8 text-center text-sm text-muted-foreground">
          No threads yet. Open a client and start a conversation; each one is logged against that
          client&apos;s mandate.
        </div>
      ) : (
        <ul className="space-y-2">
          {filtered.map((t) => {
            const client = clients.find((c) => c.id === t.client_id);
            return (
              <li key={t.id}>
                <Link
                  href={threadHref(t)}
                  className="grid grid-cols-[40px_1fr_auto_auto] items-center gap-3 rounded-lg border bg-card px-4 py-3 hover:bg-accent/30"
                >
                  <span
                    className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground"
                    style={{ background: "hsl(var(--secondary))" }}
                  >
                    <MessageSquare className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{t.title}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      <span className="font-mono">{t.client_id}</span>
                      {client ? <> · {client.displayName}</> : null}
                      {" · "}
                      {t.message_count} question{t.message_count === 1 ? "" : "s"}
                      {" · "}
                      {new Date(t.updated_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.08em]",
                        STATUS_TONE[t.status],
                      )}
                    >
                      {t.status}
                    </span>
                    {t.last_outcome ? <OutcomeBadge result={{ outcome: t.last_outcome }} size="sm" /> : null}
                  </div>
                  <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </PageContainer>
  );
}
