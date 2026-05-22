# GlassBox — An Auditable Wealth-Advisory AI Agent

> An AI agent that answers financial advisory & compliance questions **only from cited sources**, **refuses to guess**, **logs every decision for audit**, and **measures its own trustworthiness on a live dashboard.**
>
> Built for the real problem banks (like UBS) have in 2026: not "make a smarter AI" but "make an AI we can actually trust, defend, and deploy."

---

## 0. TL;DR — The Big Decisions (read this first)

| Question | Decision | Why |
|---|---|---|
| Train our own LLM from scratch? | **No** | Costs millions, pointless for this. |
| Fine-tune an open LLM on finance data? | **No** | Bakes knowledge into weights → encourages hallucination → kills the whole "grounded only" thesis. |
| What runs the language reasoning? | **Free open-source model via a free inference host** (Groq / OpenRouter free tier) | Free, public, no per-visitor cost, lets us control temperature/seed for the determinism experiments. |
| Do we train ANY of our own models? | **Yes — small ML models for the trust layer** (grounding scorer, refusal router, fallback classifier) | Cheap to train, runs free, makes the project genuinely *ours*, mirrors skills already on the resume. |
| Where does it get hosted? | **AWS** (using the $150 credits) — app, audit DB, document storage, public URL | Turns paper AWS certs into a real deployed project. |
| Who pays when strangers use the demo? | **Nobody** | Free model host + AWS free/cheap tiers + rate limiting. |

**One-line pitch:** Everyone is building AI agents that give finance answers; almost nobody is building the trust-and-audit layer that makes those answers safe to use. GlassBox is that missing layer.

## Local Implementation Status

This folder now contains a runnable local implementation:

- FastAPI backend with retrieval, grounded answering, verification, refusal, fallback, audit replay, metrics, determinism, rate limiting, and trained scikit-learn trust models.
- Synthetic IPS/factsheet/regulation corpus plus an ingestible local vector store.
- Next.js frontend with advisor chat, cited sources, trust badges, dashboard, and audit replay pages.
- `README-LATER.md` tracks cloud, real hosted-model, and hardening work that needs external services.

Run locally:

```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm run dev
```

Then open `http://localhost:3000`.

---

## 1. The Problem (why this matters)

A financial advisor asks: *"Can my client move $2M into this single tech stock?"*
Answering correctly means checking: the client's contract rules, their risk profile, position limits, cross-border/tax triggers. Advisors do this manually and miss things — and misses cost banks millions in fines.

The obvious fix is an AI agent. But banks won't deploy one because of three unsolved problems:
1. **Hallucination** — it invents rules that don't exist.
2. **Inconsistency** — same question, different answer on different runs.
3. **No audit trail** — when a regulator asks "why did it say that?", there's no defensible record.

**GlassBox attacks all three directly.** That's the novelty.

---

## 2. What GlassBox Does — The Four Pillars

1. **Grounded-only answers** — every claim must point to a real document in the corpus. Unsupported sentences are stripped before the user sees them.
2. **Refuses to guess** — if the documents don't cover it, it says "cannot answer, escalate to human" instead of making something up. In finance, "I don't know" is a feature.
3. **Self-verification** — drafts an answer, then a second pass interrogates each claim against its source and discards anything that fails (Chain-of-Verification).
4. **Measures its own trust** — runs questions multiple times to score consistency (determinism), tracks hallucination rate, refusal rate, and audit completeness on a **live dashboard**. Plus every decision is **logged and replayable**.

---

## 3. System Architecture (the components we build)

