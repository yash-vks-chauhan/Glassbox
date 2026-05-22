# GlassBox — Product Revamp Plan (v1)

> Status: **proposal, awaiting sign-off**.
> Owner: design + product.
> No implementation has started. This document is the alignment artifact before any code changes.

---

## 1. Why we're revamping

Today's GlassBox **works** but it **reads as a college project**. Concretely:

- The work surface ("Advisor") is a single-page form (textarea + button + result card), not a workbench.
- Marketing content lives inside the app: hero, "operating contract" pills, three scenario cards, FAQ at the bottom of the work surface.
- Internal-QA controls are exposed to end users: "Measure Determinism", "BYO OpenRouter key" inline.
- Trust badges appear as a separate row of colored pills, not embedded in the answer.
- "Decisions" and "Audit" overlap conceptually; the bare `/audit` route is a 404.
- "Review" is a flat list with no claim/decide/SLA behavior — i.e. it's a placeholder.
- The dashboard shows percentages without thresholds; nobody can tell if 38% refusal is good or bad.

Net effect: the **vocabulary** is right (decisions, audit, refusals, grounding) but the **behavior** of a real product — sticky context, persistent threads, role-based surfaces, queues with SLAs, inline citations, exports — is not there. We need to redesign for that.

---

## 2. Who we're actually building for

Two real personas. We design for **(1) primarily** and serve **(2) inside the same app**.

| | (1) Compliance / 2nd-line risk | (2) Advisor / RM |
|---|---|---|
| Daily artifact | A queue of flagged decisions + an audit binder | Client questions answered defensibly, fast |
| What they want from us | Evidence captured **as a side-effect** of normal work, not extra | A "second opinion" they can show a supervisor |
| Buying authority | **Yes — signs the contract** | No, but their adoption is the proof point |
| Mental model | Spreadsheet / queue | Conversation / case file |
| What "good" looks like | "SEC walks in tomorrow, I have a binder in 15 min" | "I answered correctly without flipping through 4 PDFs" |
| Failure mode | Tool adds work instead of removing it | Tool is slower than calling compliance directly |

The compliance angle is what makes GlassBox defensible vs. a generic ChatGPT wrapper. **The product narrative is "audit as a side-effect," not "smarter answers."**

### Research signals informing this

- Compliance teams spend ~40% of their time gathering evidence (Stratifi, 2025). The right product **captures evidence while you work**, not after.
- Compliance pain is fragmentation: CRM, comms-surveillance, trade-monitoring, and document review are four tools that don't talk. We don't need to replace all of them, but **we must export cleanly** to whatever's adjacent.
- The three questions a CCO asks at audit time: *What happened? Why did it happen? What was done about it?* Every page of GlassBox should answer one of those.
- For analysts/compliance, **chat is sometimes the wrong primitive entirely** — Hebbia famously chose a grid. Advisors talk; compliance officers filter. We'll honor both.
- Citations should be **adjacent to claims, not in a separate tab** (NN/g). Hover preview, click to open in side panel.
- Avoid step-by-step "reasoning" walkthroughs — research shows these are post-hoc rationalizations, not faithful explanations. Show **sources** and **what was kept/discarded**, not "how the AI thought."
- Avoid first-person anthropomorphic phrasing. *"I found three sources"* → *"Three sources retrieved."*

---

## 3. The structural decision

**Split GlassBox into two surfaces:**

### 3.1 Marketing site at `/`
- Lives in its own Next.js route group `(marketing)`. Different layout. No app chrome.
- Single hero, three proof points, one demo CTA (*"Try with your own IPS"*).
- Pricing teaser. Compliance-buyer testimonials (placeholder until we have them).
- Reads in 30 seconds; sells the **"audit as a side-effect"** thesis.

### 3.2 The workbench at `/app/*`
- Behind a sign-in stub (mock auth is fine for v1).
- **Left sidebar nav**, not top tabs.
- Role-aware: Advisor sees client/thread surfaces; Compliance sees queue/audit/insights.
- No marketing copy. No FAQs. No "scenario buttons". No "Measure Determinism" button visible to advisors.

