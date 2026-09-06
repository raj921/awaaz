# Native Hindi/Telugu Emotion Data Suite — Results Report

Generated: 2026-09-01
Scope decision (2026-09-01): this project delivers an **auxiliary data suite +
honest baselines** for native Hindi/Telugu emotional NLP. The 200-conversation
consented benchmark described in `research/benchmark/README.md` is deferred as
future work; no synthetic or fabricated data was used anywhere (project rule,
`NOTES.md` line 4).

## 1. Data suite (83,196 processed records)

All sources are the complete free+licensed universe for hi/te emotion data
(verified exhaustively 2026-08-31, KuralHub Interspeech-2026 survey as the
completeness check). Every file reproducible byte-identical from pinned
upstream versions; full provenance in `data/DATA_MANIFEST.json`.

| Processed output | Records | Content | Upstream | License |
|---|---|---|---|---|
| `native_emotion_classification.jsonl` | 66,591 | hi 20,152 (BHAAV, Devanagari story sentences) + te 34,999 (native-script sentences) + hi-en 11,440 (MaSaC, Hinglish TV dialogue, 446 dialogues) | Zenodo + HF + GitHub | research-use / CC BY 4.0 / shared-task |
| `m2h2_humor_dialogue.jsonl` | 6,185 | native-Devanagari multiparty TV dialogue, humor labels, speaker+listener structure, 13 episodes / 136 scenes | GitHub (MIT) | MIT |
| `cmu_hinglish_dog_dialogue.jsonl` | 9,962 | 259 real human-human Hinglish conversations (mean 38.5 turns), no labels | HF (festvox) | CC BY-SA 3.0 |
| `sowmith_telugu_ser_audio.jsonl` | 458 | acted Telugu speech-emotion audio index, 5 emotions | Kaggle | Apache 2.0 |

Quarantined (in manifest, not in any result): Doctor–Patient Indic Speech —
9 scripted sample dialogues, consent undocumented, smoke-test tooling only.

## 2. Baseline 1 — emotion classification (TF-IDF + LogisticRegression)

`research/benchmark/baseline_classifier.py`; TF-IDF (1-2 grams, min_df=2,
50k features) + logreg (class_weight="balanced"). Source splits preserved
as-is (no re-splitting; MaSaC episode leakage documented; group_id retained
for leakage-safe re-splits). Macro-F1 is the primary metric — neutral
dominates (58% of hi, 72% of te), so accuracy alone is misleading.

| Language (labels) | Train | Dev macro-F1 | Test macro-F1 | Test accuracy |
|---|---|---|---|---|
| hi — 5-class | 16,121 | 0.2991 | 0.3134 | 0.3745 |
| te — 5-class | 24,534 | 0.3769 | 0.3782 | 0.6000 |
| hi-en — 8-class | 8,506 | 0.2725 | 0.2608 | 0.3025 |

Per-class test F1 (support):
- hi: neutral 0.498 (1,150) · suspense 0.314 (325) · joy 0.281 (225) · anger 0.247 (155) · sadness 0.226 (161)
- te: neutral 0.718 (5,057) · sadness 0.436 (1,050) · joy 0.366 (780) · anger 0.199 (73) · fear 0.171 (20)
- hi-en: joy 0.426 (349) · neutral 0.315 (656) · surprise 0.286 (57) · anger 0.275 (142) · sadness 0.294 (155) · contempt 0.204 (82) · fear 0.172 (122) · disgust 0.115 (17)

Reading: weakest classes are exactly the tiny-support ones (te fear n=20,
hi-en disgust n=17). Context-free lexical features carry limited emotion
signal — this is the floor any future model (indic embeddings, context-aware
ERC) must beat on these same splits.

## 3. Baseline 2 — humor detection on M2H2 (same model family)

`research/benchmark/humor_baseline.py`; episode-grouped splits
(train 5,300 / dev 408 / test 477), binary humor/non-humor.

| Split | macro-F1 | Accuracy | humor F1 | non-humor F1 |
|---|---|---|---|---|
| dev | 0.5399 | 0.5686 | 0.4248 (n=169) | 0.6549 (n=239) |
| test | 0.5642 | 0.5996 | 0.4399 (n=193) | 0.6884 (n=284) |

Reading: humor lags non-humor by ~0.25 F1 — the punchline lives in
conversational context, not in the utterance's words alone. Context-free text
is an honest floor; the M2H2 multimodal baselines (context+audio+video) sit
above it by design.

## 4. Limitations (explicit)

- Main hi/te sets are sentence-level, not multi-turn dialogue; no user goals,
  preferences, or trajectory labels exist in any public source.
- hi-en (MaSaC) is romanized scripted TV dialogue — register-biased.
- 0 intensity labels anywhere public (EmoInHindi has them; access pending).
- Sowmith is acted speech at smoke-test scale (458 clips).
- Same TV episode spans official MaSaC splits — re-split by group_id for any
  leakage-safe comparison.
- The 200-conversation consented benchmark (native, natural, annotated) is
  not in this report — deferred as future work.

## 5. Reproduce

```bash
.venv/bin/pip install scikit-learn pyarrow   # one-time
python3 research/benchmark/normalize_public_data.py --bhaav-root data/raw/bhaav \
  --telugu-dir data/raw/telugu_emotion --masac-dir data/raw/masac_erc \
  --bhaav-version <pin> --telugu-version <pin> --masac-version <pin> \
  --output data/processed/native_emotion_classification.jsonl \
  --report data/processed/native_emotion_classification.report.json
python3 research/benchmark/normalize_m2h2.py --m2h2-dir data/raw/m2h2/Main-Dataset/Raw-Text \
  --output data/processed/m2h2_humor_dialogue.jsonl \
  --report data/processed/m2h2_humor_dialogue.report.json \
  --m2h2-version github-declare-lab-M2H2-dataset-7ad321bb9f01b581a025742114a9aca9b62ed3aa
.venv/bin/python research/benchmark/normalize_hinglish_dog.py --dog-dir data/raw/cmu_hinglish_dog \
  --output data/processed/cmu_hinglish_dog_dialogue.jsonl \
  --report data/processed/cmu_hinglish_dog_dialogue.report.json \
  --dog-version hf-19796c6fb32020154cb2745d48704fa73e29b17d
.venv/bin/python research/benchmark/baseline_classifier.py
.venv/bin/python research/benchmark/humor_baseline.py
```

Seeds fixed (20260828); every output verified byte-identical across reruns.
Checksums for all raw inputs + processed outputs: `data/DATA_MANIFEST.json`
and `data/raw/checksums.sha256`.
