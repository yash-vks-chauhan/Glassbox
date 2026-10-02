import type { LibraryDocument } from "@/lib/api";

export type DocKind = LibraryDocument["source_type"];

export const KIND_LABEL: Record<DocKind, string> = {
  ips: "IPS",
  portfolio: "Portfolio",
  factsheet: "Factsheet",
  regulation: "Regulation",
};

/** `state-*` token class used to tint each kind's badge. */
export const KIND_TONE: Record<DocKind, string> = {
  ips: "state-grounded",
  portfolio: "state-grounded",
  factsheet: "state-fallback",
  regulation: "state-refused",
};

export function formatSize(bytes: number) {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

export function libraryHref(sourceId: string) {
  return `/app/library/${encodeURIComponent(sourceId)}`;
}