This split alone fixes ~70% of the "demo smell." The app stops shouting about itself.

### 3.3 Route map

```
/                          (marketing) hero + CTA
/pricing                   (marketing) tiers
/contact                   (marketing) lead capture
/login                     auth stub

/app                        → redirects to /app/home
/app/home                  today's queue + alerts + recent activity
/app/clients               client list (search, filter)
/app/clients/[id]          client detail: IPS, holdings, threads, flags
/app/clients/[id]/ask      threaded conversation (replaces today's "/")
/app/threads               cross-client thread list (advisor's inbox)
/app/threads/[id]          single thread
/app/review                review queue (compliance) — grid
/app/review/[id]           single decision review
/app/audit                 audit log — searchable, exportable
/app/audit/[id]            decision replay (already exists, keep)
/app/library               docs: IPS, factsheets, regs (versioned)
/app/library/[doc]         doc viewer
/app/insights              governance metrics — was "Dashboard"
/app/admin/*               org, roles, models, rate limits, API keys
```

### 3.4 What gets removed entirely
- The hero section, "operating contract" card, workflow step cards, FAQ section, role tiles from current `/`.
- The "Decision scenarios" three-card row from `ChatPanel`.
- The "Measure Determinism" button (moved to nightly job + Insights chart).
- The "BYO OpenRouter key" inline field (moved to `/app/admin/models`).
- The audit "/audit" 404'd entry — replaced by `/app/audit` real index.
- "Decisions" and "Audit" merge into one surface ("Audit log").
- Trust badges as a separate row — folded into a one-line meta band under each assistant message.

---

## 4. The advisor surface (chat done properly)

### 4.1 Layout

```
┌────────────────────────────────────────────────────────────────────────┐
│ Müller Family Office · C001   ·   IPS v3.2 (Nov 2024) · 4 open flags  │  ← sticky context bar
├──────────┬───────────────────────────────────────────┬─────────────────┤
│ THREADS  │  CONVERSATION                             │  EVIDENCE       │
│          │                                           │                 │
│ ◉ Tech   │  You · 09:14                              │  IPS §4.1       │
│   conc.  │  Can client move $2M into single tech?    │  Concentration  │
│ ○ ESG    │                                           │  cap: 25% of    │
│   review │  GlassBox · 09:14                         │  AUM per single │
│ ○ Cross- │  No — IPS §4.1 caps single positions at   │  position.      │
│   border │  25% of AUM.[1] Current AUM €18M → max    │                 │
│          │  position €4.5M.[2] $2M alone is within   │  ─────────────  │
│ + New    │  the limit, but combined with the         │                 │
│          │  existing NVDA position (currently 6.8%)  │  Holdings       │
│          │  this would raise tech exposure to ~38%,  │  snapshot       │
│          │  which is above the 25% sector cap.       │  2024-11-30     │
│          │                                           │  NVDA  6.8%     │
│          │  Recommend: escalate to portfolio review. │  AAPL  3.1%     │
│          │  Grounded · 3 sources · Audit #a91b…      │                 │
│          │  [ Escalate ] [ Mark resolved ] [ Copy ]  │                 │
│          │                                           │                 │
│          │  ┌──────────────────────────────────┐     │                 │
│          │  │ Ask a follow-up about C001…      │     │                 │
│          │  └──────────────────────────────────┘     │                 │
└──────────┴───────────────────────────────────────────┴─────────────────┘
```

### 4.2 Behavioral rules

- **Citations are inline footnotes `[1]`, `[2]`** — not a separate tab. Hover = snippet preview popover. Click = scroll the right-hand evidence panel to that source.
- **The trust signal is one quiet meta line** under each assistant message: *"Grounded · 3 sources · Audit #a91b…"*. Click reveals the full trust breakdown (grounding score, determinism, claims kept/discarded). Not three colored pills.
- **Refusals are messages, not error banners.** Same bubble shape, different left-border color and an explicit CTA: *"Escalate to Compliance — DACH desk"*. Not a red Alert component.
- **Threads persist per client.** Yesterday's "Tech concentration" thread is still there today. Each thread has a status: `open / resolved / escalated`. The thread itself is the unit a supervisor can review later.
- **The composer is a textarea at the bottom of the conversation,** not a prominent form at the top of the page. Cmd+Enter to send. No "Ask GlassBox" button label — just a paper-plane icon. The product is the conversation, not the form.
- **No "Scenario" cards.** New users get an empty-state with one example call-to-action: *"Pick a client to begin."* Examples belong in the marketing site, not the workbench.

