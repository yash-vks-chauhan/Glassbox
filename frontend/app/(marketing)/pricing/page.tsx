import Link from "next/link";
import { Check, Minus } from "lucide-react";

import { ButtonLink } from "@/components/ButtonLink";

export const metadata = { title: "Pricing" };

type Tier = {
  name: string;
  description: string;
  price: string;
  cadence: string;
  features: Array<{ label: string; included: boolean }>;
  cta: { href: string; label: string };
  highlight?: boolean;
};

const TIERS: Tier[] = [
  {
    name: "Pilot",
    description: "Single team, single corpus. Get to a defended demo in two weeks.",
    price: "€0",
    cadence: "for 30 days",
    cta: { href: "/contact", label: "Start a pilot" },
    features: [
      { label: "Up to 3 advisors, 1 reviewer", included: true },
      { label: "10,000 grounded answers / month", included: true },
      { label: "Audit log + CSV export", included: true },
      { label: "PDF audit-binder export", included: false },
      { label: "Custom model + BYO inference", included: false },
      { label: "SSO + role-based access", included: false },
    ],
  },
  {
    name: "Desk",
    description: "Multiple advisors and a 2nd-line reviewer working a daily queue.",
    price: "€1,200",
    cadence: "per seat / year",
    highlight: true,
    cta: { href: "/contact", label: "Talk to sales" },
    features: [
      { label: "Unlimited advisors, up to 5 reviewers", included: true },
      { label: "Unlimited grounded answers", included: true },
      { label: "Audit log + CSV export", included: true },
      { label: "PDF audit-binder export", included: true },
      { label: "Reviewer outcomes train grounding scorer", included: true },
      { label: "SSO + role-based access", included: false },
    ],
  },
  {
    name: "Firm",
    description: "Whole firm, multi-desk, regulator-ready posture.",
    price: "Custom",
    cadence: "annual contract",
    cta: { href: "/contact", label: "Contact us" },
    features: [
      { label: "Multi-tenant: desks, regions, jurisdictions", included: true },
      { label: "Air-gapped deploy on your AWS / Azure", included: true },
      { label: "Custom model + BYO inference", included: true },
      { label: "SSO + role-based access", included: true },
      { label: "EU AI Act Art. 12 evidence pack", included: true },
      { label: "24×5 named support", included: true },
    ],
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-[1240px] px-5 py-16 lg:px-8 lg:py-24">
      <div className="mx-auto max-w-2xl space-y-4 text-center">
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Pricing
        </div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight md:text-[42px]">
          Pay per seat, not per answer.
        </h1>
        <p className="text-base leading-7 text-muted-foreground md:text-[17px] md:leading-8">
          Every plan ships with citations, refusals, audit replay, and the trust dashboard. You
          upgrade for scale, exports, and deployment posture — not for the controls themselves.
        </p>
      </div>

      <div className="mt-10 grid gap-4 lg:grid-cols-3 lg:mt-14">
        {TIERS.map((tier) => (
          <PricingCard key={tier.name} tier={tier} />
        ))}
      </div>

      <FaqStrip />
    </div>
  );
}

function PricingCard({ tier }: { tier: Tier }) {
  return (
    <div
      className={`relative flex flex-col rounded-xl border bg-card p-6 ${
        tier.highlight ? "shadow-md ring-1 ring-primary/30" : ""
      }`}
    >
      {tier.highlight ? (
        <span
          className="absolute -top-3 left-6 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em]"
          style={{
            background: "hsl(var(--primary))",
            color: "hsl(var(--primary-foreground))",
            borderColor: "hsl(var(--primary))",
          }}
        >
          Most teams pick this
        </span>
      ) : null}
      <div className="space-y-2">
        <h3 className="font-serif text-xl font-semibold tracking-tight">{tier.name}</h3>
        <p className="text-sm text-muted-foreground">{tier.description}</p>
      </div>
      <div className="my-6 flex items-baseline gap-2">
        <span className="font-serif text-4xl font-semibold tracking-tight tabular">{tier.price}</span>
        <span className="text-sm text-muted-foreground">{tier.cadence}</span>
      </div>
      <ul className="mb-6 space-y-2.5">
        {tier.features.map((feature) => (
          <li
            key={feature.label}
            className={`flex items-start gap-2.5 text-sm ${
              feature.included ? "text-foreground" : "text-muted-foreground/70"
            }`}
          >
            {feature.included ? (
              <Check className="mt-0.5 h-4 w-4" style={{ color: "hsl(var(--state-grounded))" }} />
            ) : (
              <Minus className="mt-0.5 h-4 w-4 text-muted-foreground/60" />
            )}
            <span>{feature.label}</span>
          </li>
        ))}
      </ul>
      <ButtonLink
        href={tier.cta.href}
        variant={tier.highlight ? "default" : "outline"}
        className="mt-auto h-10 rounded-md"
      >
        {tier.cta.label}
      </ButtonLink>
    </div>
  );
}

function FaqStrip() {
  const faqs = [
    {
      q: "Do you charge per token or per answer?",
      a: "No. Pricing is per advisor / reviewer seat. The model behind it is yours to pick.",
    },
    {
      q: "Can we bring our own model?",
      a: "Yes. BYO OpenRouter key on Pilot and Desk; full custom inference (Bedrock, Vertex, self-hosted) on Firm.",
    },
    {
      q: "Where does our data live?",
      a: "Pilot and Desk run on our EU AWS region with strict isolation. Firm deploys into your cloud — we never see your data.",
    },
    {
      q: "What if the regulator asks for a specific decision?",
      a: "Audit log → filter by date and client → export a PDF binder. Every claim, source, and reviewer override is in it.",
    },
  ];
  return (
    <section className="mt-16 grid gap-2 sm:grid-cols-2">
      {faqs.map((faq) => (
        <div key={faq.q} className="rounded-lg border bg-card p-5">
          <div className="font-serif text-base font-semibold tracking-tight">{faq.q}</div>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{faq.a}</p>
        </div>
      ))}
      <div className="rounded-lg border border-dashed bg-card/40 p-5 sm:col-span-2">
        <div className="font-serif text-base font-semibold tracking-tight">
          Have a question we didn't answer?
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Pricing for regulated firms always needs context. Reach out and we'll send you a quote
          alongside the security questionnaire.
        </p>
        <Link href="/contact" className="mt-3 inline-flex items-center gap-1.5 text-sm text-primary">
          Open contact form →
        </Link>
      </div>
    </section>
  );
}
