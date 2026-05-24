"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ArrowRight, Loader2, ScanSearch } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { forgotPassword } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") || "").trim();
    const tenantSlug = String(form.get("tenant_slug") || "demo").trim() || "demo";
    try {
      await forgotPassword(email, tenantSlug);
    } catch {
      // The backend deliberately always returns 200, so a thrown error here
      // is almost certainly transport-level. We still show the same generic
      // confirmation to avoid revealing whether the email exists.
    } finally {
      setDone(true);
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

        <h1 className="font-serif text-2xl font-semibold tracking-tight">Reset password</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          We'll email you a single-use token that's valid for one hour.
        </p>

        {done ? (
          <div className="mt-6 rounded-md border bg-muted/20 px-4 py-4 text-sm">
            If an account exists for that email, a reset email is on its way.
            <div className="mt-3">
              <Link href="/login" className="text-xs text-primary hover:underline">
                Back to sign in
              </Link>
            </div>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <div className="grid gap-1.5">
              <Label htmlFor="tenant_slug" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Workspace
              </Label>
              <Input id="tenant_slug" name="tenant_slug" defaultValue="demo" required />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="email" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Work email
              </Label>
              <Input id="email" name="email" type="email" autoComplete="email" required />
            </div>
            <Button type="submit" disabled={submitting} className="h-10 w-full gap-1.5 rounded-md">
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Sending…
                </>
              ) : (
                <>
                  Send reset email
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </form>
        )}

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Remembered it?{" "}
          <Link href="/login" className="text-foreground hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
