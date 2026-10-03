"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, ScanSearch, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, demoLogin, getDemoInfo, type DemoRole } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const ROLES: { role: DemoRole; label: string; detail: string; landing: string; icon: typeof ScanSearch }[] = [
  {
    role: "advisor",
    label: "Try as an advisor",
    detail: "Ask about a client and see the cited answer",
    landing: "/app/clients/C001/ask",
    icon: ScanSearch,
  },
  {
    role: "compliance",
    label: "Try as compliance",
    detail: "Review escalations, replay decisions, export",
    landing: "/app/review",
    icon: ShieldCheck,
  },
];

/** One-click demo sign-in, shown only when the server offers it. */
export function DemoAccess() {
  const router = useRouter();
  const { refreshUser } = useAuth();
  const [enabled, setEnabled] = useState(false);
  const [pending, setPending] = useState<DemoRole | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getDemoInfo()
      .then((info) => {
        if (active) setEnabled(info.enabled);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  if (!enabled) return null;

  async function start(role: DemoRole, landing: string) {
    setPending(role);
    setError(null);
    try {
      await demoLogin(role);
      await refreshUser();
      router.replace(landing);
    } catch (err) {
      setPending(null);
      setError(
        err instanceof ApiError && err.status === 429
          ? "Too many sign-ins from this network. Wait a minute and try again."
          : "The demo isn't available right now.",
      );
    }
  }

  return (
    <section aria-label="Live demo" className="mt-6 rounded-lg border bg-muted/30 p-4">
      <div className="text-sm font-medium">Just looking? Explore the live demo</div>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        No account needed. The demo workspace is shared, so other visitors can see what you
        ask there.
      </p>
      <div className="mt-3 grid gap-2">
        {ROLES.map(({ role, label, detail, landing, icon: Icon }) => (
          <Button
            key={role}
            type="button"
            variant="outline"
            disabled={pending !== null}
            onClick={() => start(role, landing)}
            className="h-auto justify-start gap-3 rounded-md px-3 py-2.5 text-left"
          >
            {pending === role ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
            ) : (
              <Icon className="h-4 w-4 shrink-0" />
            )}
            <span className="flex-1">
              <span className="block text-sm font-medium">{label}</span>
              <span className="block text-xs font-normal text-muted-foreground">{detail}</span>
            </span>
            <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </Button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </section>
  );
}
