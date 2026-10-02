"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BookOpen, CalendarDays, FileText } from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { listLibrary, type LibraryDocument } from "@/lib/api";
import { KIND_LABEL, KIND_TONE, formatSize, libraryHref, type DocKind } from "@/lib/library";
import { cn } from "@/lib/utils";

export default function LibraryPage() {
  const [docs, setDocs] = useState<LibraryDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | DocKind>("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    listLibrary()
      .then(setDocs)
      .catch((err) => {
        setDocs([]);
        setError(err instanceof Error ? err.message : "Could not load the library");
      });
  }, []);

  const filtered = useMemo(() => {
    if (!docs) return null;
    const needle = query.trim().toLowerCase();
    return docs.filter((d) => {
      if (filter !== "all" && d.source_type !== filter) return false;
      if (!needle) return true;
      return d.title.toLowerCase().includes(needle) || d.source_id.toLowerCase().includes(needle);
    });
  }, [docs, filter, query]);

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Approved corpus"
        title="Library"
        description="The only documents GlassBox is allowed to ground answers on — exactly what the retrieval index can cite for your workspace."
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {(["all", "ips", "portfolio", "factsheet", "regulation"] as const).map((id) => (
          <Button
            key={id}
            type="button"
            variant={filter === id ? "secondary" : "outline"}
            className="h-8 rounded-md text-xs"
            onClick={() => setFilter(id)}
          >
            {id === "all" ? "All" : KIND_LABEL[id]}
          </Button>
        ))}
        <div className="ml-auto w-full max-w-xs">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title or source ID"
            aria-label="Search documents"
            className="h-8 text-xs"
          />
        </div>
      </div>

      {error ? (
        <div className="mb-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[40px_minmax(0,2fr)_110px_130px_120px_90px_40px] gap-px border-b bg-border text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <div className="bg-card px-3 py-2.5" />
          <div className="bg-card px-3 py-2.5">Document</div>
          <div className="bg-card px-3 py-2.5">Kind</div>
          <div className="bg-card px-3 py-2.5">Version</div>
          <div className="bg-card px-3 py-2.5">Updated</div>
          <div className="bg-card px-3 py-2.5 text-right">Indexed</div>
          <div className="bg-card px-3 py-2.5" />
        </div>
        {filtered === null ? (
          <div className="space-y-1.5 p-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 rounded-md" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            No documents match.
          </div>
        ) : (
          filtered.map((doc) => (
            <Link
              key={doc.source_id}
              href={libraryHref(doc.source_id)}
              className="grid grid-cols-[40px_minmax(0,2fr)_110px_130px_120px_90px_40px] items-center border-b border-border/40 text-sm last:border-0 hover:bg-accent/30"
            >
              <div className="flex items-center justify-center px-3 py-2.5">
                <FileText className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="min-w-0 px-3 py-2.5">
                <div className="line-clamp-1">{doc.title}</div>
                <div className="font-mono text-[11px] text-muted-foreground">
                  {doc.source_id} · {doc.shared ? "all workspaces" : "this workspace only"} ·{" "}
                  {formatSize(doc.size_bytes)}
                </div>
              </div>
              <div className="px-3 py-2.5">
                <span className={cn("rounded-sm border px-1.5 py-0.5 text-[11px]", KIND_TONE[doc.source_type])}>
                  {KIND_LABEL[doc.source_type]}
                </span>
              </div>
              <div className="px-3 py-2.5 font-mono text-xs">{doc.version ?? "—"}</div>
              <div className="px-3 py-2.5">
                {doc.updated_on ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                    <CalendarDays className="h-3 w-3" />
                    {new Date(`${doc.updated_on}T00:00:00`).toLocaleDateString()}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </div>
              <div
                className={cn(
                  "px-3 py-2.5 text-right text-xs tabular",
                  doc.indexed_passages === 0 ? "text-destructive" : "text-muted-foreground",
                )}
                title={doc.indexed_passages === 0 ? "Not in the retrieval index — run ingestion" : undefined}
              >
                {doc.indexed_passages} passage{doc.indexed_passages === 1 ? "" : "s"}
              </div>
              <div className="flex items-center justify-end px-3 py-2.5 text-muted-foreground">
                <ArrowUpRight className="h-3.5 w-3.5" />
              </div>
            </Link>
          ))
        )}
      </div>

      <div className="mt-6 rounded-lg border border-dashed bg-card/40 p-4 text-xs leading-6 text-muted-foreground">
        <BookOpen className="mr-1.5 inline h-3.5 w-3.5" />
        Documents are managed as files under <code className="font-mono">backend/corpus/</code>; add or
        edit one, then re-run ingestion (<code className="font-mono">python -m corpus.ingest</code>) to
        update the index. Past answers stay replayable either way: every decision stores the exact
        passages it retrieved.
      </div>
    </PageContainer>
  );
}
