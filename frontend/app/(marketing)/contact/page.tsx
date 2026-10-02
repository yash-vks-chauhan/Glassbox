"use client";

import { FormEvent, useState } from "react";
import { ArrowUpRight, BadgeCheck, FileSearch, Link2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { submitAccessRequest } from "@/lib/api";

const PROOF_POINTS = [
  {
    icon: FileSearch,
    title: "Cited answers only",
    body: "Every answer points to a clause in the approved document set, or GlassBox refuses and routes the question to Compliance.",
  },
  {
    icon: Link2,
    title: "Tamper-evident audit log",
    body: "Each decision is hash-chained. An auditor can verify the chain and replay exactly what the system saw.",
  },
  {
    icon: ShieldCheck,
    title: "No paid model calls by default",
    body: "The local evidence engine answers without sending client data to a hosted language model.",
  },
];

export default function ContactPage() {
  const [submitting, setSubmitting] = useState(false);
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const field = (name: string) => String(form.get(name) ?? "").trim();
    setSubmitting(true);
    try {
      await submitAccessRequest({
        name: field("name"),
        company: field("company"),
        work_email: field("email"),
        role: field("role"),
        message: field("message") || null,
        website: field("website") || null,
      });
      setSubmittedEmail(field("email"));
      toast.success("Request received");
    } catch (error) {
      toast.error("Could not send your request", {
        description: error instanceof Error ? error.message : "Please try again in a minute.",
      });
    } finally {
      setSubmitting(false);
    }
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
            Tell us how your team works. The walkthrough covers three scenarios live — a mandate
            breach, a refusal, and an audit replay.
          </p>

          <ul className="space-y-3 pt-2 text-sm">
            {PROOF_POINTS.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-secondary text-secondary-foreground">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <div>
                  <div className="font-medium">{title}</div>
                  <div className="text-muted-foreground">{body}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-xl border bg-card p-6 shadow-sm">
          {submittedEmail ? (
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
                Thanks — your request is logged.
              </h2>
              <p className="text-sm text-muted-foreground">
                The reply will go to <span className="font-medium text-foreground">{submittedEmail}</span>.
                If you already have workspace credentials, you can open the workbench now.
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
                  <Input id="name" name="name" required maxLength={120} placeholder="Sarah Kühn" />
                </Field>
                <Field id="company" label="Firm">
                  <Input id="company" name="company" required maxLength={160} placeholder="Acme Wealth" />
                </Field>
              </div>
              <Field id="email" label="Work email">
                <Input id="email" name="email" type="email" required placeholder="you@firm.com" />
              </Field>
              <Field id="role" label="Your role">
                <Input id="role" name="role" required maxLength={120} placeholder="Head of Compliance" />
              </Field>
              <Field id="message" label="What does your week look like?">
                <Textarea
                  id="message"
                  name="message"
                  rows={4}
                  maxLength={4000}
                  placeholder="Three advisors, a 2nd-line reviewer, and a regulator who's asking for evidence."
                />
              </Field>
              {/* Honeypot: hidden from people, filled in by form bots. */}
              <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
                <label htmlFor="website">Website</label>
                <input id="website" name="website" type="text" tabIndex={-1} autoComplete="off" />
              </div>
              <Button type="submit" disabled={submitting} className="h-10 w-full rounded-md">
                {submitting ? "Sending…" : "Request walkthrough"}
              </Button>
              <p className="text-[11px] text-muted-foreground">
                These details are used only to reply to this request.
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
