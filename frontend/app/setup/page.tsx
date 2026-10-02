"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, ScanSearch, ShieldCheck } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  beginBootstrap,
  completeMfaSetup,
  setAccessToken,
  type BootstrapBeginResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

function slugFor(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) {
      return "Setup is turned off on this server. Start the API with BOOTSTRAP_SETUP_KEY set, then try again.";
    }
    if (err.status === 409) {
      return "This workspace already has an owner. Sign in instead, or ask its owner for an invitation.";
    }
    return typeof err.detail === "string" ? err.detail : err.message;
  }
  return err instanceof Error ? err.message : fallback;
}

const labelClass = "text-xs uppercase tracking-[0.12em] text-muted-foreground";

/** First-run setup: creates a workspace's first owner, with MFA, using the
 * setup key the server was started with. */
export default function SetupPage() {
  const router = useRouter();
  const { refreshUser } = useAuth();
  const [workspaceName, setWorkspaceName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [challenge, setChallenge] = useState<(BootstrapBeginResponse & { slug: string }) | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workspaceSlug = slugEdited ? slug : slugFor(workspaceName);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    if (password !== String(form.get("confirm") || "")) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    if (!SLUG_PATTERN.test(workspaceSlug)) {
      setError("The workspace ID may use lowercase letters, digits and dashes, and must start with a letter or digit.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await beginBootstrap({
        setup_key: String(form.get("setup_key") || "").trim(),
        tenant_slug: workspaceSlug,
        tenant_name: workspaceName.trim() || null,
        email: String(form.get("email") || "").trim(),
        password,
        display_name: String(form.get("display_name") || "").trim() || null,
      });
      setChallenge({ ...result, slug: workspaceSlug });
    } catch (err) {
      setError(describeError(err, "Could not start setup."));
    } finally {
      setSubmitting(false);
    }
  }

  async function onVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!challenge) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await completeMfaSetup(challenge.bootstrap_token, code);
      setAccessToken(result.access_token);
      setRecovery(result.recovery_codes);
      await refreshUser();
      toast.success("Signed in", { description: "Your workspace is ready." });
    } catch (err) {
      setError(describeError(err, "Could not verify the code."));
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

        {recovery && challenge ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ShieldCheck className="h-4 w-4 text-[hsl(var(--state-grounded))]" />
              Owner account ready
            </div>
            <p className="text-sm text-muted-foreground">
              Sign in to workspace <span className="font-mono text-foreground">{challenge.slug}</span>{" "}
              from now on. Save these recovery codes somewhere safe: they appear only once and each
              works once.
            </p>
            <ul className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-3 font-mono text-xs">
              {recovery.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <Button className="h-10 w-full rounded-md" onClick={() => router.replace("/app")}>
              Continue to GlassBox
              <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          </div>
        ) : challenge ? (
          <>
            <h1 className="font-serif text-2xl font-semibold tracking-tight">Turn on two-factor</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Owners sign in with an authenticator app. Add this account to Google Authenticator,
              Authy or 1Password, then enter the current 6-digit code.
            </p>
            <form onSubmit={onVerify} className="mt-6 space-y-4">
              <div className="space-y-3">
                <div className="flex justify-center rounded-md border bg-white p-4">
                  <QRCodeSVG value={challenge.provisioning_uri} size={176} level="M" includeMargin={false} />
                </div>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer select-none">
                    Can&apos;t scan? Enter this setup key manually
                  </summary>
                  <div
                    data-testid="mfa-setup-key"
                    className="mt-2 rounded-md border bg-muted/30 p-3 font-mono text-xs break-all select-all"
                  >
                    {challenge.mfa_secret}
                  </div>
                </details>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="mfa_code" className={labelClass}>
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
              <Button type="submit" disabled={submitting || code.length < 6} className="h-10 w-full gap-1.5 rounded-md">
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
              <p className="text-xs text-muted-foreground">
                The code request expires after 10 minutes. If it does, start setup again with the
                same email.
              </p>
            </form>
          </>
        ) : (
          <>
            <h1 className="font-serif text-2xl font-semibold tracking-tight">Set up GlassBox</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Create a workspace and its first owner. You need the setup key this server was started
              with (<span className="font-mono">BOOTSTRAP_SETUP_KEY</span>).
            </p>

            {error ? (
              <div role="alert" className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            ) : null}

            <form onSubmit={onCreate} className="mt-6 space-y-4">
              <div className="grid gap-1.5">
                <Label htmlFor="setup_key" className={labelClass}>
                  Setup key
                </Label>
                <Input id="setup_key" name="setup_key" type="password" autoComplete="off" required minLength={10} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="workspace_name" className={labelClass}>
                  Workspace name
                </Label>
                <Input
                  id="workspace_name"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  placeholder="Müller Wealth GmbH"
                  required
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="workspace_slug" className={labelClass}>
                  Workspace ID (used to sign in)
                </Label>
                <Input
                  id="workspace_slug"
                  value={workspaceSlug}
                  onChange={(e) => {
                    setSlugEdited(true);
                    setSlug(e.target.value.toLowerCase());
                  }}
                  className="font-mono"
                  required
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="display_name" className={labelClass}>
                  Your name (optional)
                </Label>
                <Input id="display_name" name="display_name" autoComplete="name" />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="email" className={labelClass}>
                  Work email
                </Label>
                <Input id="email" name="email" type="email" autoComplete="email" required />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="password" className={labelClass}>
                  Password
                </Label>
                <Input id="password" name="password" type="password" autoComplete="new-password" required minLength={12} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="confirm" className={labelClass}>
                  Confirm password
                </Label>
                <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required minLength={12} />
              </div>
              <Button type="submit" disabled={submitting} className="h-10 w-full gap-1.5 rounded-md">
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Creating…
                  </>
                ) : (
                  <>
                    Continue
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
