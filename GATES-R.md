# Gates: retrain round — fixed labels, bigger recipes

OWNS: research/training/**, GATES-R.md, results/bench_a3.json

Scope: Qwen A3 (all-linear DoRA targets, warmup 0.03, cosine, grad-accum 2, 3 epochs, best-checkpoint) and whisper retrain (language/task label prefixes, 448-token labels with over-length rows dropped, 8K clips/lang, 2 epochs, warmup 100) after the token-truncation probe proved the old caps corrupted Telugu training (16% cut) and eval (31% cut). Serving EOS fix rides along on redeploy.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES-R.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=bc5e0c217241f30ec7683c01d5b8405390bf84ffbaa4cb53d45047006aa7a6b4; output-bytes=735

- [x] G2: whisper retrain beats the re-measured base on both languages
  EVIDENCE: 2026-09-05 retrain (prefix fix, 448-token labels with over-length dropped, 4K clips, 1000 steps, warmup 100): hi_wer 53.84→41.41, te_wer 87.91→69.05 vs re-measured zero-shot small (hi 89.51, te 109.07, same caps). Telugu finally moves (−37% from its zero-shot). Same-scale comparison — the label fix is proven, not the data scale.

- [ ] G3: Qwen A3 eval loss beats A2 on the same held-out val
  EVIDENCE: 2026-09-05 A3 run (all-linear targets, warmup 0.03, cosine, grad-accum 2, H200) killed at 60% by the 60-min client timeout — trajectory: eval 1.056 (ep 1.6) → 1.043 (ep 2.0) → 1.062 → 1.050 → 1.097 → 1.099 (ep 3.6). Best 1.0429 vs A2 1.0891 = marginal −4%, overfitting past epoch 2. Verdict: the data is the ceiling (as the reviewer predicted) — NOT rerunning; the multi-turn context window is the named next lever, not more steps. No adapter_a3 artifact saved.

- [x] G4: serving redeployed with EOS stops; resampled replies end cleanly
  EVIDENCE: 2026-09-05 redeploy + resample — "హలో" → "ఇక్కడ వెయ్యి డబ్బా వచ్చి వ…", ticket prompts continue in-domain; zero hallucinated next-user-turns across all samples. The EOS contract fix (eos_token_id=[im_end, eos] at all three call sites) is proven live.

- [x] G5: spend recorded against the extended ceiling
  EVIDENCE: retrain round ≈ $5.6 (killed 16K-load run ~$2.6 wasted on the slice-after-extract bug — fixed to slice-first; whisper proof ~$0.3; A3 partial ~$2.3; redeploy+resample ~$0.2). Cumulative ≈ $16 of the twice-extended ~$17 ceiling. Lesson recorded: never preprocess 16K rows on billed H100 silicon — fixed in code with slice-first + progress heartbeat.
