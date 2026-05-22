# START HERE — How to Use This Pack with Codex

You have everything needed to build GlassBox. Here's the order and the workflow.

## Files in this pack
1. **README.md** — the project: what it is, why, full roadmap, resume bullets. Read this yourself first.
2. **BUILD-SPEC.md** — all frozen decisions: stack, file tree, schemas, API contracts, model specs, acceptance tests. This is the shared reference Codex relies on. Don't paste it as a task.
3. **tasks/** — the actual Codex prompts, in order:
   - `phase-0-1-setup-retrieval.md`
   - `phase-2-3-answer-verify-refusal.md`
   - `phase-4-5-provenance-trustmodels.md`
   - `phase-6-7-determinism-deploy.md`

## The workflow (important — don't skip)
1. Put `README.md` and `BUILD-SPEC.md` in your repo root. Make sure Codex can see/read them.
2. Open the first task file. Paste **one TASK block** into Codex.
3. Let it finish. Run the acceptance test it names. Read its report.
4. If it passes → `git commit`. If not → tell Codex exactly what failed, let it fix, re-test.
5. Move to the next TASK block. Repeat.

## Why one task at a time
Codex (like all coding agents) does far better on small, bounded tasks with a clear "done" check than on "build my whole app." Feeding it phase by phase keeps it accurate, keeps you in control, and means you always have a working, committed state to fall back to.

## Stopping points (each is a usable milestone)
- After **Phase 4** → you have a complete, demoable system (grounded answers, refusal, full audit replay). This alone is a strong portfolio piece.
- After **Phase 6** → you have the standout novelty (trust models + determinism harness).
- After **Phase 7** → it's publicly hosted on AWS, free for visitors.

## Reality check
Even with this spec, expect a build-test-fix loop, not one-shot magic. Your job is to direct and debug the agent. The spec makes that loop short. Budget a few evenings per phase.

## When you're done
- Fill the real measured numbers into the resume bullets (README §9).
- Write `docs/design-decisions.md` — those are your interview answers (README §10).
