# Gates: voice scale-up (whisper 16K clips / 4000 steps) + loop quality pass

OWNS: research/training/voice_pipeline.py (featurize_whisper, asr_finetune v2, loop/turn caps), GATES-V2.md

Scope: same fixed recipe that won the retrain round (language-prefixed labels,
448-token cap, warmup 100), scaled to the full 16K manifests and 4000 steps per
the reviewer's prescription. v2 saves to a NEW dir (v1 untouched = fallback +
comparison). Featurize moved to a CPU function — last round proved 16K
extraction costs ~$2.6 of silent H100 time.

- [x] G1: v2 eval beats v1 on the same 200-clip set, both languages (hi<41.41 te<69.05)
  EVIDENCE: 2026-09-05 asr_finetune steps=4000 on full 16K feats, save whisper-small-hi-te-v2: ASR_TUNED hi_wer=31.92 (was 41.41, −23%), te_wer=55.49 (was 69.05, −20%). Same eval set, same caps — the reviewer's prescription works.

- [x] G2: v2 weights healthy (479 tensors, 0 NaN/Inf, small uniform deltas vs base)
  EVIDENCE: 2026-09-05 inspect_asr: v2 base=479 tuned=479 tuned_params=241734912, NaN_Inf=0, mean_abs_delta all=2.72e-04 (encoder 2.75e-04, decoder 2.68e-04) — same uniform signature as v1 (1.36e-04), larger as expected from 4x steps. No corruption.

- [x] G3: full loop re-run on v2 with corrected ASR caps; per-stage ms + heard/reply recorded
  EVIDENCE: 2026-09-05 voice_loop on v2 (WHISPER_TUNED=v2, duration-scaled caps): hi heard EXACT match ("जी नमस्ते जी बोलिए"), te heard 1-word phonetic drift; asr 573–986ms, llm(24tok) 1116–1396ms, tts 2871–4836ms (TTS dominates). QUALITY FINDING (not hidden): te reply contains a Thai-script token ("แฟชั่น") — small-model sampling drift under top_p; documented, not fixed (needs decoding work, queued with frontend).

- [x] G4: spend recorded against the extended ceiling; all apps stopped
  EVIDENCE: round ≈ $1.4 est (CPU featurize ~$0.05 + 4000-step H100 ~$0.9 + inspect ~$0.05 + loop 2xH100 ~$0.4). Cumulative ≈ $17.4 of ~$22. 0 apps running. Killed-run lessons applied: detach+background launches, per-shard commits, resumable featurize (run survived 2 client kills, lost 0 committed shards).