```
                    ┌─────────────────────────────────────────┐
                    │            FRONTEND (Next.js)             │
                    │  Advisor chat UI + Governance Dashboard   │
                    └───────────────────┬───────────────────────┘
                                        │  (REST / WebSocket)
                    ┌───────────────────▼───────────────────────┐
                    │           BACKEND API (FastAPI)            │
                    │            "Orchestrator"                  │
                    └───┬──────┬───────┬────────┬────────┬───────┘
                        │      │       │        │        │
            ┌───────────▼┐ ┌───▼────┐ ┌▼──────┐ ┌▼──────┐ ┌▼─────────┐
            │ RETRIEVAL  │ │ANSWER  │ │VERIFY │ │TRUST  │ │PROVENANCE│
            │  (RAG)     │ │ AGENT  │ │ AGENT │ │METRICS│ │  LOGGER  │
            └─────┬──────┘ └───┬────┘ └───┬───┘ └───┬───┘ └────┬─────┘
                  │            │          │         │          │
            ┌─────▼─────┐  ┌───▼──────────▼───┐ ┌───▼───┐  ┌───▼──────┐
            │ Vector DB │  │  FREE OPEN LLM   │ │ OUR   │  │  Audit   │
            │  + S3     │  │ (Groq/OpenRouter)│ │ SMALL │  │   DB     │
            │  corpus   │  │                  │ │MODELS │  │ (Postgres)│
            └───────────┘  └──────────────────┘ └───────┘  └──────────┘
```

### Component-by-component (everything we make)

**A. Document Corpus + S3 storage**
The knowledge GlassBox is allowed to use. We assemble:
- Synthetic client IPS / mandate documents (the rules: "no single position > 25%", exclusion lists, liquidity floors).
- Public fund / ETF factsheets (risk level, asset class, region).
- Public regulatory text snippets (suitability, cross-border basics).
Stored in S3, indexed into the vector DB.

**B. Retrieval layer (RAG)**
Takes the advisor's question, finds the most relevant document chunks. Built with a vector database (Chroma/FAISS/pgvector) + an embedding model (free, open-source).

**C. Answer Agent**
The free open LLM drafts an answer **using only the retrieved chunks**, instructed to cite each claim. Low temperature for stability.

**D. Verify Agent (Chain-of-Verification)**
Breaks the draft into atomic claims → checks each against its cited source → discards/flags unsupported claims → returns the validated answer or a refusal.

**E. Trust Metrics engine (uses OUR trained models)**
- **Grounding/Hallucination scorer** (our model): scores how well each answer is supported by sources.
- **Refusal router** (our model): decides answerable vs. must-escalate.
- **Determinism harness**: runs each query N times, measures answer-drift, outputs a determinism score per query type.
- **Fallback classifier** (our model): if the LLM host is down/rate-limited, a small trained model returns a safe structured response (same idea as the AutoScaler fallback).

**F. Provenance Logger + Audit DB**
Every interaction logged: question, retrieved sources, claims kept/discarded, final answer or refusal, which rule applied, timestamps. Stored in Postgres (RDS). Replayable — an auditor can reconstruct exactly what the agent "knew" at decision time.

**G. Governance Dashboard (frontend)**
Live view of: hallucination rate, refusal/escalation frequency, determinism score, audit-trail completeness, per-query traces. This is the "show, don't tell" trust display.

---

## 4. Models — Exactly What We Use vs. Train

### Use (don't train): the language brain
- **Free open-source LLM** via a free inference host (start: **Groq** with Llama 3.3 70B, or **OpenRouter** free models).
- Optional **"bring your own key"** toggle so power users can run a stronger model.
- **Not fine-tuned** — kept grounded strictly on retrieved docs.

### Train ourselves (this is OUR ML work): the trust layer
| Model | Job | How trained | Compute |
|---|---|---|---|
| Grounding/Hallucination scorer | Score if answer is supported by sources | scikit-learn classifier on labeled good/bad answer pairs | CPU, free (Kaggle/Colab) |
| Refusal router | Answerable vs escalate-to-human | small classifier on labeled questions | CPU, free |
| Fallback classifier | Safe structured reply when LLM host fails | Random Forest on logged incidents | CPU, free |

