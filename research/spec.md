# Emotional Hindi–Telugu Conversational AI

## Research specification

**Status:** Draft v1  
**Owner:** Rajkumar  
**Target role:** AI Research Engineer  
**Date:** 2026-08-27

## 1. Research question

Does explicit multi-turn emotional-state tracking combined with preference-tuned response behavior improve human-perceived emotional attunement and adaptation in Hindi, Telugu, and Hindi/Telugu-English code-switched conversations, without increasing unsupported-memory claims or damaging language quality?

## 2. Hypothesis

A model trained only on response imitation will often produce generally polite answers but fail to track mood changes, respect the user’s conversational goal, calibrate emotional intensity, or adapt after correction.

Adding structured emotional state and human preference signals should improve:

- emotional appropriateness
- validation and specific reflection
- intensity calibration
- adaptation after user correction
- conversational fit across multiple turns

The improvement should hold across native Hindi, native Telugu, Hinglish, Tenglish, and mixed-script conversations.

## 3. Fixed model and system scope

### Text model

- Base: `Qwen/Qwen3-1.7B-Base`
- Training: QLoRA/PEFT supervised fine-tuning followed by preference tuning
- Serving: isolated GPU worker with token streaming
- Backend: Go control plane for WebSockets, memory, cancellation, rate limits, metrics, and model routing

### Voice model

- Primary Indic quality model: `ai4bharat/IndicF5`
- Indic baseline: `kenpath/svara-tts-v1`
- Separate low-latency comparator: `Qwen/Qwen3-TTS-12Hz-0.6B-Base`
- ASR: faster-whisper `small` for realtime; `large-v3` or `distil-large-v3` for evaluation

The Qwen3-TTS comparator is not treated as a Hindi/Telugu model because its official language list does not include those languages. Indic quality and low-latency performance are separate experimental tracks.

## 4. Experimental variants

### Text ablation

| Variant | Description |
|---|---|
| A0 | Qwen3 base with a fixed system prompt |
| A1 | A0 + emotional conversation supervised fine-tuning |
| A2 | A1 + human preference optimization |
| A3 | A2 + explicit emotion trajectory and correction/adaptation examples |
| A4 | A3 + retrieved memory context and forgetting rules |

The primary comparison is A0 vs A3. A1, A2, and A4 identify which component caused the change.

### Voice ablation

| Variant | Description |
|---|---|
| V0 | IndicF5 or Svara base model |
| V1 | Language-balanced Hindi/Telugu adaptation |
| V2 | V1 + emotional speech fine-tuning with natural-language descriptions and intensity |
| V3 | V2 + code-switch balancing and neutral-preservation sampling |
| V4 | Compatible base + EmoSteer-style inference-time emotion control |
| L0 | Qwen3-TTS-12Hz-0.6B-Base low-latency comparator |

The primary voice comparison is V0 vs V3 on held-out speakers. L0 is used only for streaming latency comparison.

## 5. Data policy and source selection

The primary research data must be natively authored or natively recorded in Hindi and Telugu. English or Chinese examples may be used to reproduce external baselines, test generality, or validate tooling, but may not be machine-translated and presented as native Indic evidence.

### Source roles

