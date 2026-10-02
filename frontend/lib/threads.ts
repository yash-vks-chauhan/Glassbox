import type { ThreadSummary } from "@/lib/api";

/** Where a thread opens: its client's conversation view. */
export function threadHref(thread: Pick<ThreadSummary, "id" | "client_id">) {
  return `/app/clients/${encodeURIComponent(thread.client_id)}/ask?thread=${encodeURIComponent(thread.id)}`;
}
