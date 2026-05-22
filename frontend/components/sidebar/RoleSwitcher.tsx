"use client";

import { useEffect, useState } from "react";
import { Briefcase, ChevronDown, ShieldCheck, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type Role = "advisor" | "compliance" | "admin";

const ROLES: Array<{
  id: Role;
  label: string;
  description: string;
  icon: typeof Briefcase;
}> = [
  { id: "advisor", label: "Advisor", description: "Relationship manager view", icon: Briefcase },
  { id: "compliance", label: "Compliance", description: "Supervisor / 2nd-line view", icon: ShieldCheck },
  { id: "admin", label: "Admin", description: "Org settings + model controls", icon: Wrench },
];

const STORAGE_KEY = "glassbox.role";

function readRole(): Role {
  if (typeof window === "undefined") return "advisor";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === "compliance" || raw === "admin" || raw === "advisor") return raw;
  return "advisor";
}

export function RoleSwitcher({ className }: { className?: string }) {
  const [role, setRole] = useState<Role>("advisor");

  useEffect(() => {
    setRole(readRole());
  }, []);

  const active = ROLES.find((r) => r.id === role) ?? ROLES[0];
  const Icon = active.icon;

  function pick(next: Role) {
    setRole(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next);
      // Soft refresh so role-gated server pages can pick up the change.
      window.dispatchEvent(new Event("glassbox-role-change"));
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="outline"
            className={cn(
              "h-9 gap-2 rounded-md border border-sidebar-border/70 bg-card/80 px-2.5 text-sm font-normal",
              className,
            )}
            aria-label="Switch role"
          />
        }
      >
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-foreground">{active.label}</span>
        <ChevronDown className="ml-auto h-3.5 w-3.5 opacity-60" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60 rounded-md border bg-popover p-1 shadow-md">
        <DropdownMenuLabel className="px-2 py-1.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          View as
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {ROLES.map((r) => {
          const RoleIcon = r.icon;
          return (
            <DropdownMenuItem
              key={r.id}
              onClick={() => pick(r.id)}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-sm px-2 py-2 text-sm hover:bg-accent",
                r.id === role && "bg-accent/60",
              )}
            >
              <RoleIcon className="mt-0.5 h-4 w-4 text-muted-foreground" />
              <div className="flex flex-col">
                <span className="font-medium">{r.label}</span>
                <span className="text-xs text-muted-foreground">{r.description}</span>
              </div>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function useRole(): Role {
  const [role, setRole] = useState<Role>("advisor");
  useEffect(() => {
    setRole(readRole());
    const handler = () => setRole(readRole());
    window.addEventListener("glassbox-role-change", handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("glassbox-role-change", handler);
      window.removeEventListener("storage", handler);
    };
  }, []);
  return role;
}