| Source | Language/modality | Role | Constraint |
|---|---|---|---|
| EmoInHindi | Hindi dialogue text, multi-label emotion and intensity | Primary Hindi emotion-state training/evaluation source | Use its annotations and cite Singh et al.; do not invent missing preference labels |
| BHAAV | Hindi story text, five emotion classes | Auxiliary Hindi emotion-classification source | Research-use terms; request permission before commercial use; not a conversational or speech dataset |
| Hindi emotional speech repository | Hindi speech, eight emotion states | Auxiliary audio emotion baseline/evaluation | Verify the underlying IITKGP-SEHSC terms before redistribution or training; repository describes simulated/borrowed data |
| IIIT-H TEMD | Telugu emotional speech, about five hours | Primary Telugu acoustic-emotion source | Verify dataset access and terms from the authors before redistribution; semi-natural actor/non-actor speech is not spontaneous conversation |
| Telugu Emotion Identification | Telugu text | Auxiliary Telugu emotion evaluation/training source | Access is form-gated through IIIT-H LTRC; record the received terms and version |
| Doctor–Patient Indic Speech Dataset | Hindi/Telugu multi-speaker conversational audio and transcripts | Conversational ASR, diarization, turn-taking, and language evaluation | CC BY 4.0; add attribution, inspect speaker markers/timestamps, and do not infer emotional labels without annotation |
| HumDial-EIBench | Chinese/English human-recorded emotional audio | External diagnostic benchmark only | Do not train on its evaluation data; it is not Hindi/Telugu evidence |

### Required source ledger

For every downloaded source, maintain a ledger containing URL, commit/release/version, checksum, license/terms, citation, language, speakers, modality, allowed use, preprocessing, and whether it is train/dev/test. If the original terms are unclear, keep the data out of training until permission is confirmed.

### What the public sources do not provide

No verified public source above supplies every target field—especially user goal, preferred behavior, response preference, and full emotional trajectory—across both Hindi and Telugu. Those fields require new human annotation on a held-out, native-language conversational set. Do not fill them with LLM translations or treat weak automatic labels as human ground truth.

## 6. Data contract

Every text example must include:

```json
{
  "conversation_id": "conversation-level-split-id",
  "language": "hi|te|hinglish|tenglish|mixed",
  "script": "native|romanized|mixed",
  "messages": [],
  "user_emotion": {
    "primary": "sadness",
    "secondary": "worry",
    "valence": -0.7,
    "arousal": 0.4,
    "intensity": 0.8,
    "confidence": 0.86,
    "change_from_previous": "worsening"
  },
  "user_goal": "vent|comfort|reflection|advice|celebration|repair",
  "response_strategy": [
    "validate",
    "reflect_specific_detail",
    "ask_permission_before_advice"
  ],
  "chosen_response": "...",
  "rejected_response": "...",
  "memory_context": [],
  "speech_style": {
    "emotion_description": "warm, steady, gently reassuring",
    "intensity": 0.55
  }
}
```

Every voice example must include:

```json
{
  "audio": "path/to/audio.wav",
  "text": "transcript in the spoken language",
  "language": "hi|te|hinglish|tenglish|mixed",
  "script": "native|romanized|mixed",
  "speaker_id": "speaker-001",
  "emotion": "warm_reassuring",
  "emotion_description": "calmly acknowledging the person's difficulty",
  "valence": -0.2,
  "arousal": 0.3,
  "intensity": 0.55,
  "ref_audio": "path/to/consented_reference.wav"
}
```

Only licensed or personally recorded consented data is allowed. Remove PII, document the license/consent, and split by complete conversation and speaker. No speaker may appear in both training and test sets.

## 6. Emotional behavior taxonomy

The response should be labeled and evaluated across four behavioral capabilities:

1. **Perceiving:** identify the likely emotional state without overclaiming certainty.
2. **Understanding:** track mixed emotions, intensity, and changes across turns.
3. **Facilitating:** choose whether to listen, reflect, ask, advise, or celebrate based on the user’s goal.
4. **Managing:** validate, regulate tone, respect boundaries, repair mistakes, and handle risk safely.

Reject examples containing generic therapy language, unsupported psychological diagnosis, premature advice, repetitive validation, emotional over-intensity, fabricated personal facts, or ignored user corrections.

## 7. Evaluation protocol

Evaluate complete multi-turn conversations, not isolated prompts. The research benchmark target is 200 native conversations: 80 Hindi, 80 Telugu, 20 Hinglish, 10 Tenglish, and 10 mixed Hindi/Telugu. Use 140 training conversations, 30 development conversations, 30 private test conversations, and a separate 20-conversation audit set. Split by complete conversation and keep speakers disjoint for audio evaluation where feasible.

