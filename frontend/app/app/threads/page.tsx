"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, MessageSquare, Search } from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Input } from "@/components/ui/input";
import { getAuditSummaries, type AuditSummary } from "@/lib/api";
import { useClients } from "@/lib/clients";
import { Skeleton } from "@/components/ui/skeleton";

export default function ThreadsPage() {
  const { clients } = useClients();
  const getClient = (id: string | null | undefined) =>
    id ? clients.find((c) => c.id === id) : undefined;
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    getAuditSummaries(60)
      .then((rows) => {
        if (active) setAudits(rows);
      })
      .catch(() => {
        if (active) setAudits([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!audits) return null;
    const needle = query.trim().toLowerCase();
    if (!needle) return audits;
    return audits.filter((a) => {
      const c = getClient(a.client_id);
      return (
        a.question.toLowerCase().includes(needle) ||
        (a.client_id ?? "").toLowerCase().includes(needle) ||
        (c?.displayName ?? "").toLowerCase().includes(needle)
      );
    });
  }, [audits, query]);

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Conversations"
        title="Threads"
        description="Cross-client conversation list. Pick up where you left off, or follow up on something that needs more context."
      />

      <div className="mb-4 relative max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search question text, client, ID"
          className="h-9 pl-8"
        />
      </div>

      {filtered === null ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed bg-card/40 p-8 text-center text-sm text-muted-foreground">
          No threads yet. Open a client and start a conversation.
        </div>
      ) : (
        <ul className="space-y-2">
          {filtered.map((a) => {
            const c = getClient(a.client_id);
            return (
              <li key={a.id}>
                <Link
                  href={c ? `/app/clients/${c.id}/ask` : `/app/audit/${a.id}`}
                  className="grid grid-cols-[40px_1fr_auto_auto] items-center gap-3 rounded-lg border bg-card px-4 py-3 hover:bg-accent/30"
                >
                  <span
                    className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground"
                    style={{ background: "hsl(var(--secondary))" }}
                  >
                    <MessageSquare className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm">{a.question}</div>
                    <div className="text-xs text-muted-foreground">
                      <span className="font-mono">
                        {c ? c.id : a.client_id ?? "no client"}
                      </span>
                      {c ? <> · {c.displayName}</> : null}
                      {" · "}
                      {new Date(a.created_at).toLocaleString()}
                    </div>
                  </div>
                  <OutcomeBadge result={a} size="sm" />
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
