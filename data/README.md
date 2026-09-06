# Dataset workspace

`DATA_MANIFEST.json` is the committed registry for source URLs, revisions, checksums, roles, licensing constraints, and measured preprocessing output.

Downloaded source files live under `data/raw/` and are ignored by Git. Normalized records live under `data/processed/` and are also ignored because they contain third-party derived data.

## Current public data

- BHAAV: native Hindi narrative emotion classification; research-use terms and commercial permission requirement.
- Telugu Emotion: native Telugu sentence classification; CC BY 4.0 as declared by the Hugging Face card.
- EmoInHindi: not downloaded because the authors require an access agreement.

## Rebuild normalization

```bash
python3 research/benchmark/normalize_public_data.py \
  --bhaav-root data/raw/bhaav/extracted \
  --telugu-dir data/raw/telugu_emotion \
  --output data/processed/native_emotion_classification.jsonl \
  --report data/processed/native_emotion_classification.report.json \
  --seed 20260828 \
  --bhaav-version zenodo-3457467-v1-md5-cdcaf1997a422f18ee12d713a17ffdea \
  --telugu-version hf-6432e1357ed6ad57db1683451b08943639eb45ae
```

This output is useful for emotion-classification pretraining and sanity checks. It is not the primary AttuneBench-style conversational benchmark because it has no response preferences, user goals, voice, or intensity labels.