> These run free, are deployable on AWS without a GPU, and make the project demonstrably yours — directly echoing the IIT metric-design work and the AutoScaler fallback classifier already on the resume.

---

## 5. Tech Stack

| Layer | Tool | Note |
|---|---|---|
| Frontend | Next.js + React + TypeScript + Tailwind + Recharts | Already known from Kalakraft & AutoScaler |
| Backend | Python + FastAPI | Already known from IIT/AutoScaler |
| LLM | Free open model (Groq/OpenRouter) | No paid API |
| Embeddings | Open-source (e.g. sentence-transformers / bge) | Free |
| Vector DB | Chroma / FAISS / pgvector | Free, lightweight |
| Our ML models | scikit-learn | CPU only |
| Audit DB | PostgreSQL (AWS RDS) | Mirrors AutoScaler's TimescaleDB use |
| Corpus storage | AWS S3 | Pennies |
| Hosting | AWS (EC2/Lambda + API Gateway) | Uses the $150 credits |
| Access control | IAM / RBAC | Already known; bank-relevant |
| Public-demo safety | Rate limiting + request queue | Keeps it free for visitors |

---

## 6. AWS Plan ($150 credits — spend it right)

**Use credits for:** EC2/Lambda hosting, RDS Postgres (audit logs), S3 (corpus), API Gateway, IAM. Comfortably runs a public demo for months.

**Do NOT use credits for:** GPU instances for the LLM (free external host instead) or long idle instances.

**Guardrails (do this on day one):**
- Set billing alarms at **$20 / $50 / $100**.
- Never leave a GPU/large instance running idle.
- Train the small models on **free Kaggle/Colab GPUs/CPU**, only *deploy* on AWS.

**Resume payoff:** turns the existing AWS Cloud Practitioner + AWS ML Specialty certs into a *deployed* project — IAM/RBAC, RDS audit store, S3 corpus, public URL. "I can ship to a regulated cloud environment."

---

## 7. Build Roadmap (phased — adjust to your time budget)

> Lean demo ≈ 2–3 weeks (Phases 0–4). Full version ≈ 5–6 weeks (all phases).

### Phase 0 — Setup (Days 1–2)
- Repo, README (this file), env config.
- Get free LLM host key (Groq/OpenRouter). Test a basic call.
- AWS account + billing alarms. S3 bucket created.

### Phase 1 — Corpus + Retrieval (Days 3–6)
- Assemble synthetic IPS docs + public factsheets + regulatory snippets.
- Chunk, embed, load into vector DB.
- Build retrieval endpoint: question in → relevant chunks out.
- **Milestone:** ask a question, see the right documents come back.

### Phase 2 — Answer Agent + grounding (Days 7–10)
- LLM drafts answers using only retrieved chunks, with citations.
- Strip any claim lacking a source.
- **Milestone:** every answer shows highlighted source citations.

### Phase 3 — Verify Agent + Refusal (Days 11–14)
- Chain-of-Verification pass (claim-by-claim check).
- Refusal/escalation when sources don't cover the question.
- **Milestone:** ask an out-of-scope question → it refuses instead of inventing.

### Phase 4 — Provenance Logger + basic dashboard (Days 15–18)
- Log every decision to Postgres; build replay view.
- Minimal dashboard: show traces, refusals.
- **Milestone:** click any past answer and replay its full decision trail.
- *(Lean demo ends here — already a strong portfolio piece.)*

### Phase 5 — Trust models (OUR ML) (Days 19–25)
- Label a small dataset of grounded/ungrounded answers.
- Train grounding scorer + refusal router + fallback classifier.
- Plug into the pipeline.
- **Milestone:** dashboard shows a live hallucination rate from our own model.

### Phase 6 — Determinism harness (Days 26–30)
- Run each query N times; measure answer-drift; score per query type.
- Optional: compare a frontier model vs an open model (reproduces the known research finding that no model is both perfectly deterministic and accurate).
- **Milestone:** determinism score on the dashboard + a short write-up of the comparison.

