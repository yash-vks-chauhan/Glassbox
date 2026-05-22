import Link from "next/link";
import {
  ArrowUpRight,
  ClipboardCheck,
  FileCheck2,
  Files,
  Layers,
  LineChart,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { ButtonLink } from "@/components/ButtonLink";

export default function MarketingHome() {
  return (
    <div className="relative">
      <Hero />
      <LogosStrip />
      <Pillars />
      <HowItWorks />
      <CompareSection />
      <CtaSection />
    </div>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-border/70">
      <div className="absolute inset-x-0 -top-32 -z-10 h-[420px] [background:radial-gradient(60%_60%_at_50%_0%,hsl(var(--primary)/0.08),transparent)]" />
      <div className="mx-auto grid max-w-[1240px] gap-10 px-5 py-16 md:grid-cols-[1.15fr_1fr] md:py-24 lg:px-8 lg:py-28">
        <div className="space-y-7">
          <div className="inline-flex items-center gap-2 rounded-full border bg-card/60 px-3 py-1 text-[11px] font-medium text-muted-foreground">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: "hsl(var(--state-grounded))" }}
            />
            Built for EU AI Act Art. 12, MiFID II suitability, FINMA 2023/1
          </div>

          <h1 className="font-serif text-[40px] font-semibold leading-[1.05] tracking-tight text-foreground md:text-[56px] md:leading-[1.05]">
            Make every AI answer{" "}
            <span className="italic text-primary">defensible</span> to a regulator —
            without slowing your advisors down.
          </h1>

          <p className="max-w-xl text-base leading-7 text-muted-foreground md:text-[17px] md:leading-8">
            GlassBox sits between your advisors and your AI. Every answer is cited to an approved
            document, every refusal is logged, every decision is replayable. The audit binder writes
            itself.
          </p>

          <div className="flex flex-wrap items-center gap-3">
            <ButtonLink href="/app/home" className="h-11 gap-1.5 rounded-md px-5">
              Open the workbench
              <ArrowUpRight className="h-4 w-4" />
            </ButtonLink>
            <ButtonLink href="/contact" variant="outline" className="h-11 gap-1.5 rounded-md px-5">
              Book a 20-min walkthrough
            </ButtonLink>
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pt-2 text-xs text-muted-foreground">
            <Bullet>Citations on every claim</Bullet>
            <Bullet>Replayable decision traces</Bullet>
            <Bullet>Refuses when evidence is missing</Bullet>
          </div>
        </div>

        <HeroVisual />
      </div>
    </section>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="h-1 w-1 rounded-full"
        style={{ background: "hsl(var(--state-grounded))" }}
      />
      {children}
    </span>
  );
}

