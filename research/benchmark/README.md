# Native Indic Emotional Intelligence Benchmark

This directory contains two distinct assets:

- `scenarios.jsonl`: 30 deterministic smoke-test scenarios for schema and pipeline development.
- `attunebench/`: the research benchmark format for real, consented, native Hindi/Telugu conversations and human-grounded evaluation.

The 30 scenarios are not research evidence. Do not report them as an AttuneBench-sized result.

## Target benchmark

Collect 200 real conversations:

- 80 native Hindi
- 80 native Telugu
- 20 Hinglish
- 20 Tenglish/mixed Hindi-Telugu

Each conversation should contain 5–10 natural turns where possible. Keep language, script, speaker, topic, and emotional intensity balanced enough to support slice analysis. Record why a conversation is excluded rather than silently dropping it.

## AttuneBench-style protocol

1. Recruit native Hindi/Telugu participants with informed consent.
2. Collect natural multi-turn conversations, not isolated emotion prompts.
3. Annotate mood trajectory, intensity, goals, response preferences, memory relevance, and safety with native-language human annotators.
4. Generate responses from each model variant using fixed decoding and model revisions.
5. Blind response identity and randomize pairwise order.
6. Collect observed and preferred behavior labels plus pairwise human choices.
7. Keep a private held-out release set untouched by training, prompt iteration, and judge calibration.
8. Report per-language, script, speaker, topic, emotion, and conversation-length slices with uncertainty.

## Files

- `attunebench/conversation.schema.json`: JSON Schema for collected conversations.
- `attunebench/response-evaluation.schema.json`: JSON Schema for blinded response judgments.
- `attunebench/annotation-template.json`: blank annotation record.
- `attunebench/split-manifest.example.json`: split and provenance contract.
- `attunebench/README.md`: collection, annotation, and evaluation instructions.
- `validate.py`: validates JSONL files against required fields and split rules.
- `score.py`: computes trajectory, preference, behavior, and agreement metrics from adjudicated records.

## Run the harness

Validate collected conversations:

```bash
python3 research/benchmark/attunebench/validate.py \\
  --input research/benchmark/attunebench/conversations.jsonl \\
  --kind conversation
```

Validate model trajectory predictions:

```bash
python3 research/benchmark/attunebench/validate.py \\
  --input research/benchmark/attunebench/predictions.jsonl \\
  --kind prediction
python3 research/benchmark/attunebench/score.py trajectory \\
  --conversations research/benchmark/attunebench/conversations.jsonl \\
  --predictions research/benchmark/attunebench/predictions.jsonl \\
  --output results/trajectory.json
```

Validate and score blinded response judgments:

```bash
python3 research/benchmark/attunebench/validate.py \\
  --input research/benchmark/attunebench/response-evaluations.jsonl \\
  --kind response
python3 research/benchmark/attunebench/score.py responses \\
  --input research/benchmark/attunebench/response-evaluations.jsonl \\
  --output results/responses.json
```

The scorer reports overall and language-sliced trajectory accuracy, valence/arousal/intensity MAE, preference distributions, model win rates, and inter-annotator Cohen’s kappa. It is deliberately transparent and is not a replacement for confidence intervals, human audit, or the official Hum-Dial evaluator.

## Data boundary

Use only native-language authored or recorded data. Never translate Hum-Dial, AttuneBench, English, or Chinese conversations into Hindi/Telugu and present them as native evidence. Hum-Dial-EIBench remains an external diagnostic benchmark and must not be used for training.
