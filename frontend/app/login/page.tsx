"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, ScanSearch } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    await new Promise((r) => setTimeout(r, 350));
    toast.success("Signed in", { description: "Welcome back, Sarah." });
    router.push("/app/home");
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

        <h1 className="font-serif text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Use any credentials. This is a demo environment.
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div className="grid gap-1.5">
            <Label htmlFor="email" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
              Work email
            </Label>
            <Input id="email" type="email" defaultValue="sarah@glassbox.demo" required />
          </div>
          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password" className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
                Password
              </Label>
              <Link href="/" className="text-xs text-muted-foreground hover:text-foreground">
                Forgot?
              </Link>
            </div>
            <Input id="password" type="password" defaultValue="••••••••" required />
          </div>
          <Button type="submit" disabled={loading} className="h-10 w-full gap-1.5 rounded-md">
            {loading ? "Signing in…" : "Continue to workbench"}
            <ArrowRight className="h-4 w-4" />
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
          New to GlassBox? <Link href="/contact" className="text-foreground hover:underline">Request access</Link>
        </p>
      </div>
    </div>
  );
}
