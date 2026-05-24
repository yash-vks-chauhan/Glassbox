"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2, ScanSearch, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, MfaRequiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type PendingMfa = {
  email: string;
  tenant_slug: string;
  mfa_token: string;
  next: string;
  created_at: number;
};

const STORAGE_KEY = "glassbox.pending_mfa";
const MAX_AGE_MS = 5 * 60 * 1000;

function safeRedirect(target: string | null): string {
  if (!target) return "/app/home";
  if (!target.startsWith("/app/") && target !== "/app") return "/app/home";
  return target;
}

function loadPending(): PendingMfa | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PendingMfa;
    if (!parsed.mfa_token || Date.now() - parsed.created_at > MAX_AGE_MS) {
      sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

function MfaInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [pending, setPending] = useState<PendingMfa | null>(null);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = safeRedirect(searchParams?.get("next") ?? pending?.next ?? null);

  useEffect(() => {
    const nextPending = loadPending();
    setPending(nextPending);
    if (!nextPending) {
      setError("Your MFA challenge expired. Sign in again to continue.");
    }
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pending) return;
    setError(null);
    setLoading(true);
    try {
      await login({ mfa_token: pending.mfa_token, mfa_code: code });
      sessionStorage.removeItem(STORAGE_KEY);
      toast.success("Signed in");
      router.replace(next);
    } catch (err) {
      if (err instanceof MfaRequiredError) {
        setError("MFA challenge expired. Sign in again to continue.");
      } else if (err instanceof ApiError && err.status === 401) {
        setError("Invalid or expired MFA code.");
      } else {
        setError(err instanceof Error ? err.message : "Unable to verify MFA.");
      }
    } finally {
      setLoading(false);
    }
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

        <h1 className="font-serif text-2xl font-semibold tracking-tight">Two-factor code</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Enter the current authenticator code for {pending?.email ?? "your account"}.
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

        <form onSubmit={onSubmit} className="mt-6 space-y-4" aria-label="MFA challenge form">
          <div className="grid gap-1.5">
            <Label htmlFor="mfa_code" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Authenticator or recovery code
            </Label>
            <Input
              id="mfa_code"
              name="mfa_code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={12}
              required
              autoFocus
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                sessionStorage.removeItem(STORAGE_KEY);
                router.replace(`/login?next=${encodeURIComponent(next)}`);
              }}
              className="h-10 w-full rounded-md gap-1.5"
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
            <Button
              type="submit"
              disabled={loading || !pending || code.length < 4}
              className="h-10 w-full rounded-md"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Verifying
                </>
              ) : (
                "Verify"
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function MfaPage() {
  return (
    <Suspense fallback={<div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>}>
      <MfaInner />
    </Suspense>
  );
}