### 4.3 What disappears from the advisor's view
- The "Decision" sticky card (current right side of `ChatPanel`) — its contents now live inline as the assistant message.
- The Settings popover and "Advanced controls" collapsible — moved to Admin.
- The "Measure Determinism" button — automated nightly, surfaced on Insights.
- The "BYO key" field — moved to Admin (and only org admins see it).

---

## 5. The compliance surface (grid, not chat)

This is the most important UX bet in the revamp. Compliance officers do not want to chat. They want to **work a queue** and **build an evidence binder**.

### 5.1 `/app/review` — the queue

A spreadsheet-like grid. Each row is one flagged or escalated decision. Each column is an attribute the CCO would sort/filter by.

```
Filters: [Status ▾] [Client ▾] [Outcome ▾] [Grounding < 60% ▾] [Date: last 7d ▾] [Reviewer: me ▾]   [Export CSV] [Export PDF binder]

┌────┬──────────┬─────────┬──────────┬─────────┬───────────┬──────────┬──────────┬──────────┐
│ ▢  │ When     │ Client  │ Advisor  │ Outcome │ Grounding │ Reviewer │ SLA      │ Replay   │
├────┼──────────┼─────────┼──────────┼─────────┼───────────┼──────────┼──────────┼──────────┤
│ ▣  │ 09:14    │ C001    │ S. Kühn  │ Flagged │ 72%       │ —        │ 2h 14m   │ Open ▸   │
│ ▢  │ 08:51    │ C014    │ M. Reis  │ Refused │ —         │ A. Lopez │ done     │ Open ▸   │
│ ▢  │ 08:42    │ C003    │ S. Kühn  │ Flagged │ 64%       │ me       │ 1h 32m   │ Open ▸   │
└────┴──────────┴─────────┴──────────┴─────────┴───────────┴──────────┴──────────┴──────────┘

Bulk actions for selected rows: [ Claim ] [ Mark reviewed ] [ Escalate ] [ Export PDF ]
```

Why a grid: every reviewer's instinct is *sort by Grounding ascending, filter to last 7 days, claim the top 10*. Chat can't do that. Grid can.

### 5.2 `/app/review/[id]` — single decision review

Three-pane: question + answer (left), evidence (middle), reviewer panel (right).

The reviewer panel is the new thing:

```
Reviewer
─────────────────────
Status:  [ Open  ▾ ]
Assignee: A. Lopez
Outcome assessment:
  ◯  AI was correct
  ●  AI was correct but needs supervisor sign-off
  ◯  AI was wrong — override below
  ◯  Insufficient evidence — escalate

Reason code:
  [ Concentration breach (IPS) ▾ ]

Notes:
  ┌────────────────────────────────────┐
  │ Concur with refusal. Cross-border  │
  │ tax not in approved corpus.        │
  └────────────────────────────────────┘

SLA: 1h 32m remaining   [ Submit review ]
```

**This is the page that earns the buyer's love.** It also closes the ML loop: every reviewer submission becomes a labeled example for the grounding scorer.

### 5.3 `/app/audit` — system of record

Same grid shell as `/app/review` but **read-only**, **all outcomes (not just flagged)**, **date-range and reviewer filters**, and a prominent **Export PDF binder** action that generates a regulator-ready document for a date range.

The audit binder export is the single feature most likely to make a CCO sign a contract.

---

## 6. The home / dashboard surfaces

### 6.1 `/app/home`

A small, action-oriented landing for whoever just logged in.

- **Top strip**: 3 cards — *Open flags assigned to me* · *SLA breaches today* · *IPS updated in the last 7 days*.
- **Middle**: 2-pane — *Recent activity* (your last 10 actions) · *Watchlist* (clients you follow).
- **Below**: *What's new* — last release notes, model changes, doc updates.

