"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ArchiveRestore,
  BookOpen,
  ClipboardList,
  Cog,
  Home,
  LayoutGrid,
  LineChart,
  ScanSearch,
  Users,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { hasAtLeastRole, useAuth, type AuthUser } from "@/lib/auth-context";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  group: "work" | "oversight" | "system";
  matches?: (pathname: string) => boolean;
  /** Minimum role required to see this item. Default: visible to everyone. */
  requires?: AuthUser["role"];
};

const NAV: NavItem[] = [
  { href: "/app/home", label: "Home", icon: Home, group: "work" },
  { href: "/app/clients", label: "Clients", icon: Users, group: "work",
    matches: (p) => p.startsWith("/app/clients") },
  { href: "/app/threads", label: "Threads", icon: LayoutGrid, group: "work",
    matches: (p) => p.startsWith("/app/threads") },
  { href: "/app/review", label: "Review queue", icon: ClipboardList, group: "oversight",
    matches: (p) => p.startsWith("/app/review"), requires: "compliance" },
  { href: "/app/audit", label: "Audit log", icon: ArchiveRestore, group: "oversight",
    matches: (p) => p.startsWith("/app/audit") },
  { href: "/app/insights", label: "Insights", icon: LineChart, group: "oversight",
    requires: "compliance" },
  { href: "/app/library", label: "Library", icon: BookOpen, group: "system" },
  // Phase F — hide /app/admin for non-admin/non-owner. The page itself also
  // guards on `hasAtLeastRole(role, "admin")`, this just keeps the sidebar tidy.
  { href: "/app/admin", label: "Admin", icon: Cog, group: "system", requires: "admin" },
];

const GROUP_LABELS: Record<NavItem["group"], string> = {
  work: "Advisory",
  oversight: "Oversight",
  system: "System",
};

export function SidebarNav() {
  const pathname = usePathname() || "";
  const { role } = useAuth();
  // Filter once per render — the role rarely changes and the list is small.
  const visible = NAV.filter((item) => !item.requires || hasAtLeastRole(role, item.requires));
  const grouped: Record<NavItem["group"], NavItem[]> = { work: [], oversight: [], system: [] };
  for (const item of visible) grouped[item.group].push(item);

  return (
    <nav className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-2">
      {(Object.keys(grouped) as NavItem["group"][]).map((group) => (
        <div key={group} className="space-y-1">
          <div className="px-2 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/80">
            {GROUP_LABELS[group]}
          </div>
          <ul className="space-y-0.5">
            {grouped[group].map((item) => {
              const isActive = item.matches ? item.matches(pathname) : pathname === item.href;
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground/80 transition-colors",
                      "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                      isActive &&
                        "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0 opacity-80 group-hover:opacity-100" />
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      <div className="mt-auto px-2 pb-3">
        <div className="flex items-center gap-2 rounded-md border border-sidebar-border/60 bg-sidebar/80 px-2.5 py-2 text-xs text-muted-foreground">
          <span className="relative flex h-2 w-2">
            <span
              className="absolute inset-0 animate-ping rounded-full opacity-60"
              style={{ backgroundColor: "hsl(var(--state-grounded))" }}
            />
            <span
              className="relative inline-flex h-2 w-2 rounded-full"
              style={{ backgroundColor: "hsl(var(--state-grounded))" }}
            />
          </span>
          <span className="truncate">All controls operational</span>
        </div>
      </div>
    </nav>
  );
}

export function SidebarBrand() {
  const { user } = useAuth();
  const tenant = user?.tenant_slug ?? "Audit-grade AI";
  return (
    <div className="px-3 pt-4">
      <Link href="/app/home" className="flex items-center gap-2.5">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-md text-primary-foreground"
          style={{ background: "hsl(var(--primary))" }}
        >
          <ScanSearch className="h-3.5 w-3.5" />
        </span>
        <div className="flex flex-col">
          <span className="font-serif text-[15px] font-semibold tracking-tight leading-none">
            GlassBox
          </span>
          <span className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            {tenant}
          </span>
        </div>
      </Link>
      {user ? (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-sidebar-border/60 bg-sidebar/80 px-2 py-1.5 text-[11px]">
          <span className="truncate text-muted-foreground" title={user.email}>
            {user.email}
          </span>
          <span
            className="ml-auto rounded-sm border px-1.5 py-px text-[10px] uppercase tracking-[0.12em] text-foreground"
            data-testid="sidebar-role-badge"
            title={`Role: ${user.role}`}
          >
            {user.role}
          </span>
        </div>
      ) : null}
    </div>
  );
}

export function SidebarUtility() {
  return (
    <div className="px-3 pb-3 pt-2">
      <div className="flex items-center gap-2 rounded-md border bg-card/80 px-2.5 py-2">
        <Activity className="h-3.5 w-3.5 text-muted-foreground" />
        <div className="flex-1 text-xs leading-tight">
          <div className="font-medium tabular">3 / 6</div>
          <div className="text-[10px] text-muted-foreground">SLAs in range</div>
        </div>
      </div>
    </div>
  );
}
