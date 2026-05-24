"use client";

/**
 * Admin → Users card.
 *
 * Lists every user in the caller's tenant, plus pending invitations.
 * Admin/owner can:
 *  - Invite by email (POST /auth/invite).
 *  - Change a user's role (PATCH /admin/users/{id}).
 *  - Revoke a user's active sessions (POST /admin/users/{id}/sessions/revoke).
 *  - Soft-revoke an account entirely (DELETE /admin/users/{id}).
 *  - Cancel a pending invitation.
 *
 * The card hides itself for non-admins (the parent page also gates, this
 * is belt-and-braces).
 */

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Loader2, MailPlus, RefreshCcw, ShieldOff, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  cancelAdminInvitation,
  changeAdminUserRole,
  inviteUser,
  listAdminInvitations,
  listAdminUsers,
  revokeAdminUser,
  revokeAdminUserSessions,
  type AdminInvitation,
  type AdminUser,
} from "@/lib/api";
import { hasAtLeastRole, useAuth } from "@/lib/auth-context";

const ROLES = ["advisor", "compliance", "admin", "owner"] as const;

export function UsersCard() {
  const { user, role } = useAuth();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [invites, setInvites] = useState<AdminInvitation[] | null>(null);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [u, i] = await Promise.all([listAdminUsers(), listAdminInvitations()]);
      setUsers(u);
      setInvites(i);
    } catch (err) {
      // 403 means we don't have access; bail silently — the card will hide.
      if (!(err instanceof ApiError) || err.status !== 403) {
        toast.error("Could not load users", {
          description: err instanceof Error ? err.message : undefined,
        });
      }
      setUsers([]);
      setInvites([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (hasAtLeastRole(role, "admin")) {
      void reload();
    }
  }, [role, reload]);

  if (!hasAtLeastRole(role, "admin")) return null;

  return (
    <section className="rounded-lg border bg-card p-5">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Users
          </h2>
          <p className="mt-1 text-sm text-foreground/80">
            Everyone in your workspace. Invite by email; role changes take effect on next request.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={reload} className="gap-1.5">
          <RefreshCcw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </header>

      <InviteForm onInvited={reload} />

      <div className="mt-4 space-y-2">
        {users === null || loading ? (
          <Skeleton className="h-24 rounded-md" />
        ) : users.length === 0 ? (
          <div className="text-xs text-muted-foreground">No users yet.</div>
        ) : (
          <div className="overflow-hidden rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-left text-xs uppercase tracking-[0.12em] text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Email</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">MFA</th>
                  <th className="px-3 py-2">Last login</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {users.map((row) => (
                  <UserRow
                    key={row.id}
                    row={row}
                    isSelf={row.id === user?.user_id}
                    onChanged={reload}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {invites && invites.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Pending invitations
          </h3>
          <ul className="mt-2 divide-y divide-border/60 rounded-md border bg-muted/20">
            {invites.map((invite) => (
              <li key={invite.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                <span className="flex-1 truncate">{invite.email}</span>
                <span className="rounded-sm border bg-card px-1.5 py-px text-[10px] uppercase tracking-[0.12em]">
                  {invite.role}
                </span>
                <span className="text-xs text-muted-foreground">
                  expires {new Date(invite.expires_at).toLocaleDateString()}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Cancel invite for ${invite.email}`}
                  onClick={async () => {
                    try {
                      await cancelAdminInvitation(invite.id);
                      await reload();
                      toast.success("Invitation cancelled");
                    } catch (err) {
                      toast.error("Could not cancel", {
                        description: err instanceof Error ? err.message : undefined,
                      });
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4 text-muted-foreground" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function InviteForm({ onInvited }: { onInvited: () => Promise<void> }) {
  const [submitting, setSubmitting] = useState(false);
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") || "").trim();
    const role = String(form.get("role") || "advisor") as AdminUser["role"];
    setSubmitting(true);
    try {
      await inviteUser(email, role);
      toast.success(`Invitation sent to ${email}`);
      (event.currentTarget as HTMLFormElement).reset();
      await onInvited();
    } catch (err) {
      toast.error("Invite failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <form
      onSubmit={onSubmit}
      className="grid items-end gap-3 sm:grid-cols-[1fr_auto_auto]"
    >
      <div className="grid gap-1.5">
        <Label htmlFor="invite-email" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
          Invite by email
        </Label>
        <Input
          id="invite-email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="teammate@firm.com"
          required
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="invite-role" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
          Role
        </Label>
        <select
          id="invite-role"
          name="role"
          defaultValue="advisor"
          className="h-10 rounded-md border bg-background px-2 text-sm"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <Button type="submit" disabled={submitting} className="h-10 gap-1.5">
        <MailPlus className="h-4 w-4" />
        {submitting ? "Sending…" : "Invite"}
      </Button>
    </form>
  );
}

function UserRow({
  row,
  isSelf,
  onChanged,
}: {
  row: AdminUser;
  isSelf: boolean;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);

  async function patchRole(next: AdminUser["role"]) {
    if (next === row.role) return;
    setBusy(true);
    try {
      await changeAdminUserRole(row.id, next);
      toast.success(`${row.email} → ${next}`);
      await onChanged();
    } catch (err) {
      toast.error("Role change failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  async function revokeSessions() {
    setBusy(true);
    try {
      await revokeAdminUserSessions(row.id);
      toast.success(`${row.email} signed out everywhere`);
      await onChanged();
    } catch (err) {
      toast.error("Could not revoke sessions", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  async function revokeAccount() {
    if (!confirm(`Revoke ${row.email}? They can be re-invited later but lose all access immediately.`)) {
      return;
    }
    setBusy(true);
    try {
      await revokeAdminUser(row.id);
      toast.success(`${row.email} revoked`);
      await onChanged();
    } catch (err) {
      toast.error("Revoke failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr>
      <td className="px-3 py-2">
        <div className="font-medium">{row.email}</div>
        <div className="text-[11px] text-muted-foreground">
          {row.locked ? "locked" : "active"}
          {isSelf ? " · you" : ""}
        </div>
      </td>
      <td className="px-3 py-2">
        <select
          value={row.role}
          onChange={(e) => patchRole(e.target.value as AdminUser["role"])}
          disabled={busy || isSelf}
          className="h-8 rounded-md border bg-background px-2 text-xs"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2">
        <span
          className={
            row.mfa_enrolled
              ? "rounded-sm border bg-muted/40 px-1.5 py-px text-[10px] uppercase tracking-[0.12em]"
              : "rounded-sm border bg-muted/40 px-1.5 py-px text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
          }
        >
          {row.mfa_enrolled ? "on" : "off"}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">
        {row.last_login_at ? new Date(row.last_login_at).toLocaleString() : "—"}
      </td>
      <td className="px-3 py-2 text-right">
        {busy ? (
          <Loader2 className="ml-auto h-4 w-4 animate-spin text-muted-foreground" />
        ) : (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Revoke ${row.email}'s sessions`}
              onClick={revokeSessions}
              disabled={isSelf}
              title="Log out everywhere"
            >
              <ShieldOff className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Revoke ${row.email}`}
              onClick={revokeAccount}
              disabled={isSelf}
              title="Revoke account"
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        )}
      </td>
    </tr>
  );
}
