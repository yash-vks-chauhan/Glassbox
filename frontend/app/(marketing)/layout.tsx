import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight, ScanSearch } from "lucide-react";

import { ButtonLink } from "@/components/ButtonLink";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border/70 bg-background/70 backdrop-blur supports-[backdrop-filter]:bg-background/50">
        <div className="mx-auto flex h-14 max-w-[1240px] items-center justify-between gap-6 px-5 lg:px-8">
          <Link href="/" className="flex items-center gap-2.5">
            <span
              className="flex h-7 w-7 items-center justify-center rounded-md text-primary-foreground"
              style={{ background: "hsl(var(--primary))" }}
            >
              <ScanSearch className="h-3.5 w-3.5" />
            </span>
            <span className="font-serif text-[15px] font-semibold tracking-tight">
              GlassBox
            </span>
          </Link>
          <nav className="hidden items-center gap-6 text-sm md:flex">
            <Link href="/#how" className="text-muted-foreground hover:text-foreground">
              How it works
            </Link>
            <Link href="/#pillars" className="text-muted-foreground hover:text-foreground">
              Controls
            </Link>
            <Link href="/pricing" className="text-muted-foreground hover:text-foreground">
              Pricing
            </Link>
            <Link href="/contact" className="text-muted-foreground hover:text-foreground">
              Contact
            </Link>
          </nav>
          <div className="flex items-center gap-1.5">
            <ThemeToggle />
            <Link
              href="/login"
              className="hidden text-sm text-muted-foreground hover:text-foreground sm:inline"
            >
              Sign in
            </Link>
            <ButtonLink href="/contact" variant="default" size="sm" className="h-9 gap-1.5 rounded-md">
              Book a walkthrough
              <ArrowUpRight className="h-3.5 w-3.5" />
            </ButtonLink>
          </div>
        </div>
      </header>

      <main className="relative">{children}</main>

      <footer className="border-t border-border/70 bg-card/40">
        <div className="mx-auto grid max-w-[1240px] gap-8 px-5 py-10 md:grid-cols-[1.4fr_1fr_1fr_1fr] lg:px-8">
          <div>
            <div className="flex items-center gap-2.5">
              <span
                className="flex h-7 w-7 items-center justify-center rounded-md text-primary-foreground"
                style={{ background: "hsl(var(--primary))" }}
              >
                <ScanSearch className="h-3.5 w-3.5" />
              </span>
              <span className="font-serif text-[15px] font-semibold tracking-tight">GlassBox</span>
            </div>
            <p className="mt-3 max-w-xs text-sm text-muted-foreground">
              Audit-grade AI for wealth-advisory teams. Citations on every answer, replay on every decision.
            </p>
          </div>
          <FooterCol
            title="Product"
            links={[
              { label: "Workbench", href: "/app/home" },
              { label: "Pricing", href: "/pricing" },
              { label: "Changelog", href: "/#whatsnew" },
            ]}
          />
          <FooterCol
            title="Resources"
            links={[
              { label: "Trust & security", href: "/#trust" },
              { label: "EU AI Act overview", href: "/#regulation" },
              { label: "Contact sales", href: "/contact" },
            ]}
          />
          <FooterCol
            title="Company"
            links={[
              { label: "About", href: "/contact" },
              { label: "Privacy", href: "/contact" },
              { label: "Terms", href: "/contact" },
            ]}
          />
        </div>
        <div className="border-t border-border/70 py-4">
          <div className="mx-auto flex max-w-[1240px] flex-col items-center justify-between gap-2 px-5 text-xs text-muted-foreground md:flex-row lg:px-8">
            <span>© {new Date().getFullYear()} GlassBox. All rights reserved.</span>
            <span>Built for regulated wealth-advisory teams.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function FooterCol({
  title,
  links,
}: {
  title: string;
  links: Array<{ label: string; href: string }>;
}) {
  return (
    <div>
      <div className="mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </div>
      <ul className="space-y-2 text-sm">
        {links.map((link) => (
          <li key={link.href}>
            <Link href={link.href} className="text-foreground/80 hover:text-foreground">
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
