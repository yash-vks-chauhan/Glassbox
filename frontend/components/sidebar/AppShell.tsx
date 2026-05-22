"use client";

import type { ReactNode } from "react";

import { SidebarBrand, SidebarNav, SidebarUtility } from "@/components/sidebar/SidebarNav";
import { Topbar } from "@/components/sidebar/Topbar";
import { TooltipProvider } from "@/components/ui/tooltip";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider>
      <div className="relative flex h-screen w-full overflow-hidden">
        <aside className="hidden w-60 shrink-0 flex-col border-r border-sidebar-border/70 bg-sidebar lg:flex">
          <SidebarBrand />
          <SidebarNav />
          <SidebarUtility />
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>
    </TooltipProvider>
  );
}
