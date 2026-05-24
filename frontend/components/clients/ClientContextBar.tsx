"use client";

import Link from "next/link";
import { CalendarDays, ChevronRight, FileText, ShieldAlert } from "lucide-react";

import { formatAUM, type ClientRecord } from "@/lib/clients";
import { cn } from "@/lib/utils";

type Props = {
  client: ClientRecord;
  openFlagCount?: number;
  activeTab?: "overview" | "ask" | "threads" | "history";
};

export function ClientContextBar({ client, openFlagCount = 0, activeTab = "overview" }: Props) {
  const tabs: Array<{ id: NonNullable<Props["activeTab"]>; label: string; href: string }> = [
    { id: "overview", label: "Overview", href: `/app/clients/${client.id}` },
    { id: "ask", label: "Ask", href: `/app/clients/${client.id}/ask` },
    { id: "threads", label: "Threads", href: `/app/clients/${client.id}#threads` },
    { id: "history", label: "History", href: `/app/clients/${client.id}#history` },
  ];

  return (
    <div className="sticky top-0 z-20 border-b border-border/70 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div className="mx-auto flex max-w-[1480px] flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 lg:px-8">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Link href="/app/clients" className="hover:text-foreground">
            Clients
          </Link>
          <ChevronRight className="h-3 w-3 opacity-60" />
          <span className="font-mono text-foreground/80">{client.id}</span>
        </div>

        <div className="flex min-w-0 items-center gap-3">
          <span
            className="flex h-9 w-9 items-center justify-center rounded-md font-mono text-xs tabular"
            style={{
              background: "hsl(var(--secondary))",
              color: "hsl(var(--secondary-foreground))",
            }}
          >
            {client.id}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate font-serif text-base font-semibold tracking-tight">
                {client.displayName}
              </span>
              <span
                className="rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em]"
                style={{
                  borderColor: "hsl(var(--border))",
                  color: "hsl(var(--muted-foreground))",
                }}
              >
                {client.riskProfile}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
              <span>{client.household}</span>
              <span>·</span>
              <span className="tabular">{formatAUM(client.aumEur)} AUM</span>
              <span>·</span>
              <span>Advisor {client.advisor}</span>
            </div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Meta icon={FileText} label={`IPS ${client.ipsVersion}`} />
          <Meta icon={CalendarDays} label={formatDate(client.ipsUpdatedAt)} />
          {openFlagCount > 0 ? (
            <Meta
              icon={ShieldAlert}
              label={`${openFlagCount} open flag${openFlagCount === 1 ? "" : "s"}`}
              tone="flagged"
            />
          ) : null}
        </div>
      </div>

      <div className="mx-auto flex max-w-[1480px] gap-4 border-t border-border/40 px-5 lg:px-8">
        {tabs.map((tab) => {
          const active = tab.id === activeTab;
          return (
            <Link
              key={tab.id}
              href={tab.href}
              className={cn(
                "relative -mb-px border-b-2 border-transparent px-1 py-2 text-[13px] text-muted-foreground transition-colors hover:text-foreground",
                active && "border-foreground text-foreground",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function Meta({
  icon: Icon,
  label,
  tone,
}: {
  icon: typeof FileText;
  label: string;
  tone?: "flagged";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5",
        tone === "flagged" && "state-flagged border-flagged/30",
      )}
    >
      <Icon className="h-3 w-3" />
      <span>{label}</span>
    </span>
  );
}
