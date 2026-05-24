"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { AppShell } from "@/components/sidebar/AppShell";
import { useAuth } from "@/lib/auth-context";

/**
 * Route guard for every /app/* page.
 *
 * The auth bootstrap runs once in <AuthProvider>; until it settles we render
 * a thin loading shell rather than redirecting eagerly (otherwise a hard
 * reload on /app/audit would always blink past /login on its way back).
 *
 * Once `status === "unauthenticated"`, we redirect to /login carrying the
 * original path as `?next=` so the post-login flow can land the user back
 * where they were.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname() || "/app/home";

  useEffect(() => {
    if (status === "unauthenticated") {
      const next = encodeURIComponent(pathname);
      router.replace(`/login?next=${next}`);
    }
  }, [status, router, pathname]);

  if (status === "loading" || status === "unauthenticated") {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {status === "loading" ? "Restoring your session…" : "Redirecting to sign in…"}
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
