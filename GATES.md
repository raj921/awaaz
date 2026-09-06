# Gates: Modal training pipeline + memory prototype (A1 smoke + serving)

OWNS: research/memory/**, research/training/**, results/memory_eval.json, results/serving_latency.json, GATES.md

Scope: memory prototype evaluated against scenarios.jsonl; Qwen3-1.7B QLoRA SFT training app and serving function for Modal (H100); real smoke-training adapter artifact; warm serving under the 200 ms budget; Modal account state documented.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=8e443f30143717a1d1be757670680ebcfc18e979cbdfcd38bdd993159aa4736f; output-bytes=428

- [x] G2: memory prototype honors explicit forgetting and retrieves active facts, proven with negative controls over scenarios.jsonl
  CHECK: python3 research/memory/run_eval.py
  EXPECT: MEMORY_EVAL_PASS
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=c4260602b798b7fd8bd9e38d9f45d9c1f7b415e99041998653dd1bed9fa353c5; output-bytes=17

- [x] G3: training and serving scripts are structurally valid Modal apps (QLoRA config, H100 request, adapter volume, streaming endpoint) without needing a GPU locally
  CHECK: .venv/bin/python research/training/validate_scripts.py
  EXPECT: TRAIN_SCRIPTS_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=3ef65fb6b4b361edba1cd836de67e905da7e521f162fbf35f469b0325a06452e; output-bytes=17

- [x] G4: real Modal smoke-training run produced a downloadable QLoRA adapter artifact that passes structural sanity
  CHECK: .venv/bin/python research/training/check_adapter.py
  EXPECT: ADAPTER_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=e1444bb13c33c70f2187b4f86e7f09ef1692dd5f5eea1da9b7572fd70df15cf4; output-bytes=11

- [x] G5: deployed serving endpoint answers warm with server-side first-token latency under the 200 ms budget, returned by the endpoint itself
  CHECK: .venv/bin/python research/training/check_serving.py
  EXPECT: SERVE_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=45654009189409d374a501ccc29550372c9c216ec7d1f607b70b0dc44e6dea9d; output-bytes=61

- [x] G6: Modal account and app state (raj315920/main) documented from browser inspection
  EVIDENCE: 2026-09-02 modal.com/apps/raj315920/main — workspace raj315920/main, plan Starter, credits $106.07, 0 live apps, 0 stopped apps; recorded in NOTES.md Part 13

- [x] G7: smoke-training run evidence (GPU class, steps, final train loss) recorded from live Modal logs
  EVIDENCE: 2026-09-02 run ap-fV2PlTaAhl7yUScceN35yP — GPU H100 (run page; download_base CPU), TRAIN_DATA examples=800, trainable 6,594,560/1,727,169,536 (0.38%), TRAIN_DONE steps=30 final_loss=4.7277; credits $106.07→$104.45; details in NOTES.md Part 13
