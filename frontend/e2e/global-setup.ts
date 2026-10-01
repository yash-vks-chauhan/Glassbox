import { runPython } from "./helpers";

/** Seed the e2e accounts once, before any worker starts, so parallel spec
 * files don't race to insert the same users. Workers read the result from
 * E2E_SEED (see seedUsers). */
export default function globalSetup() {
  process.env.E2E_SEED = runPython(["scripts/seed_phase_f_e2e.py"]);
}
