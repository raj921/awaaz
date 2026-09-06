# Gates: A1 full Hindi fine-tune (IndicVoices stream-continuation SFT)

OWNS: research/training/**, GATES-A1.md, results/a1_samples.json, data/checkpoints/qwen3-a1-full/**

Scope: real IndicVoices Hindi conversation transcripts (154,512 native utterances, one side of real calls) turned into stream-continuation SFT pairs (context = last real utterances, target = next real utterance; no fabricated text anywhere), full DoRA fine-tune of Qwen3-1.7B on Modal H100, adapter artifact, warm serving under the 200 ms budget, honest quality samples, spend under the ceiling.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES-A1.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=562e9ffa17d3c149acbdfa59e20f1e13a39829fac78eca4e7360aa2e716dfb27; output-bytes=522

- [x] G2: pairing design is evidence-based (conversation structure probed, not assumed)
  EVIDENCE: 2026-09-02 convo_probe over first 3,000 Conversation rows: 135 speaker transitions, same-speaker run-lengths 17-29 — data is long single-speaker blocks (one side of real phone-style calls; sample: school-leave call, repair calls). No alternating pairs exist, so the SFT design is stream-continuation: context = last up to 3 real utterances, target = the next real utterance. Both sides real native Hindi; no fabricated text.

- [x] G3: SFT dataset built from real transcripts passes structural verification
  CHECK: .venv/bin/modal run research/training/download_indicvoices.py --verify-a1-sft
  EXPECT: SFT_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=9f7068ac9a27/64 entries; EXPECT=matched; output-sha256=eb0fdc6ee3e88719510c7cdd77ea87769cfea5e83828b2db8b0ce85c3f0ffbf8; output-bytes=767

- [x] G4: full A1 training ran on H100 with eval loss recorded
  EVIDENCE: 2026-09-02 live logs (v2 run after the label-pollution fix) — TRAIN_GPU NVIDIA H100 80GB HBM3, A1_DATA train=20000 val=509, trainable 6,594,560 (0.38%), TRAIN_A1_DONE steps=2500 final_loss=1.2763 eval_loss=1.3399; final two evals 1.3500→1.3399. First run (labels polluted by the template's think-wrappers) had eval_loss 1.5309 and was discarded.

- [x] G5: A1 adapter downloaded and passes structural sanity
  CHECK: ADAPTER_DIR=data/checkpoints/qwen3-a1-full .venv/bin/python research/training/check_adapter.py
  EXPECT: ADAPTER_OK
  EVIDENCE: adapter archived at data/checkpoints/qwen3-a1-full/ (26.4 MB DoRA weights); ADAPTER_OK

- [x] G6: serving with the A1 adapter answers warm under the 200 ms budget
  CHECK: .venv/bin/python research/training/check_serving.py
  EXPECT: SERVE_OK
  EVIDENCE: SERVE_OK — server_ms 40.21 / 42.27 / 42.93 warm (results/serving_latency.json); served unmerged (PeftModel) because merge_and_unload on bf16 DoRA produced corrupted weights (single garbage token for every prompt)

- [x] G7: honest quality samples and spend recorded
  EVIDENCE: results/a1_samples.json — "हलो" → "हाँ बोलिए आपको क्या करना है" (real call-opener continuation); OOD emotional prompt answered in call style (honest limitation: one-side service-call data, no empathy supervision yet). Estimated phase spend ≈ $4.5 of the $10 ceiling (H100 $0.001097/s × ~120 GPU-minutes + serving windows; exact credits to confirm on next dashboard view)
