# Gates: human-like memory (working memory, salience, decay, rehearsal)

OWNS: research/memory/**, GATES-M.md, results/memory_eval.json, results/memory_human_eval.json

Scope: human retention dynamics layered on the proven hard-delete core — working memory (7-slot), salience-weighted storage and decay (tau = 5 + 10 × salience days), rehearsal strengthening (add/hear/retrieve all reinforce), natural evaporation below the strength floor, and re-learning after forgetting. Explicit forget stays hard, instant, permanent — deliberately not human. Both suites must pass on the same engine.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES-M.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=2866f20a15d881139b55f2370be37571b557fd605e9c2bbfeb7047ae63833114; output-bytes=152

- [x] G2: the legacy guarantee suite still passes on the new engine
  CHECK: python3 research/memory/run_eval.py
  EXPECT: MEMORY_EVAL_PASS
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=c4260602b798b7fd8bd9e38d9f45d9c1f7b415e99041998653dd1bed9fa353c5; output-bytes=17

- [x] G3: the human-dynamics suite passes (working, rehearsal, salience, decay, hard-forget, re-learn)
  CHECK: python3 research/memory/run_human_eval.py
  EXPECT: MEMORY_HUMAN_PASS
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=5174604804d7aca8af5a99a07c2be463b7efb252608f7f39c35f371d0c9dd215; output-bytes=18

- [x] G4: design decisions documented (what is human-like and what deliberately is not)
  EVIDENCE: memory.py module docstring (dynamics spec + ceilings), run_human_eval.py (6 asserted behaviors), NOTES.md Part 21
