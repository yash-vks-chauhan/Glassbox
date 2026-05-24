"use client";

import { FormEvent, use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, ScanSearch } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, resetPassword } from "@/lib/api";

export default function ResetPasswordPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  // Next 15 hands us a Promise for route params.
  const { token } = use(params);
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirm = String(form.get("confirm") || "");
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      toast.success("Password updated", {
        description: "You can now sign in with the new password.",
      });
      router.replace("/login");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(typeof err.detail === "string" ? err.detail : err.message);
      } else {
        setError(err instanceof Error ? err.message : "Unable to reset password.");
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

        <h1 className="font-serif text-2xl font-semibold tracking-tight">Choose a new password</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          12+ characters, ideally a passphrase.
        </p>

        {error ? (
          <div role="alert" className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        ) : null}

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div className="grid gap-1.5">
            <Label htmlFor="password" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              New password
            </Label>
            <Input id="password" name="password" type="password" autoComplete="new-password" required minLength={12} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="confirm" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Confirm password
            </Label>
            <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required minLength={12} />
          </div>
          <Button type="submit" disabled={submitting} className="h-10 w-full gap-1.5 rounded-md">
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Updating…
              </>
            ) : (
              <>
                Set new password
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}
