"use client";

/**
 * Settings → Security.
 *
 * Five cards in one page so the user has a single home for every credential:
 *
 *  1. Change password — POSTs /users/me/change-password; on success we
 *     toast and the backend revokes every other refresh token, so the
 *     user has to sign back in everywhere else.
 *  2. Two-factor — enrol/verify TOTP via /auth/mfa/enroll + /auth/mfa/verify.
 *  3. BYO keys — list + upsert + delete.
 *  4. Active sessions — list + per-session info; "Log out everywhere" hits
 *     /users/me/sessions/revoke-all.
 *  5. (Future) recovery codes regeneration — punted to a later phase per
 *     docs/SECURITY-IMPLEMENTATION.md "deliberately NOT in this pass".
 */

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2, RefreshCcw, ShieldCheck, Smartphone, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { PageContainer, PageHeader } from "@/components/PageContainer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  changeOwnPassword,
  deleteByoKey,
  enrollMfa,
  listByoKeys,
  listOwnSessions,
  revokeAllOwnSessions,
  saveByoKey,
  verifyMfa,
  type ByoKey,
  type Session,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function SettingsSecurityPage() {
  const { user, refreshUser, logout } = useAuth();
  const router = useRouter();
  const [byoKeys, setByoKeys] = useState<ByoKey[] | null>(null);
  const [sessions, setSessions] = useState<Session[] | null>(null);

  const reloadByoKeys = useCallback(async () => {
    try {
      const rows = await listByoKeys();
      setByoKeys(rows);
    } catch {
      setByoKeys([]);
    }
  }, []);

  const reloadSessions = useCallback(async () => {
    try {
      const rows = await listOwnSessions();
      setSessions(rows);
    } catch {
      setSessions([]);
    }
  }, []);

  useEffect(() => {
    void reloadByoKeys();
    void reloadSessions();
  }, [reloadByoKeys, reloadSessions]);

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Settings"
        title="Security"
        description="Manage your password, two-factor authentication, BYO API keys, and active sessions."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <ChangePasswordCard />
        <TwoFactorCard onChanged={refreshUser} />
        <ByoKeysCard
          keys={byoKeys}
          onReload={reloadByoKeys}
        />
        <SessionsCard
          sessions={sessions}
          onReload={reloadSessions}
          onLogoutEverywhere={async () => {
            await revokeAllOwnSessions();
            toast.success("Signed out of every session");
            await logout();
            router.replace("/login");
          }}
        />
      </div>

      {user ? (
        <div className="mt-6 rounded-md border border-dashed bg-card/40 px-4 py-2.5 text-xs text-muted-foreground">
          Signed in as <span className="font-medium text-foreground">{user.email}</span> · workspace{" "}
          <span className="font-medium text-foreground">{user.tenant_slug}</span> · role{" "}
          <span className="font-medium text-foreground">{user.role}</span>
        </div>
      ) : null}
    </PageContainer>
  );
}

function Card(props: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-5">
      <header className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {props.title}
        </h2>
        <p className="mt-1 text-sm text-foreground/80">{props.description}</p>
      </header>
      {props.children}
    </section>
  );
}

function ChangePasswordCard() {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const current = String(form.get("current") || "");
    const next = String(form.get("next") || "");
    const confirm = String(form.get("confirm") || "");
    if (next !== confirm) {
      setError("New passwords don't match.");
      return;
    }
    if (next.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    setSubmitting(true);
    try {
      await changeOwnPassword(current, next);
      toast.success("Password changed", {
        description: "Other sessions have been signed out.",
      });
      event.currentTarget.reset();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(typeof err.detail === "string" ? err.detail : err.message);
      } else {
        setError(err instanceof Error ? err.message : "Could not change password.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card
      title="Password"
      description="Use at least 12 characters. Changing your password signs you out of every other session."
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <div className="grid gap-1.5">
          <Label htmlFor="current">Current password</Label>
          <Input id="current" name="current" type="password" autoComplete="current-password" required />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="next">New password</Label>
          <Input id="next" name="next" type="password" autoComplete="new-password" minLength={12} required />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="confirm">Confirm new password</Label>
          <Input id="confirm" name="confirm" type="password" autoComplete="new-password" minLength={12} required />
        </div>
        {error ? (
          <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        ) : null}
        <Button type="submit" disabled={submitting} className="h-10 w-full rounded-md">
          {submitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Updating…
            </>
          ) : (
            "Change password"
          )}
        </Button>
      </form>
    </Card>
  );
}

function TwoFactorCard({ onChanged }: { onChanged: () => Promise<unknown> }) {
  const { user } = useAuth();
  const [phase, setPhase] = useState<"idle" | "enrolling" | "verifying">("idle");
  const [secret, setSecret] = useState<string | null>(null);
  const [otpauth, setOtpauth] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startEnrollment() {
    setError(null);
    setPhase("enrolling");
    try {
      const challenge = await enrollMfa();
      setSecret(challenge.secret);
      setOtpauth(challenge.provisioning_uri);
      setPhase("verifying");
    } catch (err) {
      setPhase("idle");
      setError(err instanceof Error ? err.message : "Could not start enrollment.");
    }
  }

  async function submitVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      const result = await verifyMfa(code);
      setRecovery(result.recovery_codes);
      setPhase("idle");
      setCode("");
      await onChanged();
      toast.success("MFA enrolled");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Code rejected.");
    }
  }

  if (user?.mfa_enrolled && phase === "idle" && !recovery) {
    return (
      <Card
        title="Two-factor authentication"
        description="MFA is enrolled. Required for admin and owner roles."
      >
        <div className="flex items-center gap-2 text-sm text-foreground/80">
          <ShieldCheck className="h-4 w-4 text-[hsl(var(--state-grounded))]" />
          You're protected with an authenticator app.
        </div>
      </Card>
    );
  }

  return (
    <Card
      title="Two-factor authentication"
      description="Add a one-time code from an authenticator app. Required for admin and owner roles."
    >
      {recovery ? (
        <div className="space-y-3">
          <p className="text-sm">
            Save these recovery codes somewhere safe. They appear only once and each works once.
          </p>
          <ul className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-3 font-mono text-xs">
            {recovery.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <Button variant="outline" onClick={() => setRecovery(null)} className="h-9 w-full rounded-md">
            I've saved them
          </Button>
        </div>
      ) : phase === "verifying" && secret && otpauth ? (
        <form onSubmit={submitVerification} className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Add this secret to your authenticator app, then enter the current 6-digit code.
          </p>
          <div className="rounded-md border bg-muted/30 p-3 font-mono text-xs break-all">
            {secret}
          </div>
          <div className="text-xs text-muted-foreground">
            Or use the otpauth URI: <code className="break-all">{otpauth}</code>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="mfa_code">Authenticator code</Label>
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
          <Button type="submit" disabled={code.length < 6} className="h-10 w-full rounded-md">
            Verify and finish
          </Button>
        </form>
      ) : (
        <Button onClick={startEnrollment} className="h-10 w-full rounded-md gap-2">
          <Smartphone className="h-4 w-4" />
          {phase === "enrolling" ? "Preparing…" : "Enrol authenticator"}
        </Button>
      )}
    </Card>
  );
}

