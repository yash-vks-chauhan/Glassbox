"use client";

import { FormEvent, useState } from "react";
import { ArrowUpRight, BadgeCheck, Mail, MapPin } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export default function ContactPage() {
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    await new Promise((r) => setTimeout(r, 600));
    setSubmitting(false);
    setSubmitted(true);
    toast.success("Request received", {
      description: "We'll reply within one business day.",
    });
  }

  return (
    <div className="mx-auto max-w-[1240px] px-5 py-16 lg:px-8 lg:py-24">
      <div className="grid gap-12 lg:grid-cols-[1.05fr_1fr]">
        <div className="space-y-6">
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Contact
          </div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight md:text-[42px]">
            Book a 20-minute walkthrough.
          </h1>
          <p className="max-w-lg text-base leading-7 text-muted-foreground md:text-[17px] md:leading-8">
            Send us one of your IPS documents (synthetic or production). We'll wire it into the
            workbench and walk through three scenarios live — a mandate breach, a refusal, and an
            audit replay.
          </p>

          <ul className="space-y-3 pt-2 text-sm">
            <li className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md"
                style={{
                  background: "hsl(var(--state-grounded-soft))",
                  color: "hsl(var(--state-grounded-soft-foreground))",
                }}
              >
                <BadgeCheck className="h-3.5 w-3.5" />
              </span>
              <div>
                <div className="font-medium">EU + US compliance posture</div>
                <div className="text-muted-foreground">SOC 2 Type II underway, ISO 27001 mapped.</div>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md bg-secondary text-secondary-foreground">
                <Mail className="h-3.5 w-3.5" />
              </span>
              <div>
                <div className="font-medium">contact@glassbox.ai</div>
                <div className="text-muted-foreground">Replies same business day.</div>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-md bg-secondary text-secondary-foreground">
                <MapPin className="h-3.5 w-3.5" />
              </span>
              <div>
                <div className="font-medium">Zurich · London · Singapore</div>
                <div className="text-muted-foreground">Customer engineering teams in each region.</div>
              </div>
            </li>
          </ul>
        </div>

        <div className="rounded-xl border bg-card p-6 shadow-sm">
          {submitted ? (
            <div className="flex flex-col items-start gap-3 text-sm">
              <span
                className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px]"
                style={{
                  background: "hsl(var(--state-grounded-soft))",
                  color: "hsl(var(--state-grounded-soft-foreground))",
                }}
              >
                <BadgeCheck className="h-3 w-3" /> Request received
              </span>
              <h2 className="font-serif text-xl font-semibold tracking-tight">
                We'll be in touch within one business day.
              </h2>
              <p className="text-sm text-muted-foreground">
                In the meantime, open the workbench with a demo dataset — it'll show you exactly
                what we're going to walk through.
              </p>
              <a
                href="/app/home"
                className="inline-flex items-center gap-1.5 text-sm text-primary"
              >
                Open workbench
                <ArrowUpRight className="h-3.5 w-3.5" />
              </a>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4">
              <h2 className="font-serif text-xl font-semibold tracking-tight">
                Tell us about your team
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="name" label="Your name">
                  <Input id="name" required placeholder="Sarah Kühn" />
                </Field>
                <Field id="company" label="Firm">
                  <Input id="company" required placeholder="Acme Wealth" />
                </Field>
              </div>
              <Field id="email" label="Work email">
                <Input id="email" type="email" required placeholder="you@firm.com" />
              </Field>
              <Field id="role" label="Your role">
                <Input id="role" required placeholder="Head of Compliance" />
              </Field>
              <Field id="message" label="What does your week look like?">
                <Textarea
                  id="message"
                  rows={4}
                  placeholder="Three advisors, a 2nd-line reviewer, and a regulator who's asking for evidence."
                />
              </Field>
              <Button type="submit" disabled={submitting} className="h-10 w-full rounded-md">
                {submitting ? "Sending…" : "Request walkthrough"}
              </Button>
              <p className="text-[11px] text-muted-foreground">
                By submitting you agree to our standard NDA template; we'll countersign before any
                materials change hands.
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="text-xs uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}
