"use client";

import { useMemo, useState } from "react";
import { BookOpen, CalendarDays, FileText, Upload } from "lucide-react";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useClients } from "@/lib/clients-hooks";
import { cn } from "@/lib/utils";

type DocKind = "ips" | "factsheet" | "regulation";

type Doc = {
  id: string;
  title: string;
  kind: DocKind;
  version: string;
  updatedAt: string;
  applicableTo: string[];
  size: string;
};

const STATIC_DOCS: Doc[] = [
  {
    id: "F100",
    title: "Factsheet — Global Tech Equity",
    kind: "factsheet",
    version: "Oct 2024",
    updatedAt: "2024-10-31",
    applicableTo: ["all"],
    size: "84 KB",
  },
  {
    id: "F200",
    title: "Factsheet — Liquid Core Bond",
    kind: "factsheet",
    version: "Oct 2024",
    updatedAt: "2024-10-31",
    applicableTo: ["all"],
    size: "72 KB",
  },
  {
    id: "F300",
    title: "Factsheet — Sustainability Equity",
    kind: "factsheet",
    version: "Oct 2024",
    updatedAt: "2024-10-31",
    applicableTo: ["all"],
    size: "78 KB",
  },
  {
    id: "REG_SUITABILITY",
    title: "MiFID II Suitability — extract",
    kind: "regulation",
    version: "Sep 2024",
    updatedAt: "2024-09-01",
    applicableTo: ["all"],
    size: "9 KB",
  },
];

const KIND_LABEL: Record<DocKind, string> = {
  ips: "IPS",
  factsheet: "Factsheet",
  regulation: "Regulation",
};

const KIND_TONE: Record<DocKind, string> = {
  ips: "state-grounded",
  factsheet: "state-fallback",
  regulation: "state-refused",
};

export default function LibraryPage() {
  const { clients } = useClients();
  const [filter, setFilter] = useState<"all" | DocKind>("all");
  const [query, setQuery] = useState("");

  const docs = useMemo<Doc[]>(
    () => [
      ...clients.map<Doc>((c) => ({
        id: `IPS_${c.id}`,
        title: `Investment Policy Statement — ${c.displayName}`,
        kind: "ips",
        version: c.ipsVersion,
        updatedAt: c.ipsUpdatedAt,
        applicableTo: [c.id],
        size: "12 KB",
      })),
      ...STATIC_DOCS,
    ],
    [clients],
  );

  const filtered = docs.filter((d) => {
    if (filter !== "all" && d.kind !== filter) return false;
    if (query) {
      const n = query.toLowerCase();
      return d.title.toLowerCase().includes(n) || d.id.toLowerCase().includes(n);
    }
    return true;
  });

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Approved corpus"
        title="Library"
        description="The only documents GlassBox is allowed to ground answers on. Versioned, applicable-to scoped, replayable."
        actions={
          <Button className="h-9 gap-1.5 rounded-md">
            <Upload className="h-3.5 w-3.5" />
            Upload document
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {(["all", "ips", "factsheet", "regulation"] as const).map((id) => (
          <Button
            key={id}
            type="button"
            variant={filter === id ? "secondary" : "outline"}
            className="h-8 rounded-md text-xs capitalize"
            onClick={() => setFilter(id)}
          >
            {id === "all" ? "All" : KIND_LABEL[id]}
          </Button>
        ))}
        <div className="ml-auto w-full max-w-xs">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search documents"
            className="h-8 text-xs"
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <div className="grid grid-cols-[40px_minmax(0,2fr)_120px_120px_120px_80px] gap-px border-b bg-border text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <div className="bg-card px-3 py-2.5" />
          <div className="bg-card px-3 py-2.5">Document</div>
          <div className="bg-card px-3 py-2.5">Kind</div>
          <div className="bg-card px-3 py-2.5">Version</div>
          <div className="bg-card px-3 py-2.5">Updated</div>
          <div className="bg-card px-3 py-2.5 text-right">Size</div>
        </div>
        {filtered.map((doc) => (
          <div
            key={doc.id}
            className="grid grid-cols-[40px_minmax(0,2fr)_120px_120px_120px_80px] items-center border-b border-border/40 text-sm last:border-0 hover:bg-accent/30"
          >
            <div className="flex items-center justify-center px-3 py-2.5">
              <FileText className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="px-3 py-2.5">
              <div className="line-clamp-1">{doc.title}</div>
              <div className="font-mono text-[11px] text-muted-foreground">
                {doc.id} ·{" "}
                {doc.applicableTo[0] === "all"
                  ? "All clients"
                  : `Applies to ${doc.applicableTo.join(", ")}`}
              </div>
            </div>
            <div className="px-3 py-2.5">
              <span className={cn("rounded-sm border px-1.5 py-0.5 text-[11px]", KIND_TONE[doc.kind])}>
                {KIND_LABEL[doc.kind]}
              </span>
            </div>
            <div className="px-3 py-2.5 font-mono text-xs">{doc.version}</div>
            <div className="px-3 py-2.5">
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <CalendarDays className="h-3 w-3" />
                {new Date(doc.updatedAt).toLocaleDateString()}
              </span>
            </div>
            <div className="px-3 py-2.5 text-right text-xs tabular text-muted-foreground">
              {doc.size}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 rounded-lg border border-dashed bg-card/40 p-4 text-xs text-muted-foreground">
        <BookOpen className="mr-1.5 inline h-3.5 w-3.5" />
        Documents added here become available to the retrieval layer immediately. Past answers
        issued against earlier versions remain replayable against the version that was active at
        decision time.
      </div>
    </PageContainer>
  );
}
