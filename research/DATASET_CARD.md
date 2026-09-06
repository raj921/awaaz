# Native Indic Emotional Conversation Dataset Card

## Summary

This project uses native Hindi and Telugu resources to build and evaluate emotional conversation models. It does not translate English or Chinese emotional conversations into Hindi or Telugu and call them native data.

The dataset is assembled from public source datasets plus a small new human-annotated conversational set owned by the project. Each source keeps its original license, attribution, and allowed-use restrictions.

## Source inventory

| Source | Native content | Planned use | Status |
|---|---|---|---|
| EmoInHindi | Hindi Wizard-of-Oz counselling dialogues with 16 emotion labels and intensity | Hindi emotion trajectory pretraining and diagnostic evaluation | Verify distribution terms before download |
| BHAAV | Hindi story sentences with anger, joy, suspense, sadness, neutral | Auxiliary text emotion classifier | Research use; permission required for commercial use |
| Hindi emotional speech repository | Simulated Hindi emotional speech | Auxiliary acoustic baseline only | Underlying IITKGP-SEHSC terms must be checked |
| IIIT-H TEMD | Telugu semi-natural emotional speech from actors and non-actors | Telugu acoustic emotion baseline/adaptation | Confirm access and terms with the dataset authors |
| Telugu Emotion Identification | Telugu text emotion resource | Auxiliary Telugu emotion classifier/evaluation | Request through IIIT-H LTRC and record terms |
| Doctor–Patient Indic Speech Dataset | Hindi and Telugu two-speaker audio with native transcripts | ASR, diarization, turn-taking, and language robustness | CC BY 4.0 with attribution |
| HumDial-EIBench | Human-recorded Chinese and English emotional audio | External cross-lingual diagnostic benchmark | Evaluation-only; never train on its evaluation split |
| Project-owned set | Native Hindi/Telugu/mixed conversations with new human labels | Primary preference, goal, trajectory, memory, and safety evaluation | Collect with consent |

## Intended task coverage

- Native Hindi and Telugu emotion recognition.
- Multi-turn emotion trajectory tracking.
- Underlying-cause reasoning grounded in the dialogue.
- Empathetic text response generation.
- Emotional voice generation and acoustic congruence.
- Hindi/Telugu code-switching.
- ASR and turn-taking robustness.
- Memory-grounded response behavior and explicit forgetting.

## Data boundaries

- Every source is versioned by URL, repository commit or release, checksum, and retrieval date.
- Dataset terms are stored before training begins.
- Unclear or permission-gated sources remain excluded from training.
- Personally identifiable information is removed or masked before annotation and model input.
- Health, relationship, identity, and other sensitive fields receive restricted access and are not copied into logs.
- Speakers and complete conversations are disjoint across train, development, and test splits.
- Synthetic examples can be used for development augmentation only when clearly marked; they cannot replace native human data in the primary result.
- No HumDial-EIBench evaluation sample, annotation, or metadata is used for fine-tuning.

## Quality controls

For text:

- Unicode/script normalization without changing meaning.
- Duplicate and near-duplicate detection.
- Conversation-level leakage checks.
- Native-language reviewer checks for transliteration and code-switch labels.
- PII and sensitive-content review.

For audio:

- Sample-rate and channel normalization for the model pipeline.
- Clipping, silence, signal-to-noise, duration, and corrupted-file checks.
- Transcript alignment and WER/CER spot checks.
- Speaker-disjoint split verification.
- Native-language reviewer checks for pronunciation and emotion labels.
- Do not use automatic emotion classifiers as the sole ground truth.

## Annotation agreement

At least two native-language annotators label each project-owned evaluation item. A third annotator resolves disagreements on emotion, intensity, user goal, and preferred response behavior. Report agreement by language, script, and label family. Store disagreement rather than silently collapsing ambiguous cases.

## Licensing and attribution

The repository does not relicense third-party data. Each source is cited independently in the source ledger. Model checkpoints and derived artifacts include the source data, license, commit/hash, preprocessing version, and whether redistribution is permitted.

## Known limitations

- EmoInHindi covers dialogue emotion and intensity but does not automatically provide human response preferences or voice recordings.
- BHAAV is narrative Hindi text, not conversational dialogue or speech.
- IIIT-H TEMD is semi-natural acted/non-acted Telugu speech and may not represent spontaneous conversation.
- Doctor–Patient Indic Speech is useful for conversational audio but does not provide emotion labels and may lack fine-grained speaker timestamps.
- Public resources have different emotion taxonomies; the project uses a canonical valence/arousal/intensity representation plus source-specific labels and records the mapping.
- The project-owned set will be smaller than foundation training corpora; statistical uncertainty and confidence intervals are mandatory.

## Citation targets

- EmoInHindi: https://aclanthology.org/2022.lrec-1.627/
- BHAAV: https://github.com/midas-research/bhaav
- Hindi emotional speech repository: https://github.com/ankuPRK/Emotion-Recognition-in-Hindi-Speech
- IIIT-H TEMD: https://aclanthology.org/2020.lrec-1.192/
- IIIT-H language resources: https://ltrc.iiit.ac.in/showfile.php?filename=downloads/lingResources/newreleases.html
- Doctor–Patient Indic Speech: https://github.com/bala-ceg/doctor-patient-indic-speech-dataset
- HumDial-EIBench: https://huggingface.co/datasets/ASLP-lab/HumDial-EIBench
