# Gates: voice milestone — STT, TTS, and the full loop

OWNS: research/training/voice_pipeline.py, results/voice/**, GATES-V.md

Scope: STT on real IndicVoices hi/te speech (zero-shot baselines + domain fine-tune of whisper-small), TTS via ai4bharat/indic-parler-tts (apache-2.0), and the full voice loop STT → bilingual A2 LLM → TTS with server-side per-stage latencies. Audio stayed on Modal volumes; only six demo WAVs came to the Mac.

- [x] G1: this ledger states outcomes that can fail
  CHECK: node /Users/rajkumar/.agents/skills/unlazy/scripts/gate-lint.mjs GATES-V.md
  EXPECT: LINT OK
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/rajkumar/rumikhire; path=e89d98c46c5e/63 entries; EXPECT=matched; output-sha256=7ecb94ef23590afdb96bb5cbacb2c9484d0eec748c4e42ca5f69bd45b89a6704; output-bytes=988

- [x] G2: voice eval/train data built from real IndicVoices audio on the Modal volume
  EVIDENCE: 2026-09-02 PREP_DONE {"hi_eval": 100, "te_eval": 100, "hi_train": 2000, "te_train": 2000} — 4,400 real conversation WAVs (2–10 s, Conversation scenario) extracted from the volume parquets at /root/indicvoices/voice_eval/ with aligned text manifests.

- [x] G3: ASR zero-shot baselines recorded (whisper-medium + whisper-small)
  EVIDENCE: 2026-09-02 asr_eval on 199 content utterances (≥3 words; backchannels excluded — whisper hallucination-loop territory, verified by asr_debug): whisper-medium hi_wer 76.89→72.64% te_wer 101.74% (1.1 s/clip), whisper-small hi 89.51% te 109.07%. Raw runs with loops (76.89/104.57) retained in logs as the pathology evidence.

- [x] G4: fine-tuned whisper-small improves over its zero-shot baseline on both languages
  EVIDENCE: 2026-09-02 asr_finetune — 500 steps, 4,000 hi+te clips, train loss 1.279→0.465 (110 s on H100, ~$0.03): ASR_TUNED hi_wer 53.84 (vs zero-shot small 89.51, −40% relative; also beats 3×-larger zero-shot medium 72.64), te_wer 87.91 (vs 109.07, −19% relative). Telugu remains the honest open gap — small whisper + 2,000 clips is not enough for spontaneous Telugu.

- [x] G5: TTS speaks both languages, license recorded, warm synthesis latency recorded
  EVIDENCE: 2026-09-02 tts_demo on ai4bharat/indic-parler-tts (apache-2.0, accepted by the user; 4 samples at results/voice/tts_*.wav): hi 2.94 s→2.6 s audio, 3.52 s→3.19 s; te 3.99 s→3.80 s, 4.03 s→3.72 s. Near-real-time autoregressive synthesis, 44.1 kHz.

- [x] G6: full STT → LLM → TTS loop runs end-to-end in both languages with per-stage latencies
  EVIDENCE: 2026-09-02 voice_loop (results/voice/loop_hi.wav, loop_te.wav): hi — heard "जी नमस्ते जी बोलगी", replied "और इस व्यावसाय का क्या है...", asr 794 ms, llm 24 tokens 1,153 ms (sampled, temp 0.8 — greedy produced backchannel loops), tts 5,046 ms; te — heard "ఆవునండి మా బ్ర్డ్ వచ్చేస్తే ఇండిగో ప్రేన్ పెయించండి", replied "ఓకే అండి మా బ్ర్డ", asr 401 ms, llm 908 ms, tts 2,471 ms.

- [x] G7: honest latency verdicts against the 200 ms budget and spend recorded
  EVIDENCE: VERDICTS — LLM first-token: PASS (62–65 ms, prior ledger). Full-utterance ASR: 0.4–0.9 s per clip — not 200 ms-class (streaming ASR is the upgrade path, named ceiling). TTS full synthesis: 2.5–5 s — autoregressive parler-tts is not a first-chunk-200 ms engine (streaming/parallel vocoder is the ceiling). Voice phase spend ≈ $1.6 (evals + finetune + TTS + loop, incl. failed attempts) — cumulative ≈ $10.4 of the user-extended ~$13 ceiling. All containers stopped.
