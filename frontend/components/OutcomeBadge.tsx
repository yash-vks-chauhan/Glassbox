import type { AskResponse } from "@/lib/api";
import { classify, outcomeMeta, type OutcomeKind } from "@/lib/outcomes";
import { cn } from "@/lib/utils";

export { classify as displayOutcome, outcomeMeta };
export type { OutcomeKind };

type OutcomeBadgeProps = {
  outcome?: string;
  result?: AskResponse | { outcome: string; answer?: string | null };
  className?: string;
  size?: "sm" | "md";
};

const STATE_CLASS: Record<OutcomeKind, string> = {
  answered: "state-grounded",
  flagged: "state-flagged",
  refused: "state-refused",
  fallback: "state-fallback",
};

export function OutcomeBadge({ outcome, result, className, size = "md" }: OutcomeBadgeProps) {
  const kind: OutcomeKind = result
    ? classify(result)
    : ((outcome as OutcomeKind | undefined) ?? "refused");
  const meta = outcomeMeta(kind);
  return (
    <span
      data-slot="badge"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border font-medium uppercase tracking-wide",
        STATE_CLASS[kind],
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]",
        className,
      )}
    >
      <span
        className={cn(
          "inline-block rounded-full",
          size === "sm" ? "h-1 w-1" : "h-1.5 w-1.5",
        )}
        style={{ backgroundColor: `hsl(var(--state-${meta.token}))` }}
      />
      {meta.label}
    </span>
  );
}