No marketing copy. No "operating contract." Linear's home, not a landing page.

### 6.2 `/app/insights` (renamed from Dashboard)

Same metrics, fundamentally different design rules:

- **Every tile has a target.** "Grounding ≥ 80%". Below target = amber. >10pp below = red.
- **Every tile has a 7-day sparkline.** Single percent with no trend is decoration.
- **Every tile is drillable.** Click "Refusal rate" → opens the audit log filtered to refusals in that window.
- **Determinism is here, not in chat.** It runs as a nightly job and posts to this page.
- **Chart bars and axes have labels.** Today's chart shows bars with no axis legend — that's a bug.
- **One headline number at the top.** *"3 of 6 governance SLAs in range."* The exec view.

---

## 7. Color palette (the visual reset)

### 7.1 Current state and why we're changing it

Current tokens (light): navy primary `215 55% 24%`, emerald accent `158 44% 92%`, cold slate background `210 25% 98%`. It's perfectly acceptable but reads as "generic fintech." Two specific problems:

1. **Emerald reads as "growth/money."** Wrong semantic for an *audit* product. Audit means restraint, not upside.
2. **Cold slate background** is the same as 200 other SaaS apps. We're competing in a category where seriousness is a feature.

### 7.2 The new palette — "ink + parchment"

Influences: the Financial Times paper aesthetic, Bridgewater research notes, a Bloomberg terminal stripped of orange, Linear's neutral discipline.

**Light theme:**

| Token | New value | Old value | What it is |
|---|---|---|---|
| `--background` | `36 25% 97%` | `210 25% 98%` | Warm off-white (parchment). Less clinical than cold slate. |
| `--foreground` | `220 35% 11%` | `222 47% 11%` | Ink black, slight navy cast. |
| `--card` | `0 0% 100%` | `0 0% 100%` | Pure white — cards float over parchment. |
| `--primary` | `218 58% 20%` | `215 55% 24%` | Deeper, slightly cooler ink-navy. |
| `--primary-foreground` | `36 25% 97%` | `210 40% 98%` | Parchment on navy. |
| `--secondary` | `34 18% 92%` | `214 32% 94%` | Warm putty for chips, badges, hover states. |
| `--muted` | `34 12% 94%` | `210 32% 95%` | Warm muted surface. |
| `--muted-foreground` | `220 12% 38%` | `215 16% 42%` | Quiet ink-gray for meta text. |
| `--accent` | `34 30% 88%` | `158 44% 92%` | **Removed the emerald.** Warm putty accent. Used for hover/selected, not for "grounded." |
| `--accent-foreground` | `218 58% 20%` | `166 64% 20%` | Same as primary. |
| `--destructive` | `0 65% 42%` | `0 84.2% 60.2%` | Deeper, less neon red — "vermillion seal," not "alert toast." |
| `--border` | `34 14% 86%` | `214 24% 88%` | Warm border. |
| `--ring` | `218 58% 30%` | `215 55% 32%` | Focus ring in primary family. |

**Status colors (new — semantic, not in shadcn defaults):**

| Token | Value | Used for |
|---|---|---|
| `--state-grounded` | `175 35% 30%` | Deep teal. *"Answered & grounded."* Replaces emerald. |
| `--state-flagged` | `34 70% 45%` | Burnt amber. *"Needs review."* |
| `--state-refused` | `220 12% 38%` | Ink-gray. *"Refused — out of scope."* Quieter than red. |
| `--state-fallback` | `260 25% 45%` | Muted plum. *"Safe offline path used."* |
| `--state-destructive` | `0 65% 42%` | Vermillion. *"Override / escalate."* |

