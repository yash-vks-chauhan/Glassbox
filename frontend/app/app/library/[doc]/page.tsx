"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ChevronRight, FileText } from "lucide-react";

import { PageContainer } from "@/components/PageContainer";
import { Skeleton } from "@/components/ui/skeleton";
import { getLibraryDocument, type LibraryDocumentDetail } from "@/lib/api";
import { KIND_LABEL, KIND_TONE, formatSize } from "@/lib/library";
import { cn } from "@/lib/utils";

export default function LibraryDocumentPage({
  params,
}: {
  params: Promise<{ doc: string }>;
}) {
  const { doc: sourceId } = use(params);
  const [doc, setDoc] = useState<LibraryDocumentDetail | null | "loading">("loading");

  useEffect(() => {
    let active = true;
    getLibraryDocument(decodeURIComponent(sourceId))
      .then((row) => active && setDoc(row))
      .catch(() => active && setDoc(null));
    return () => {
      active = false;
    };
  }, [sourceId]);

  if (doc === "loading") {
    return (
      <PageContainer>
        <Skeleton className="mb-4 h-8 w-64 rounded-md" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </PageContainer>
    );
  }
  if (doc === null) {
    return (
      <PageContainer>
        <Link
          href="/app/library"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to library
        </Link>
        <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          Document not found in your workspace&apos;s approved set.
        </div>
      </PageContainer>
    );
  }

  const metadata = Object.entries(doc.metadata);
  return (
    <PageContainer>
      <div className="mb-4 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link href="/app/library" className="hover:text-foreground">
          Library
        </Link>
        <ChevronRight className="h-3 w-3 opacity-60" />
        <span className="font-mono text-foreground/80">{doc.source_id}</span>
      </div>

      <div className="mb-5 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-sm border px-1.5 py-0.5 text-[11px]", KIND_TONE[doc.source_type])}>
            {KIND_LABEL[doc.source_type]}
          </span>
          <span className="text-xs text-muted-foreground">
            {doc.shared ? "Shared with all workspaces" : "This workspace only"}
          </span>
        </div>
        <h1 className="font-serif text-2xl font-semibold tracking-tight">{doc.title}</h1>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>Version {doc.version ?? "—"}</span>
          <span>·</span>
          <span>Updated {doc.updated_on ?? "—"}</span>
          <span>·</span>
          <span className="font-mono">{doc.file}</span>
          <span>·</span>
          <span>{formatSize(doc.size_bytes)}</span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <article className="rounded-xl border bg-card p-5 lg:p-6">
          <MarkdownBody text={doc.body} />
        </article>

        <aside className="space-y-4 lg:sticky lg:top-[5.5rem] lg:self-start">
          <section className="rounded-xl border bg-card">
            <header className="border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Retrieval
            </header>
            <dl className="divide-y divide-border/60 text-sm">
              <Row label="Source ID">
                <code className="font-mono text-[11px]">{doc.source_id}</code>
              </Row>
              <Row label="Indexed passages">
                <span className={cn("tabular", doc.indexed_passages === 0 && "text-destructive")}>
                  {doc.indexed_passages === 0 ? "0 — run ingestion" : doc.indexed_passages}
                </span>
              </Row>
              <Row label="Cited in decisions">
                <span className="tabular">{doc.cited_in_decisions}</span>
              </Row>
            </dl>
          </section>

          {metadata.length ? (
            <section className="rounded-xl border bg-card">
              <header className="border-b px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Document fields
              </header>
              <dl className="divide-y divide-border/60 text-sm">
                {metadata.map(([key, value]) => (
                  <Row key={key} label={key.replaceAll("_", " ")}>
                    {Array.isArray(value) ? value.join(", ") || "—" : String(value)}
                  </Row>
                ))}
              </dl>
            </section>
          ) : null}
        </aside>
      </div>
    </PageContainer>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-2">
      <dt className="text-muted-foreground first-letter:uppercase">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

/** Renders the corpus' markdown subset (headings, paragraphs, bullet lists)
 * as React elements; no raw HTML is ever injected. */
function MarkdownBody({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  return (
    <div className="space-y-4 text-[14px] leading-7">
      {blocks.map((block, index) => {
        const heading = /^(#{1,3})\s+(.+)$/.exec(block);
        if (heading) {
          const level = heading[1].length;
          return (
            <h2
              key={index}
              className={cn(
                "font-serif font-semibold tracking-tight",
                level === 1 ? "text-lg" : "text-base",
              )}
            >
              {heading[2]}
            </h2>
          );
        }
        const lines = block.split("\n");
        if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
          return (
            <ul key={index} className="list-disc space-y-1 pl-5">
              {lines.map((line, i) => (
                <li key={i}>{line.replace(/^\s*[-*]\s+/, "")}</li>
              ))}
            </ul>
          );
        }
        return (
          <div key={index} className="space-y-1.5">
            {lines.map((line, i) => (
              <p key={i} className="flex gap-2">
                <FileText className="mt-1.5 h-3 w-3 shrink-0 text-muted-foreground/50" aria-hidden />
                <span>{line}</span>
              </p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
