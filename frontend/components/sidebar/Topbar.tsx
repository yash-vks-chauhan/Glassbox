"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { Bell, ChevronRight, Search } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/ThemeToggle";
import { RoleSwitcher } from "@/components/sidebar/RoleSwitcher";

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

export function Topbar() {
  const pathname = usePathname() || "";
  const [timeLabel, setTimeLabel] = useState("--:--");

  useEffect(() => {
    const formatTime = () =>
      new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
        timeZone: "Europe/Zurich",
      }).format(new Date());
    const updateTime = () => setTimeLabel(formatTime());

    updateTime();
    const timer = window.setInterval(updateTime, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const crumbs = crumbsFor(pathname);

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

      <div className="hidden flex-1 max-w-md md:block">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search clients, decisions, IDs…"
            className="h-9 pl-8 text-sm bg-card/60"
          />
          <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border bg-muted px-1.5 font-mono text-[10px] text-muted-foreground sm:inline-block">
            ⌘K
          </kbd>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="hidden text-xs text-muted-foreground tabular md:inline">
          {timeLabel} CET
        </span>
        <RoleSwitcher />
        <Button variant="ghost" size="icon" className="h-9 w-9 rounded-md" aria-label="Notifications">
          <Bell className="h-4 w-4" />
        </Button>
        <ThemeToggle />
        <Avatar className="h-8 w-8 border">
          <AvatarFallback className="bg-secondary text-[11px] font-medium text-secondary-foreground">
            SK
          </AvatarFallback>
        </Avatar>
      </div>
    </header>
  );
}