**Chart palette (5 colors that don't traffic-light):**

| Token | Value | Note |
|---|---|---|
| `--chart-1` | `218 58% 20%` | Primary ink-navy |
| `--chart-2` | `175 35% 30%` | Deep teal |
| `--chart-3` | `34 70% 45%` | Burnt amber |
| `--chart-4` | `260 25% 45%` | Muted plum |
| `--chart-5` | `220 12% 55%` | Slate |

**Dark theme:**

| Token | New value | Old value |
|---|---|---|
| `--background` | `220 28% 7%` | `222 47% 6%` |
| `--foreground` | `36 20% 94%` | `210 40% 96%` |
| `--card` | `220 24% 10%` | `222 40% 8%` |
| `--primary` | `218 70% 78%` | `210 80% 72%` |
| `--primary-foreground` | `220 28% 7%` | `222 47% 8%` |
| `--secondary` | `220 18% 16%` | `217 28% 16%` |
| `--muted` | `220 18% 16%` | `217 28% 16%` |
| `--muted-foreground` | `36 12% 70%` | `215 20% 68%` |
| `--accent` | `220 18% 18%` | `164 48% 14%` |
| `--accent-foreground` | `218 70% 78%` | `156 70% 76%` |
| `--destructive` | `0 58% 52%` | `0 72.2% 50.6%` |
| `--border` | `220 18% 18%` | `217 24% 18%` |
| `--ring` | `218 70% 78%` | `210 80% 72%` |

### 7.3 Use rules

- **Primary (ink-navy)** is the only "bold" color on the page. ≤10% of pixels.
- **Parchment background + white cards** is the canvas. ~70%.
- **All semantic states use the `--state-*` family**, not primary. We stop using primary navy for "everything that's a button or a number."
- **Destructive is reserved** for irreversible actions (delete, force-override). It is **not** the color of a flagged decision.
- **One accent at a time.** A row never shows amber and teal and plum simultaneously.

### 7.4 Typography

Stay on the existing sans (default Inter/Geist from Next). Add:
- A **mono** for IDs, hashes, timestamps, code (`JetBrains Mono` or `IBM Plex Mono`). We already lean on `font-mono` in spots; commit to it.
- An optional **serif** display for marketing-site headlines only (`Source Serif Pro` or `Newsreader`). Reinforces the "research note" aesthetic on the marketing site. App stays sans.

### 7.5 Density and radius

- `--radius` stays `0.75rem`. shadcn-correct.
- **Density increase** on the workbench: default row height for tables drops from `py-3` to `py-2`. Compliance pages should feel closer to Linear/Notion than Stripe Dashboard. Marketing site keeps its current breathing room.
- Card shadows become **flatter** (`shadow-sm` only). Audit products shouldn't look bouncy.

---

## 8. Component patterns (the parts that get reused)

### 8.1 The assistant message

A single composable bubble used in `/app/clients/[id]/ask` and `/app/threads/[id]`. Replaces the current "Decision card."

```
GlassBox · 09:14
┌──────────────────────────────────────────────────┐
│ No — IPS §4.1 caps single positions at 25%[1].   │
│ Current AUM €18M → max position €4.5M.[2]        │
│ …                                                │
│ ─────────────────────────────────────────────    │
│ Grounded · 3 sources · 320 ms · Audit #a91b      │  ← one-line meta band, click to expand
└──────────────────────────────────────────────────┘
[ Escalate ] [ Mark resolved ] [ Copy ] [ Replay ]
```

Variants by outcome (all the same shape, only the meta band + left-border color change):

- **Answered/Grounded** → teal left border, "Grounded" badge.
- **Flagged** → amber left border, "Flagged for review" badge, `Escalate` is primary action.
- **Refused** → ink-gray left border, "Refused — out of scope" badge, `Escalate` is primary action.
- **Fallback** → plum left border, "Safe offline response" badge, "hosted model unavailable" tooltip.

### 8.2 Inline citation

`[1]` in body text → on hover, `Popover` with the source snippet + title + page. On click, the right-hand `Evidence` panel scrolls to that source. Numbered consistently with the order they appear in the answer.

### 8.3 Refusal language rules

Replace current copy:

| Before | After |
|---|---|
| "The system did not have enough approved evidence to answer safely." | "Out of scope. The approved document set does not cover cross-border tax for German residents. Escalate to Compliance · DACH desk." |
| "Escalated or refused" (Alert title) | "Refused — out of scope" (meta line, not an alert) |
| "REFUSED" badge | "Refused" (lowercase, neutral weight) |

No first-person model voice. No anthropomorphism. Specific, actionable disclaimers.

### 8.4 Trust expander

Click the meta band → expands inline (not a modal) showing:

```
Grounding score        72%     [ what is this? → ]
Determinism (24h avg)  91%
Claims kept            4 of 5
Claim discarded        "Tax-loss harvest applies cross-border" → no source matched
Sources retrieved      5  (IPS §4.1, IPS §4.3, Factsheet NVDA, Factsheet AAPL, Holdings 2024-11)
Model                  llama-3.3-70b · temperature 0.1 · seed 42
Latency                320 ms
Audit ID               a91b6d8e-…  [ open replay → ]
```

This is the "show your work" surface. Not in a tab — in an expander.

### 8.5 Empty states

Every empty state has a specific next action and copy that names a specific document or client. No "Click here to begin."

- Threads empty → *"Pick a client to start. Each conversation is logged against that client's IPS version."*
- Review queue empty → *"Nothing in your queue. 12 decisions were auto-approved today; see [/app/audit](/app/audit)."*
- Audit search no results → *"No decisions match. Loosen filters, or try a wider date range."*

---

## 9. What we explicitly are NOT building in v1

To keep scope honest:

- **Real auth.** Stub a role switcher in the header for now.
- **Multi-tenant.** Single org, single workspace. Add `org_id` to the DB schema (cheap), but no admin UI for tenant management.
- **Real upload of customer IPS PDFs.** That's the marketing-site CTA but we wire it later.
- **Slack / Teams / email integration.** Out of scope.
- **Mobile.** Workbench is desktop-first. Marketing site is responsive.
- **Realtime collaboration.** Two reviewers on the same flag at the same time is a v2 concern.
- **Pricing page actually charging.** Marketing stub only.

---

## 10. Migration map — file-by-file

What changes on the codebase side:

### Frontend additions
- `app/(marketing)/layout.tsx` + `app/(marketing)/page.tsx` + `app/(marketing)/pricing/page.tsx` + `app/(marketing)/contact/page.tsx`
- `app/(app)/layout.tsx` — new app shell (sidebar).
- `app/(app)/home/page.tsx`
- `app/(app)/clients/page.tsx`, `app/(app)/clients/[id]/page.tsx`, `app/(app)/clients/[id]/ask/page.tsx`
- `app/(app)/threads/page.tsx`, `app/(app)/threads/[id]/page.tsx`
- `app/(app)/review/page.tsx` (replaces today's flat list), `app/(app)/review/[id]/page.tsx`
- `app/(app)/audit/page.tsx` (fix the 404), keep `app/(app)/audit/[id]/page.tsx`
- `app/(app)/library/page.tsx`, `app/(app)/library/[doc]/page.tsx`
- `app/(app)/insights/page.tsx` (rename of dashboard)
- `app/(app)/admin/{models,users,api-keys}/page.tsx`
- `app/login/page.tsx` — auth stub.

### Frontend deletions / heavy edits
- `app/page.tsx` (current) → split: marketing pieces move to `(marketing)/page.tsx`, the chat workspace moves to `(app)/clients/[id]/ask/page.tsx`.
- `app/dashboard/` → moves to `app/(app)/insights/`.
- `app/decisions/` → folds into `app/(app)/audit/`.
- `app/review/` → rewrites as queue grid.
- `components/AppShell.tsx` → rewrites as left-sidebar shell.
- `components/ChatPanel.tsx` → replaced by:
  - `components/conversation/Conversation.tsx`
  - `components/conversation/AssistantMessage.tsx`
  - `components/conversation/InlineCitation.tsx`
  - `components/conversation/EvidencePanel.tsx`
  - `components/conversation/Composer.tsx`
  - `components/conversation/TrustExpander.tsx`
- `components/TrustBadges.tsx` → removed (folded into `TrustExpander`).
- `components/SearchableAccordion.tsx` (FAQ) → moves to marketing site only.
- `app/globals.css` → palette rewrite (Section 7).

### Backend
- No API changes required for v1 visual + IA revamp. `/ask`, `/audit`, `/audit/{id}`, `/determinism`, `/metrics/summary`, `/llm/status` all stay.
- Add later: `/review/{id}/decision` (POST reviewer outcome → labels for grounding scorer), `/clients`, `/clients/{id}`, `/threads`, `/threads/{id}`, `/audit/export?format=pdf|csv`.

---

## 11. Build order (slices, smallest-first)

Each slice is shippable on its own and visibly different from the slice before. We do not start the next slice until the previous one is approved.

### Slice 0 — palette + sidebar shell (1–2 days)
- Rewrite `globals.css` tokens (Section 7).
- New `AppShell` with left sidebar nav, role switcher in header.
- Move current pages under `/app/*` route group. Marketing copy off `/`.
- Nothing else changes functionally. **The whole product instantly looks different.**

### Slice 1 — marketing site (1 day)
- `/`, `/pricing`, `/contact` with hero + three proof points + one CTA.
- This unblocks "stop putting marketing inside the app."

### Slice 2 — clients + sticky context (2 days)
- `Clients` list + `Client detail` page.
- Sticky context bar (client name, IPS version, open flags).
- Existing `/ask` becomes `/app/clients/[id]/ask` (chat scoped to a client).

### Slice 3 — conversation surface (3–4 days)
- Replace `ChatPanel` with the new `Conversation` + `AssistantMessage` + `EvidencePanel` + inline `[1]` citations + `TrustExpander`.
- Threads stored per client (light DB addition).
- **This is the slice that visibly stops looking like a college project.**

### Slice 4 — review queue grid (2–3 days)
- New `/app/review` grid with filters, claim/decide/SLA.
- Reviewer outcome submission feeds back to the grounding scorer dataset.

### Slice 5 — audit log + export (2 days)
- Real `/app/audit` index with filters and CSV export.
- PDF binder export (server-side, simple).

### Slice 6 — insights with targets + sparklines (1–2 days)
- Every metric tile gets a target threshold, 7-day sparkline, drill-down.
- Determinism becomes a nightly job, not a user button.

### Slice 7 — admin + auth stub (1 day)
- `/app/admin/models` (move BYO key + temperature + model selection here).
- `/login` stub with hardcoded `advisor` / `compliance` / `admin` roles.

**Total: ~13–18 working days** for the full revamp. Slices 0+3 alone (≈5 days) cover the user's stated complaint ("looks like a college project").

---

## 12. Definition of done (this revamp)

- [ ] App and marketing live in separate route groups; no marketing copy on any `/app/*` page.
- [ ] Sidebar IA matches Section 3.3.
- [ ] New palette tokens (Section 7) applied; emerald removed from app chrome.
- [ ] Advisor view is a threaded conversation with inline citations and evidence panel.
- [ ] Compliance review is a filterable grid with claim/decide/SLA.
- [ ] `/app/audit` exists (no 404), supports filters + CSV + PDF binder export.
- [ ] Determinism is no longer a button advisors click; it's a metric on Insights.
- [ ] Every metric tile has a target and a sparkline.
- [ ] No first-person AI voice in any user-facing copy; no "REFUSED" alert.
- [ ] All scenario cards / "operating contract" pills / inline FAQ removed from the app.

---

## 13. Open questions for the owner before we start

1. **Buyer focus** — confirm compliance officer is the primary buyer (the whole IA pivots on this).
2. **Marketing CTA** — *"Try with your IPS"* upload demo or *"Book a 20-min walkthrough"* call booking?
3. **Palette name lock** — *"Ink + parchment"* as proposed, or do you want a more neutral all-slate palette (Linear-style) with no warm cast?
4. **Multi-tenancy now or later** — adding `org_id` to the schema during this revamp is cheap; deferring it later is annoying. Recommendation: do it now.
5. **Auth stub level** — three hardcoded roles (`advisor`, `compliance`, `admin`) toggleable from the header, or real Auth.js with a dev provider?

Answers determine: (a) what we cut from v1, (b) the order of slices, (c) whether the marketing site needs a working demo CTA on day 1.