### Phase 7 — Deploy + public-demo hardening (Days 31–35)
- Deploy on AWS (app + RDS + S3 + IAM).
- Rate limiting + request queue + graceful "busy" handling for free public access.
- Optional BYO-key toggle.
- **Milestone:** a public URL anyone can try, costing you nothing.

### Phase 8 — Polish (Days 36–42, optional)
- README diagrams, demo video/GIF, screenshots.
- Short "design decisions" doc (why no fine-tuning, why grounded-only, why open model + AWS split).
- Clean architecture diagram for interviews.

---

## 8. Definition of Done (checklist)

- [ ] Answers cite real sources; unsupported claims removed.
- [ ] Refuses/escalates on out-of-scope questions.
- [ ] Chain-of-Verification pass implemented.
- [ ] Every decision logged + replayable in audit DB.
- [ ] Our trained grounding scorer + refusal router + fallback classifier live.
- [ ] Determinism harness produces per-query scores.
- [ ] Live governance dashboard (hallucination / refusal / determinism / audit completeness).
- [ ] Deployed on AWS with a public URL, free to visitors, rate-limited.
- [ ] README + design-decisions doc + demo media.

---

## 9. Resume Bullets (problem-and-impact first)

> **GlassBox — Auditable Wealth-Advisory AI Agent**
> - Built a multi-agent advisory system that answers compliance/suitability questions **only from cited sources**, implementing retrieval-grounding, Chain-of-Verification, and automatic refusal on ungrounded claims (reduced ungrounded responses to <X%).
> - Trained custom grounding, refusal-routing, and fallback classifiers (scikit-learn) to guard the trust boundary and provide an LLM-failure fallback with zero external dependency.
> - Designed a **determinism harness** measuring answer-drift across repeated runs, surfacing the consistency/accuracy trade-off that current financial-AI research treats as an open problem.
> - Generated **replayable decision traces** and a live governance dashboard (hallucination, refusal, determinism, audit-completeness), addressing the auditability gap regulators require under the EU AI Act.
> - Deployed on **AWS** (EC2/Lambda, RDS, S3, IAM/RBAC) with rate-limited public access on a free open-source model — no per-user cost.

---

## 10. Interview Talking Points (defend the choices)

- **"Why not fine-tune a finance model?"** → Fine-tuning pushes the model to answer from baked-in weights, undermining auditability. A compliance-grade system needs answers grounded strictly in retrieved, citable sources, with separate trained models guarding the trust boundary.
- **"Why an open model not a paid API?"** → Cost-free public access + full control of temperature/seed for the determinism experiments; mirrors how banks avoid leaking data to third parties.
- **"How does this relate to UBS?"** → It sits *on top of* an assistant like UBS Red rather than competing with it, and maps directly to UBS's AI governance principles (autonomy, harm-prevention, transparency) and their agentic-AI mandate.
- **"What's genuinely new here?"** → The trust harness — measuring and displaying grounding + determinism live — is the part the industry openly admits is missing.

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Free LLM host rate limits | Request queue + "busy" handling + BYO-key option |
| AWS credits burn | Billing alarms, no idle GPU, train models off-AWS |
| Scope creep | Lean demo (Phases 0–4) is already shippable; rest is bonus |
| Weak grounding on small models | Tight corpus, strong retrieval, verification pass |
| Synthetic data looks fake | Base IPS rules on real public mandate templates; use real public factsheets |

---

## 12. Glossary

- **RAG** — Retrieval-Augmented Generation; answer from fetched documents, not memory.
- **Grounding** — every claim tied to a real source.
- **Chain-of-Verification (CoVe)** — model checks its own draft claim-by-claim before answering.
- **Determinism** — does the same input give the same output across runs.
- **Provenance / decision trace** — replayable record of what the agent used and why.
- **IPS** — Investment Policy Statement; a client's rulebook (limits, exclusions, liquidity).
