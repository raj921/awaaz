# Gates: memory v2 port + LoCoMo harness

OWNS: research/memory/memory_v2.py, research/memory/eval_locomo.py, GATES-M2.md

Scope: port the proposed store with three verified fixes (compile, raw-token
conflict, hi/te STOP+SALIENT), land the harness verbatim, prove it on synthetic
+ real LoCoMo retrieval. LLM paths (extract/resolve/answer/judge) untested by
construction — no key, no calls, no claims.

- [x] G1: memory_v2 compiles clean
  EVIDENCE: 2026-09-05 py_compile research/memory/memory_v2.py OK (draft failed with SyntaxError L145, fixed: `self.memories: dict = {}`).

- [x] G2: harness --synthetic prints the specified table
  EVIDENCE: 2026-09-05 single/multi/temporal evidence_recall 1.0, latency p50 0.01ms. Store, date parse, provenance, metrics wired.

- [x] G3: our oracle asserts hold on the port
  EVIDENCE: 2026-09-05 battery: conflict newest_only True (raw-token Jaccard fix), hear-add-forget-context_block zero leak, decay/salience/rehearsal/relearn True, as_of temporal correct.

- [x] G4: native-script storage round-trips (regex fix)
  EVIDENCE: 2026-09-05 normalize('నా పేరు రాజు') and 'मेरा नाम राज है' exact; romanized unchanged. Caught our own near-miss: first patch dropped the `+` and split romanized per-character — fixed and re-verified all three scripts.

- [x] G5: real LoCoMo retrieval-only number recorded, latency in budget
  EVIDENCE: 2026-09-05 10 convs, 1540 q: single 0.575 / multi 0.169 / temporal 0.526 / open 0.224 / ALL 0.469; p95 1.9ms (< 50ms). results/locomo_eval.json. Hybrid probe (MiniLM, 2 samples): 0.411 vs lexical 0.478 same samples — dense currently HURTS; fusion needs work, reported not hidden.
