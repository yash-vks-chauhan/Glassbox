"use client";

import type { ReactNode } from "react";

import { SidebarBrand, SidebarNav, SidebarUtility } from "@/components/sidebar/SidebarNav";
import { Topbar } from "@/components/sidebar/Topbar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuth } from "@/lib/auth-context";

export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return (
    <TooltipProvider>
      <div className="relative flex h-screen w-full overflow-hidden">
        <aside className="hidden w-60 shrink-0 flex-col border-r border-sidebar-border/70 bg-sidebar lg:flex">
          <SidebarBrand />
          <SidebarNav />
          <SidebarUtility />
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {user?.is_demo ? (
            <div
              data-testid="demo-banner"
              className="border-b bg-accent/50 px-5 py-1.5 text-center text-xs text-accent-foreground"
            >
              Demo workspace, shared with other visitors: what you ask here is visible to them.
            </div>
          ) : null}
          <Topbar />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>
    </TooltipProvider>
  );
}