The existing 30-row fixture in `research/benchmark/scenarios.jsonl` is a deterministic smoke-test set only. It validates schema and pipeline behavior; it is not large enough to support a research claim.

### Hum-Dial external diagnostic

Use HumDial-EIBench only as an external cross-lingual diagnostic and never for training. Reuse its task structure as a design reference:

- emotional trajectory detection
- implicit causal reasoning
- empathetic response generation with textual and vocal dimensions
- acoustic-semantic conflict testing

HumDial is Chinese/English and must be reported separately from the native Hindi/Telugu results. Do not translate it into Hindi/Telugu or merge its annotations into the project-owned benchmark. Use the official evaluation scripts and record the exact dataset/model revision when running it.

### Text quality metrics

- blinded pairwise human preference
- emotional appropriateness
- validation and specific-detail reflection
- intensity calibration error
- user-goal fit
- adaptation-after-correction rate
- emotion trajectory tracking error
- memory-grounded answer accuracy
- unsupported emotion inference rate
- unsupported personal-memory rate
- Hindi/Telugu/code-switch naturalness
- response length and first-token latency

### Voice quality metrics

- Serving budget (decision 2026-09-02): target time-to-first-audio **< 200 ms** warm on the served GPU; report hardware, precision, warm/cold state, and P50/P95 with every measurement.
- Hindi WER and Telugu CER
- code-switch transcription accuracy
- speaker similarity
- naturalness MOS
- emotional fidelity MOS
- emotion intensity calibration
- neutral-preservation regression
- interpolation smoothness
- emotion erasure success
- clipping, dropout, repetition, and pause artifacts
- time to first audio packet
- real-time factor

### System metrics

- end-of-turn to first audio P50/P95/P99
- ASR, memory, LLM, TTS, and network stage latency
- TTS TTFA P50/P95/P99
- queue wait and queue depth
- cancellation and barge-in yield latency
- model-worker timeout rate
- GPU utilization and cost per completed turn
- memory retrieval precision@k, recall@k, MRR, and stale-recall rate

## 8. Success criteria

The research claim is supported only if A3 beats A0 on the held-out bilingual benchmark with statistical uncertainty reported and no unacceptable regressions.

Minimum decision rules:

- Human preference improves by at least 5 percentage points.
- Adaptation-after-correction improves by at least 10 percentage points.
- Unsupported personal-memory rate does not increase.
- Emotion intensity calibration error decreases.
- Hindi/Telugu language quality does not regress beyond the predefined WER/CER tolerance.
- V3 improves emotional fidelity over V0 while preserving intelligibility.
- Every voice latency claim reports hardware, precision, warm/cold state, concurrency, and P50/P95.
- A release fails on safety, memory deletion, or critical unsupported-fact violations regardless of average quality.

These thresholds are initial gates, not results. Record the measured values and revise thresholds only before looking at the held-out results.

## 9. Required artifacts

- dataset card and consent/license record
- model card for every base and adapter
- training configuration and exact model revisions
- evaluation fixture and split manifest
- base-vs-adapter comparison report
- failure analysis by language, script, speaker, emotion, noise, and conversation length
- latency waterfall and quality-latency Pareto chart
- reproducible commands and environment lockfiles
- Go backend trace showing memory, text, and voice events

## 10. First experiment

Before training anything, create 30 held-out multi-turn scenarios:

- 10 Hindi
- 10 Telugu
- 5 Hinglish/Tenglish
- 5 mixed-language

Cover sadness, worry, excitement, frustration, relief, mixed emotion, correction, explicit forgetting, and advice-vs-venting ambiguity. Produce A0 responses with fixed decoding settings, label expected behavior, and recruit at least one additional human rater for pairwise comparisons. This establishes the benchmark and exposes data-design problems before model training.
