"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { Bell, ChevronRight, Search } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/ThemeToggle";
import { RoleSwitcher } from "@/components/sidebar/RoleSwitcher";
import { listEscalations } from "@/lib/api";
import { hasAtLeastRole, useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const TITLES: Array<[RegExp, string]> = [
  [/^\/app\/home$/, "Home"],
  [/^\/app\/clients$/, "Clients"],
  [/^\/app\/clients\/[^/]+$/, "Client"],
  [/^\/app\/clients\/[^/]+\/ask$/, "Conversation"],
  [/^\/app\/threads$/, "Threads"],
  [/^\/app\/threads\/[^/]+$/, "Thread"],
  [/^\/app\/review$/, "Review queue"],
  [/^\/app\/review\/[^/]+$/, "Reviewing decision"],
  [/^\/app\/audit$/, "Audit log"],
  [/^\/app\/audit\/[^/]+$/, "Decision replay"],
  [/^\/app\/insights$/, "Insights"],
  [/^\/app\/library$/, "Library"],
  [/^\/app\/admin$/, "Admin"],
];

function titleFor(pathname: string): string {
  for (const [re, label] of TITLES) if (re.test(pathname)) return label;
  return "GlassBox";
}

function crumbsFor(pathname: string) {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== "app") return [];
  const crumbs: Array<{ label: string; href?: string }> = [{ label: "GlassBox", href: "/app/home" }];
  let acc = "/app";
  for (let i = 1; i < segments.length; i += 1) {
    acc = `${acc}/${segments[i]}`;
    const label = segments[i].length > 12 ? `${segments[i].slice(0, 8)}…` : segments[i];
    crumbs.push({ label, href: i === segments.length - 1 ? undefined : acc });
  }
  return crumbs;
}

function initials(name: string | null | undefined, email: string | undefined) {
  const source = name?.trim() || email?.split("@")[0] || "";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase() || "?";
}

/** Where the global search sends a query: a client code opens that client,
 * anything else searches the full audit log. */
function searchTarget(query: string) {
  const trimmed = query.trim();
  if (/^C\d{3,6}$/i.test(trimmed)) return `/app/clients/${trimmed.toUpperCase()}`;
  return `/app/audit?range=all&q=${encodeURIComponent(trimmed)}`;
}

export function Topbar() {
  const pathname = usePathname() || "";
  const router = useRouter();
  const { user, role } = useAuth();
  const isReviewer = hasAtLeastRole(role, "compliance");
  const [timeLabel, setTimeLabel] = useState("--:--");
  const [query, setQuery] = useState("");
  const [openEscalations, setOpenEscalations] = useState<number | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  // Local time in the viewer's own time zone.
  useEffect(() => {
    const format = new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
    const updateTime = () => setTimeLabel(format.format(new Date()));
    updateTime();
    const timer = window.setInterval(updateTime, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  // ⌘K / Ctrl+K focuses the search box.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Active escalations visible to the user: the review queue for
  // reviewers, the ones they raised for advisors.
  useEffect(() => {
    if (!user) return;
    let active = true;
    const load = () =>
      listEscalations(200)
        .then(
          (rows) =>
            active &&
            setOpenEscalations(rows.filter((r) => r.status === "open" || r.status === "in_review").length),
        )
        .catch(() => active && setOpenEscalations(null));
    void load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [user]);

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    router.push(searchTarget(query));
    setQuery("");
    searchRef.current?.blur();
  }

  const crumbs = crumbsFor(pathname);
  const bellLabel =
    openEscalations === null
      ? "Escalations"
      : `${openEscalations} open escalation${openEscalations === 1 ? "" : "s"}`;

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border/70 bg-background/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60 lg:px-6">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <div className="hidden min-w-0 items-center gap-1.5 text-xs text-muted-foreground lg:flex">
          {crumbs.map((crumb, index) => (
            <span key={`${crumb.label}-${index}`} className="flex items-center gap-1.5">
              {index > 0 ? <ChevronRight className="h-3 w-3 opacity-60" /> : null}
              {crumb.href ? (
                <Link href={crumb.href} className="hover:text-foreground">
                  {crumb.label}
                </Link>
              ) : (
                <span className="font-medium text-foreground">{crumb.label}</span>
              )}
            </span>
          ))}
        </div>
        <div className="lg:hidden">
          <span className="font-serif text-base font-semibold tracking-tight">
            {titleFor(pathname)}
          </span>
        </div>
      </div>

      <form onSubmit={onSearch} role="search" className="hidden flex-1 max-w-md md:block">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search decisions, or jump to a client (C001)…"
            aria-label="Search decisions or jump to a client"
            className="h-9 pl-8 text-sm bg-card/60"
          />
          <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border bg-muted px-1.5 font-mono text-[10px] text-muted-foreground sm:inline-block">
            ⌘K
          </kbd>
        </div>
      </form>

      <div className="flex items-center gap-1.5">
        <span className="hidden text-xs text-muted-foreground tabular md:inline">{timeLabel}</span>
        <RoleSwitcher />
        <Link
          href={isReviewer ? "/app/review" : "/app/home"}
          aria-label={bellLabel}
          title={bellLabel}
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-accent"
        >
          <Bell className="h-4 w-4" />
          {openEscalations ? (
            <span
              className={cn(
                "absolute right-1 top-1 min-w-[16px] rounded-full px-1 text-center text-[10px] font-medium leading-4",
                "bg-[hsl(var(--state-flagged))] text-white",
              )}
            >
              {openEscalations > 99 ? "99+" : openEscalations}
            </span>
          ) : null}
        </Link>
        <ThemeToggle />
        <Avatar className="h-8 w-8 border" title={user?.email}>
          <AvatarFallback className="bg-secondary text-[11px] font-medium text-secondary-foreground">
            {initials(user?.display_name, user?.email)}
          </AvatarFallback>
        </Avatar>
      </div>
    </header>
  );
}
