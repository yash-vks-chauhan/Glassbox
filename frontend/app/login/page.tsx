"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowRight, Loader2, ScanSearch, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, MfaRequiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

function safeRedirect(target: string | null): string {
  // Only honor in-app paths under /app to stop ?next= open-redirects.
  if (!target) return "/app/home";
  if (!target.startsWith("/app/") && target !== "/app") return "/app/home";
  return target;
}

function LoginInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [loading, setLoading] = useState(false);
  // Local error state lives alongside the toast so screen-readers see it inline.
  const [error, setError] = useState<string | null>(null);

  const next = safeRedirect(searchParams?.get("next") ?? null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") || "").trim();
    const password = String(form.get("password") || "");
    const tenant_slug = String(form.get("tenant_slug") || "demo").trim() || "demo";
    try {
      await login({ email, password, tenant_slug });
      toast.success("Signed in");
      router.replace(next);
    } catch (err) {
      handleLoginError(err, { email, password, tenant_slug });
    } finally {
      setLoading(false);
    }
  }

  function handleLoginError(
    err: unknown,
    creds: { email: string; password: string; tenant_slug: string },
  ) {
    if (err instanceof MfaRequiredError) {
      if (err.reason === "mfa_enrollment_required") {
        setError(
          "Your role requires MFA. Please contact your administrator to start enrollment.",
        );
        return;
      }
      if (!err.mfaToken) {
        setError("MFA challenge could not be started. Please try again.");
        return;
      }
      sessionStorage.setItem(
        "glassbox.pending_mfa",
        JSON.stringify({
          email: creds.email,
          tenant_slug: creds.tenant_slug,
          mfa_token: err.mfaToken,
          next,
          created_at: Date.now(),
        }),
      );
      setError(null);
      router.push(`/login/mfa?next=${encodeURIComponent(next)}`);
      return;
    }
    if (err instanceof ApiError) {
      if (err.status === 423) {
        setError("Account locked after too many failed attempts. Try again later.");
        return;
      }
      if (err.status === 401) {
        setError("Invalid email, password, or MFA code.");
        return;
      }
      setError(typeof err.detail === "string" ? err.detail : err.message);
      return;
    }
    setError(err instanceof Error ? err.message : "Unable to sign in right now.");
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-5 py-10">
      <div
        className="absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(60% 60% at 50% 10%, hsl(var(--primary) / 0.07), transparent)",
        }}
      />
      <div className="w-full max-w-md rounded-xl border bg-card p-8 shadow-md">
        <Link href="/" className="mb-6 flex items-center gap-2.5">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md text-primary-foreground"
            style={{ background: "hsl(var(--primary))" }}
          >
            <ScanSearch className="h-3.5 w-3.5" />
          </span>
          <span className="font-serif text-[15px] font-semibold tracking-tight">GlassBox</span>
        </Link>

        <h1 className="font-serif text-2xl font-semibold tracking-tight">
          Sign in
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Use your assigned workspace credentials.
        </p>

        {error ? (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive"
          >
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5" />
            <span>{error}</span>
          </div>
        ) : null}

        <form onSubmit={onSubmit} className="mt-6 space-y-4" aria-label="Sign in form">
            <div className="grid gap-1.5">
              <Label htmlFor="tenant_slug" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Workspace
              </Label>
              <Input
                id="tenant_slug"
                name="tenant_slug"
                defaultValue="demo"
                autoComplete="organization"
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="email" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Work email
              </Label>
              <Input id="email" name="email" type="email" autoComplete="email" required />
            </div>
            <div className="grid gap-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="password" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                  Password
                </Label>
                <Link href="/forgot" className="text-xs text-muted-foreground hover:text-foreground">
                  Forgot?
                </Link>
              </div>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
            <Button type="submit" disabled={loading} className="h-10 w-full gap-1.5 rounded-md">
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                <>
                  Continue to workbench
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
        </form>

        <div className="mt-6 flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          <span>OR</span>
          <span className="h-px flex-1 bg-border" />
        </div>

        <div className="mt-4 grid gap-2">
          <Button variant="outline" className="h-10 w-full rounded-md text-sm" disabled>
            Continue with Okta (coming soon)
          </Button>
          <Button variant="outline" className="h-10 w-full rounded-md text-sm" disabled>
            Continue with Microsoft (coming soon)
          </Button>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          New to GlassBox?{" "}
          <Link href="/contact" className="text-foreground hover:underline">
            Request access
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams() needs to live inside a Suspense boundary in Next 15+.
  return (
    <Suspense fallback={<div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>}>
      <LoginInner />
    </Suspense>
  );
}
