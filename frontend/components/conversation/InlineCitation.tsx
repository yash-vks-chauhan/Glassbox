"use client";

import { useState } from "react";
import { FileText } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type CitationRef = {
  index: number;
  sourceId: string;
  sourceType: string;
  snippet: string;
};

type Props = {
  citation: CitationRef;
  onClick?: (sourceId: string) => void;
};

export function InlineCitation({ citation, onClick }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            onMouseEnter={() => setOpen(true)}
            onMouseLeave={() => setOpen(false)}
            onClick={() => onClick?.(citation.sourceId)}
            className={cn(
              "mx-0.5 inline-flex h-[14px] min-w-[14px] items-center justify-center rounded-[3px] border bg-card px-[3px] align-super text-[10px] font-medium leading-none transition-colors",
              "text-primary hover:bg-primary hover:text-primary-foreground",
            )}
            aria-label={`Citation ${citation.index} – ${citation.sourceId}`}
          />
        }
      >
        {citation.index}
      </PopoverTrigger>
      <PopoverContent className="w-[320px] rounded-md border bg-popover p-3 text-sm shadow-lg">
        <div className="mb-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <FileText className="h-3 w-3" />
          <span className="font-mono uppercase tracking-[0.12em]">{citation.sourceType}</span>
          <span className="font-mono text-foreground">{citation.sourceId}</span>
        </div>
        <p className="text-[13px] leading-6 text-foreground/90">{citation.snippet}</p>
      </PopoverContent>
    </Popover>
  );
}

const TOKEN_RE = /\[([A-Z][A-Z0-9_-]+|\d+)\]/g;

export function renderTextWithCitations(
  text: string,
  citations: CitationRef[],
  onCitation?: (sourceId: string) => void,
) {
  if (!text) return null;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TOKEN_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[1];
    const n = Number(token);
    const citation = Number.isFinite(n)
      ? citations.find((c) => c.index === n)
      : citations.find((c) => c.sourceId === token);
    if (citation) {
      nodes.push(
        <InlineCitation
          key={`${match.index}-${token}`}
          citation={citation}
          onClick={onCitation}
        />,
      );
    } else {
      nodes.push(match[0]);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}
