# Gates: A2 bilingual (Hindi + Telugu) fine-tune

OWNS: research/training/**, GATES-A2.md, results/a2_samples.json, data/checkpoints/qwen3-a2-bilingual/**

Scope: bilingual SFT on real IndicVoices conversation transcripts (10,000 Hindi + 10,000 Telugu stream-continuation pairs, no fabricated text), DoRA fine-tune of Qwen3-1.7B on Modal H100, adapter artifact, warm serving under the 200 ms budget, honest quality samples in both languages, spend under the ceiling.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES-A2.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=4a3e2ba045a18ef741c69f730e7cd9d65f4d5e1639ce1354134d4db85a20d0ae; output-bytes=406

- [x] G2: bilingual SFT dataset built from real transcripts passes structural verification
  CHECK: .venv/bin/modal run research/training/download_indicvoices.py --verify-a2-sft
  EXPECT: SFT_OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=d5d99de39701a001ec071077ce9f2caa7242a9a82b6fd070597bf126563b2eed; output-bytes=847

- [x] G3: bilingual training ran on H100 with eval loss recorded
  EVIDENCE: 2026-09-02 live logs — TRAIN_GPU NVIDIA H100 80GB HBM3, A2_DATA train=20017 val=520, TRAIN_A2_DONE steps=2500 final_loss=1.0154 eval_loss=1.0891. First attempt OOMed at step 1114 (Telugu utterance tail + allocator fragmentation) — fixed with 512-token tail-slice in collate + PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True, then trained clean end-to-end.

- [x] G4: bilingual adapter downloaded and passes structural sanity
  CHECK: ADAPTER_DIR=data/checkpoints/qwen3-a2-bilingual .venv/bin/python research/training/check_adapter.py
  EXPECT: ADAPTER_OK
  EVIDENCE: adapter archived at data/checkpoints/qwen3-a2-bilingual/ (26.4 MB DoRA weights); ADAPTER_OK

- [x] G5: serving with the bilingual adapter answers warm under the 200 ms budget
  CHECK: .venv/bin/python research/training/check_serving.py
  EXPECT: SERVE_OK
  EVIDENCE: SERVE_OK — server_ms 64.72 / 61.77 / 61.96 warm (results/serving_latency.json), served unmerged

- [x] G6: honest quality samples in both languages and spend recorded
  EVIDENCE: results/a2_samples.json — Hindi: "हलो" → "हाँ तो आपको बात करना है..."; Telugu: "హలో" → "అవును అండి అంటే మీరు ఎంత కాల..." (native conversational register in both); OOD emotional prompts answered in call style — same honest limitation as A1 (no empathy supervision yet). Phase spend ≈ $2.2 (train attempt 1 OOM ~$0.3 + clean train ~$0.9 + serving windows ~$0.9 + CPU cents); cumulative ≈ $8.7 of the $10 ceiling, exact credits to confirm on next dashboard view
