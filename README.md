# AttuneBench — native Indic emotional-intelligence benchmark + ML demo pipeline

Native-authored Hindi/Telugu emotion data suite (83,196 processed records, 8 pinned sources)
with honest baselines, plus a complete cloud ML pipeline demo: **memory system,
GPU fine-tuning, and sub-200 ms serving — all real runs, all reproducible.**

## The demo pipeline (the 3 role bullets)

**1. Long-term memory system** — `research/memory/memory.py`
Store with add / retrieve / conflict-supersede / explicit **forget**, plus a context-block builder.
Guarantee proven, not claimed: eval over 30 scenarios with negative controls — 27/27 self-recall,
**0 leaks from forgotten facts** (incl. an adversarial-injection control), `results/memory_eval.json`.
Now with human-like retention: 7-slot verbatim working memory, salience-weighted storage and decay
(emotional facts persist, mundane ones fade), rehearsal reinforcement, natural evaporation, re-learning —
and forgetting stays a hard guarantee, re-proven under the new dynamics: `MEMORY_HUMAN_PASS` 6/6,
`results/memory_human_eval.json`. Run: `python3 research/memory/run_eval.py`, `python3 research/memory/run_human_eval.py`.

**2. GPU fine-tuning** — `research/training/train_qwen3_sft.py`
Qwen3-1.7B-Base + **DoRA** (r=16, α=32, q/k/v/o) on Modal H100. Hand-rolled label masking (loss on
pure assistant content only) because TRL's `assistant_only_loss` needs template markers Qwen3 lacks —
and the raw chat template pollutes labels with think-wrappers the model then repeats. Base model cached
to a Modal Volume by a CPU function so GPU time is never billed for downloads. **Flagship run: one epoch
over 20,017 bilingual pairs (10,000 Hindi + 10,000 Telugu real conversation continuations)** from
IndicVoices, `TRAIN_A2_DONE steps=2500 final_loss=1.0154 eval_loss=1.0891` — a CUDA OOM on the first
attempt (Telugu utterance-length tail) was fixed with 512-token tail-slicing + expandable segments.
Artifacts: `data/checkpoints/qwen3-a2-bilingual/` (+ the Hindi-only A1 adapter).

**3. Sub-200 ms serving** — `research/training/serve_qwen3.py`
The bilingual DoRA adapter is served live behind a Modal `fastapi_endpoint`, `scaledown_window=600`,
server-side first-token latency measured in-container. **Warm: 62–65 ms vs the 200 ms budget** (client
wall time is India→US geography, recorded but never asserted). Four real bugs were caught by gates and
probes, not luck: model never moved to CUDA (12,430 ms → `.to("cuda")`), lazy CUDA kernel loading
(391 ms → warm-up at container start), **bf16 DoRA merge corruption** (one garbage token for every
prompt — solved by serving the adapter unmerged), and label pollution from the chat template's
think-wrappers. The model answers in **both languages**: `"हलो" → "हाँ तो आपको बात करना है..."` and
`"హలో" → "అవును అండి అంటే మీరు ఎంత కాల..."` (`results/a2_samples.json`).

## Evidence ledger

| Gate | Result |
|---|---|
| Four ledgers: `GATES.md` / `GATES-A1.md` / `GATES-A2.md` / `GATES-V.md` | **7/7 + 7/7 + 6/6 + 7/7 met**, tool-verified |
| Corpus (all in Modal volumes, zero bytes via the Mac) | Hindi 337,436 + Telugu 272,601 native utterances, CC BY 4.0, consented |
| Bilingual dataset | 20,017 train / 520 val pairs (10K hi + 10K te), 99.9% Indic script, `SFT_OK` |
| Serving latency | 61.8–64.7 ms warm ×3 (`results/serving_latency.json`) |
| Quality benchmark | held-out eval_loss base 1.52 → tuned **1.09** (hi −27%, te −30%; `results/bench_base_vs_tuned.json`) |
| Training | H100 80GB, 2,500 steps, eval_loss 1.0891 (live Modal logs) |
| Voice | hi WER 53.8% (fine-tuned small beats zero-shot medium), full loop in both languages (`results/voice/`) |
| Total cloud spend | **~$10.4** across all five phases (extended ceiling ~$13); containers stopped after every pass |

**4. Voice: STT + TTS + the full loop** — `research/training/voice_pipeline.py`
- **STT:** whisper-small domain-fine-tuned on 4,000 real hi/te conversation clips (500 steps, 110 s of H100): Hindi WER **89.5% → 53.8%** (beats 3×-larger zero-shot whisper-medium at 72.6%); Telugu 109.1% → 87.9% (open gap, named honestly). Whisper hallucination loops on backchannel clips were diagnosed and documented, not hidden.
- **TTS:** `ai4bharat/indic-parler-tts` (apache-2.0) — speaks both languages, warm synthesis ~3–4 s per sentence.
- **The loop:** real audio → fine-tuned whisper → bilingual LLM → TTS, server-side per-stage latencies (listen: `results/voice/loop_hi.wav`, `loop_te.wav`). LLM first-token passes the 200 ms class; full-utterance ASR/TTS honestly do not — streaming is the named upgrade path.

## The research core

- Data suite: `data/DATA_MANIFEST.json` — bhaav, Telugu-emotion, MaSaC ERC, M2H2 humor
  (native Devanagari), CMU Hinglish DoG, Sowmith Telugu SER. Native-authored only;
  no machine-translated data, no fabricated labels or consent (schema-enforced).
- Baselines (`results/RESULTS.md`): emotion test macro-F1 hi 0.3134 / te 0.3782 / hi-en 0.2608;
  humor (M2H2) 0.5642. Byte-identical reproducible; per-class numbers and limitations included.
- Spec: `research/spec.md` · project log: `NOTES.md` (Parts 1–13).

## Reproduce

```bash
.venv/bin/python research/training/validate_scripts.py   # TRAIN_SCRIPTS_OK
.venv/bin/modal run research/training/train_qwen3_sft.py  # TRAIN_DONE (~$0.50)
.venv/bin/modal volume get qwen3-a1 adapter data/checkpoints/qwen3-a1-smoke
.venv/bin/python research/training/check_adapter.py       # ADAPTER_OK
.venv/bin/modal deploy research/training/serve_qwen3.py   # URL -> research/training/endpoint.url
.venv/bin/python research/training/check_serving.py       # SERVE_OK
.venv/bin/modal app stop qwen3-a1-serve --yes             # stop the meter
```