function ByoKeysCard({ keys, onReload }: { keys: ByoKey[] | null; onReload: () => Promise<void> }) {
  const [provider, setProvider] = useState("openrouter");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  async function onSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!apiKey) return;
    setSaving(true);
    try {
      await saveByoKey({ provider, api_key: apiKey });
      toast.success("Key saved");
      setApiKey("");
      await onReload();
    } catch (err) {
      toast.error("Could not save key", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(p: string) {
    try {
      await deleteByoKey(p);
      toast.success("Key removed");
      await onReload();
    } catch (err) {
      toast.error("Could not remove key", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }

  return (
    <Card
      title="BYO API keys"
      description="Your key is encrypted at rest with AES-GCM. The plaintext is never returned again — store it once."
    >
      <form onSubmit={onSave} className="grid gap-3 sm:grid-cols-[1fr_2fr_auto]">
        <Input
          aria-label="Provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          placeholder="provider"
          pattern="[a-z0-9._-]+"
          required
        />
        <Input
          aria-label="API key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-…"
          minLength={8}
          required
        />
        <Button type="submit" disabled={saving} className="h-10 rounded-md gap-1.5">
          <KeyRound className="h-4 w-4" />
          {saving ? "Saving…" : "Save"}
        </Button>
      </form>
      <div className="mt-4 space-y-2">
        {keys === null ? (
          <Skeleton className="h-12 rounded-md" />
        ) : keys.length === 0 ? (
          <div className="text-xs text-muted-foreground">No keys stored.</div>
        ) : (
          keys.map((row) => (
            <div
              key={row.provider}
              className="flex items-center justify-between rounded-md border bg-muted/20 px-3 py-2 text-sm"
            >
              <div className="flex flex-col">
                <span className="font-medium">{row.provider}</span>
                <span className="text-xs text-muted-foreground">
                  ····{row.last4 ?? "????"} · kid {row.kid} · added{" "}
                  {new Date(row.created_at).toLocaleString()}
                </span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => onDelete(row.provider)}
                aria-label={`Remove ${row.provider} key`}
              >
                <Trash2 className="h-4 w-4 text-muted-foreground" />
              </Button>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

function SessionsCard({
  sessions,
  onReload,
  onLogoutEverywhere,
}: {
  sessions: Session[] | null;
  onReload: () => Promise<void>;
  onLogoutEverywhere: () => Promise<void>;
}) {
  const [loggingOut, setLoggingOut] = useState(false);
  async function handleLogout() {
    setLoggingOut(true);
    try {
      await onLogoutEverywhere();
    } catch (err) {
      toast.error("Could not log out everywhere", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setLoggingOut(false);
    }
  }
  const active = sessions?.filter((s) => !s.revoked_at) ?? [];
  return (
    <Card
      title="Active sessions"
      description="Devices that currently hold a refresh token for your account."
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {sessions === null ? "Loading…" : `${active.length} active · ${sessions.length} total`}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onReload} className="gap-1.5">
            <RefreshCcw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={handleLogout}
            disabled={loggingOut || active.length === 0}
          >
            {loggingOut ? "Signing out…" : "Log out everywhere"}
          </Button>
        </div>
      </div>
      {sessions === null ? (
        <Skeleton className="h-24 rounded-md" />
      ) : sessions.length === 0 ? (
        <div className="text-xs text-muted-foreground">No sessions recorded.</div>
      ) : (
        <ul className="divide-y divide-border/60 overflow-hidden rounded-md border bg-card text-sm">
          {sessions.slice(0, 12).map((session) => (
            <li key={session.id} className="grid grid-cols-[1fr_auto] gap-2 px-3 py-2">
              <div>
                <div className="text-xs text-muted-foreground">
                  {session.user_agent ?? "Unknown client"}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  IP {session.ip ?? "—"} · created{" "}
                  {new Date(session.created_at).toLocaleString()}
                </div>
              </div>
              <span
                className={
                  session.revoked_at
                    ? "self-center rounded-sm border bg-muted/40 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
                    : "self-center rounded-sm border border-[hsl(var(--state-grounded))/40] bg-[hsl(var(--state-grounded))/10] px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-[hsl(var(--state-grounded))]"
                }
              >
                {session.revoked_at ? "revoked" : "active"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
