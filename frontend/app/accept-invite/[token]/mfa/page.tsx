"use client";

import { FormEvent, use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, ScanSearch, ShieldCheck } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, completeMfaSetup, setAccessToken } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useBrowserStorage, writeBrowserStorage } from "@/lib/use-browser-storage";
import { useIsClient } from "@/lib/use-is-client";
import { useNow } from "@/lib/use-now";

type PendingMfa = {
  mfa_setup_token: string;
  mfa_secret: string;
  provisioning_uri: string;
  created_at: number;
};

// The mfa_setup_token has a 10-min TTL on the backend. Refuse anything
// older client-side so we don't make the user type a code that's already
// destined to be rejected.
const MAX_AGE_MS = 9 * 60 * 1000;
const STORAGE_KEY = "glassbox.pending_invite_mfa";

type Challenge =
  | { status: "missing" }
  | { status: "expired" }
  | { status: "ready"; pending: PendingMfa };

function readChallenge(raw: string | null, nowMs: number | null): Challenge {
  if (!raw) return { status: "missing" };
  try {
    const parsed = JSON.parse(raw) as PendingMfa;
    if (!parsed.mfa_setup_token) return { status: "missing" };
    if (nowMs !== null && nowMs - parsed.created_at > MAX_AGE_MS) return { status: "expired" };
    return { status: "ready", pending: parsed };
  } catch {
    return { status: "missing" };
  }
}

export default function AcceptInviteMfaPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const router = useRouter();
  const { refreshUser } = useAuth();
  const raw = useBrowserStorage("session", STORAGE_KEY);
  const nowMs = useNow();
  const isClient = useIsClient();
  const challenge = useMemo(() => readChallenge(raw, nowMs), [raw, nowMs]);
  const pending = challenge.status === "ready" ? challenge.pending : null;
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Remember an expiry: the stale entry is removed below, and the notice
  // has to outlive it.
  const [expired, setExpired] = useState(false);
  if (challenge.status === "expired" && !expired) setExpired(true);

  // The setup secret is single-use; drop it once it can't be used.
  useEffect(() => {
    if (raw !== null && !pending) writeBrowserStorage("session", STORAGE_KEY, null);
  }, [raw, pending]);

  // No challenge to finish: start over from the invitation link.
  useEffect(() => {
    if (isClient && challenge.status === "missing" && !expired && !recovery) {
      router.replace(`/accept-invite/${token}`);
    }
  }, [isClient, challenge.status, expired, recovery, router, token]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pending) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await completeMfaSetup(pending.mfa_setup_token, code);
      // Backend has now flipped mfa_enrolled and set the refresh cookie.
      // Stash the access token + hydrate the auth context.
      setAccessToken(result.access_token);
      setRecovery(result.recovery_codes);
      writeBrowserStorage("session", STORAGE_KEY, null);
      await refreshUser();
      toast.success("Signed in", { description: "MFA enrolment complete." });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(typeof err.detail === "string" ? err.detail : err.message);
      } else {
        setError(err instanceof Error ? err.message : "Could not verify the code.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-5 py-10">
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

        {recovery ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ShieldCheck className="h-4 w-4 text-[hsl(var(--state-grounded))]" />
              MFA enrolled
            </div>
            <p className="text-sm text-muted-foreground">
              Save these recovery codes somewhere safe — they appear only once and each works once.
            </p>
            <ul className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-3 font-mono text-xs">
              {recovery.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <Button
              className="h-10 w-full rounded-md"
              onClick={() => router.replace("/app")}
            >
              Continue to GlassBox
              <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </div>
        ) : (
          <>
            <h1 className="font-serif text-2xl font-semibold tracking-tight">
              Set up two-factor
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Your role requires an authenticator app. Add this secret to
              Google Authenticator, Authy, or 1Password, then enter the
              current 6-digit code.
            </p>

            {pending ? (
              <form onSubmit={onSubmit} className="mt-6 space-y-4">
                <div className="space-y-3">
                  <Label className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                    Scan with your authenticator
                  </Label>
                  <div className="flex justify-center rounded-md border bg-white p-4">
                    <QRCodeSVG
                      value={pending.provisioning_uri}
                      size={176}
                      level="M"
                      includeMargin={false}
                    />
                  </div>
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer select-none">
                      Can&apos;t scan? Enter this setup key manually
                    </summary>
                    <div
                      data-testid="mfa-setup-key"
                      className="mt-2 rounded-md border bg-muted/30 p-3 font-mono text-xs break-all select-all"
                    >
                      {pending.mfa_secret}
                    </div>
                  </details>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="mfa_code" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                    Authenticator code
                  </Label>
                  <Input
                    id="mfa_code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={8}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                  />
                </div>
                {error ? (
                  <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    {error}
                  </div>
                ) : null}
                <Button
                  type="submit"
                  disabled={submitting || code.length < 6}
                  className="h-10 w-full gap-1.5 rounded-md"
                >
                  {submitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Verifying…
                    </>
                  ) : (
                    <>
                      Verify and finish
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </Button>
              </form>
            ) : expired ? (
              <div role="alert" className="mt-6 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                Your enrolment session expired. Ask for a fresh invitation.
              </div>
            ) : (
              <div className="mt-6 text-sm text-muted-foreground">Loading…</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
