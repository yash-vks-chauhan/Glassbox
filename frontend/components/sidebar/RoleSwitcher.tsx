"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, LogOut, Settings, ShieldCheck, Briefcase, Wrench } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth, type AuthUser } from "@/lib/auth-context";

/**
 * Phase F: this used to be a self-service role *switcher* (write-only to
 * localStorage). Now the role is authoritatively the JWT claim — what the
 * sidebar shows is the truth, and the dropdown surfaces tenant + actions
 * like "log out" rather than letting users masquerade.
 */
export type Role = AuthUser["role"];

const ROLE_META: Record<Role, { label: string; icon: typeof Briefcase; description: string }> = {
  advisor: { label: "Advisor", description: "Relationship manager", icon: Briefcase },
  compliance: { label: "Compliance", description: "Supervisor / 2nd line", icon: ShieldCheck },
  admin: { label: "Admin", description: "Org settings + model controls", icon: Wrench },
  owner: { label: "Owner", description: "Workspace owner", icon: Wrench },
};

export function RoleSwitcher({ className }: { className?: string }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const role = user?.role ?? "advisor";
  const meta = ROLE_META[role];
  const Icon = meta.icon;

  async function handleLogout() {
    try {
      await logout();
      toast.success("Signed out");
    } catch {
      toast.error("Sign out failed");
    } finally {
      router.replace("/login");
    }
  }

  return (
    <div className="relative">
      <Button
        variant="outline"
        className={cn(
          "h-9 gap-2 rounded-md border border-sidebar-border/70 bg-card/80 px-2.5 text-sm font-normal",
          className,
        )}
        aria-label="Account menu"
        data-testid="account-menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-foreground">{meta.label}</span>
        <ChevronDown className="ml-auto h-3.5 w-3.5 opacity-60" />
      </Button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-11 z-50 w-72 rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <div className="px-2 py-2">
            <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Signed in as
            </div>
            <div className="mt-1 truncate text-sm font-medium">{user?.email ?? "—"}</div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              {user?.tenant_slug ? `${user.tenant_slug} · ${meta.description}` : meta.description}
            </div>
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              router.push("/app/settings/security");
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-accent"
          >
            <Settings className="h-3.5 w-3.5 text-muted-foreground" />
            Security settings
          </button>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            data-testid="sign-out-action"
            className="flex w-full cursor-pointer items-center gap-2 rounded-sm px-2 py-2 text-left text-sm text-destructive hover:bg-destructive/10"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Legacy hook retained so older imports don't break — it now returns the
 * *real* role from AuthProvider. Code that relied on the old localStorage
 * switcher should migrate to `useAuth()` directly.
 */
export function useRole(): Role {
  const { role } = useAuth();
  return role ?? "advisor";
}