function HeroVisual() {
  return (
    <div className="relative">
      <div className="absolute -inset-4 -z-10 rounded-2xl bg-gradient-to-br from-primary/8 via-transparent to-accent/30 blur-2xl" />
      <div className="overflow-hidden rounded-xl border bg-card shadow-md">
        <div className="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
          <span>Conversation · C001 · Müller Family Office</span>
          <span className="font-mono normal-case">IPS v3.2 · Nov 2024</span>
        </div>
        <div className="space-y-3 p-4 text-sm leading-7">
          <div className="text-muted-foreground">
            <span className="font-medium text-foreground">Advisor · 09:14 </span>
            Can client move €2M into a single tech stock?
          </div>
          <div className="rounded-lg border bg-background p-3">
            <div className="mb-1.5 flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <span className="inline-flex items-center gap-1 rounded-sm border state-grounded px-1.5 py-0.5">
                <span
                  className="h-1 w-1 rounded-full"
                  style={{ background: "hsl(var(--state-grounded))" }}
                />
                Grounded
              </span>
              GlassBox · 09:14 · 312ms
            </div>
            <p className="text-foreground">
              No — IPS §4.1 caps single positions at{" "}
              <span className="font-medium">25%</span> of AUM
              <Sup>1</Sup>. Current AUM €18M ⇒ max position{" "}
              <span className="font-medium">€4.5M</span>
              <Sup>2</Sup>. The trade is within the single-position limit, but combined with the
              existing NVDA position would lift tech exposure to ~38%, above the 25% sector cap
              <Sup>3</Sup>. <span className="text-muted-foreground">Recommend: escalate.</span>
            </p>
            <div className="mt-2.5 flex items-center justify-between border-t pt-2 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <span>Grounded · 3 sources · Audit #a91b…</span>
              <span className="text-primary">View replay →</span>
            </div>
          </div>
          <div className="grid gap-1.5 rounded-md border border-dashed bg-card/60 p-2.5 text-[11px] text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Files className="h-3 w-3" /> IPS §4.1 · Concentration cap
            </div>
            <div className="flex items-center gap-1.5">
              <Files className="h-3 w-3" /> IPS §4.3 · Sector concentration
            </div>
            <div className="flex items-center gap-1.5">
              <Files className="h-3 w-3" /> Holdings snapshot · 2024-11-30
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Sup({ children }: { children: React.ReactNode }) {
  return (
    <sup className="ml-0.5 inline-flex h-3.5 min-w-3.5 items-center justify-center rounded-sm border bg-card px-0.5 align-super text-[9px] font-medium text-primary">
      {children}
    </sup>
  );
}

function LogosStrip() {
  const labels = [
    "Mandate breaches",
    "Suitability checks",
    "Cross-border flags",
    "Concentration caps",
    "Exclusion lists",
    "Sanctions screening",
  ];
  return (
    <section className="border-b border-border/70 bg-card/40">
      <div className="mx-auto max-w-[1240px] px-5 py-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          <span>Used daily for</span>
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {labels.map((label) => (
              <li key={label} className="flex items-center gap-1.5">
                <span
                  className="h-1 w-1 rounded-full"
                  style={{ background: "hsl(var(--muted-foreground))" }}
                />
                {label}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Pillars() {
  const items = [
    {
      icon: ShieldCheck,
      title: "Grounded-only answers",
      body: "Every claim cites a real document in your approved corpus. Unsupported sentences are stripped before they reach the advisor.",
    },
    {
      icon: FileCheck2,
      title: "Refuses to guess",
      body: "When the documents don't cover it, GlassBox refuses and routes to the right escalation desk — instead of inventing a rule.",
    },
    {
      icon: Layers,
      title: "Self-verifying",
      body: "Chain-of-Verification re-checks each claim against its source, discards anything that fails, and only then returns an answer.",
    },
    {
      icon: ClipboardCheck,
      title: "Replayable forever",
      body: "Every decision stored with question, sources, claims kept and dropped, trust scores, model and seed. One-click replay for audit.",
    },
  ];

  return (
    <section id="pillars" className="border-b border-border/70">
      <div className="mx-auto max-w-[1240px] px-5 py-16 lg:px-8 lg:py-20">
        <div className="mb-10 flex flex-col gap-3 lg:mb-12 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl space-y-3">
            <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Four controls, always on
            </div>
            <h2 className="font-serif text-3xl font-semibold tracking-tight md:text-4xl">
              Not a smarter AI. A defensible one.
            </h2>
            <p className="text-base leading-7 text-muted-foreground md:text-[17px] md:leading-8">
              The trust layer that makes AI-assisted advice safe to actually deploy in a regulated
              firm. Four controls that work whether the underlying model is open-source, hosted, or
              hot-swapped tomorrow.
            </p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <div
                key={item.title}
                className="rounded-xl border bg-card p-5 transition-shadow hover:shadow-sm"
              >
                <div
                  className="mb-4 flex h-9 w-9 items-center justify-center rounded-md"
                  style={{
                    background: "hsl(var(--state-grounded-soft))",
                    color: "hsl(var(--state-grounded-soft-foreground))",
                  }}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <h3 className="font-serif text-[17px] font-semibold tracking-tight">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    {
      n: "01",
      title: "Advisor asks against the approved corpus",
      body: "Threads are scoped to a client. The IPS version, jurisdictions, and risk profile travel with every question.",
    },
    {
      n: "02",
      title: "Every claim verified against its source",
      body: "Chain-of-Verification breaks the answer into claims and discards anything not supported by a retrieved chunk.",
    },
    {
      n: "03",
      title: "Compliance reviews from a queue, not an inbox",
      body: "Flagged decisions land in a sortable grid: claim, decide, escalate. Reviewer outcomes train the grounding model.",
    },
    {
      n: "04",
      title: "Audit binder writes itself",
      body: "Filter the audit log by date, client, outcome — export a regulator-ready PDF in one click.",
    },
  ];
  return (
    <section id="how" className="border-b border-border/70 bg-card/30">
      <div className="mx-auto max-w-[1240px] px-5 py-16 lg:px-8 lg:py-24">
        <div className="mb-12 max-w-2xl space-y-3">
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            How it works
          </div>
          <h2 className="font-serif text-3xl font-semibold tracking-tight md:text-4xl">
            One pipeline. Four checkpoints. Zero unauditable answers.
          </h2>
        </div>
        <ol className="grid gap-px overflow-hidden rounded-xl border bg-border md:grid-cols-4">
          {steps.map((step) => (
            <li key={step.n} className="bg-card p-5">
              <div className="mb-4 flex items-center justify-between">
                <span className="font-mono text-[11px] text-muted-foreground">{step.n}</span>
                <LineChart className="h-3.5 w-3.5 text-muted-foreground" />
              </div>
              <h3 className="font-serif text-base font-semibold leading-snug tracking-tight">
                {step.title}
              </h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function CompareSection() {
  const rows: Array<{ label: string; without: string; glassbox: string }> = [
    {
      label: "Source of every claim",
      without: "Implicit, often invented",
      glassbox: "Cited inline to approved document",
    },
    {
      label: "What happens out of scope",
      without: "Confident hallucination",
      glassbox: "Explicit refusal with escalation target",
    },
    {
      label: "Audit binder time",
      without: "Days reconstructing decisions",
      glassbox: "Minutes — one filter, one PDF",
    },
    {
      label: "Reviewer feedback loop",
      without: "Lives in email threads",
      glassbox: "Becomes training labels automatically",
    },
    {
      label: "Determinism check",
      without: "Not measured",
      glassbox: "Nightly job, on the dashboard",
    },
  ];
  return (
    <section className="border-b border-border/70">
      <div className="mx-auto max-w-[1240px] px-5 py-16 lg:px-8 lg:py-20">
        <div className="mb-10 max-w-2xl space-y-3">
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Without GlassBox vs. with
          </div>
          <h2 className="font-serif text-3xl font-semibold tracking-tight md:text-4xl">
            The difference shows up at audit time.
          </h2>
        </div>
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="grid grid-cols-[1.2fr_1fr_1fr] gap-px border-b bg-border text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            <div className="bg-card px-4 py-3">Capability</div>
            <div className="bg-card px-4 py-3">Today (raw LLM)</div>
            <div className="bg-card px-4 py-3">With GlassBox</div>
          </div>
          {rows.map((row) => (
            <div
              key={row.label}
              className="grid grid-cols-[1.2fr_1fr_1fr] gap-px bg-border text-sm last:border-0"
            >
              <div className="bg-card px-4 py-3 font-medium">{row.label}</div>
              <div className="bg-card px-4 py-3 text-muted-foreground">{row.without}</div>
              <div
                className="bg-card px-4 py-3"
                style={{ color: "hsl(var(--state-grounded-soft-foreground))" }}
              >
                {row.glassbox}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CtaSection() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 -z-10 [background:radial-gradient(50%_60%_at_50%_30%,hsl(var(--primary)/0.08),transparent)]" />
      <div className="mx-auto max-w-[1240px] px-5 py-20 text-center lg:px-8 lg:py-28">
        <h2 className="mx-auto max-w-2xl font-serif text-3xl font-semibold tracking-tight md:text-[42px]">
          Turn AI-assisted advice into a documented control.
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base text-muted-foreground md:text-[17px]">
          Open the workbench with a demo dataset, or book a walkthrough with your own IPS.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <ButtonLink href="/app/home" className="h-11 gap-1.5 rounded-md px-5">
            Open the workbench
            <ArrowUpRight className="h-4 w-4" />
          </ButtonLink>
          <ButtonLink href="/contact" variant="outline" className="h-11 gap-1.5 rounded-md px-5">
            Talk to us
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
