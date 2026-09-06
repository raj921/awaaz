# AttuneBench-style native benchmark

This is the collection and scoring harness for a native Hindi/Telugu emotional-intelligence benchmark. It is inspired by AttuneBench and HumDial, but it is not their dataset and must not borrow their test annotations.

## Dataset size contract

Collect **200 core benchmark conversations** plus **20 separate audit conversations**, for **220 approved records total**:

- Core train: 140
- Core development: 30
- Core private test: 30
- Audit: 20

Core language targets:

- 80 Hindi
- 80 Telugu
- 20 Hinglish
- 10 Tenglish
- 10 mixed Hindi/Telugu

The audit set is additional and must remain untouched by training, prompt tuning, judge calibration, and release decisions. The 30 existing smoke-test scenarios are not part of these counts.

## Collection requirements

Use `collection-record.example.json` for each real conversation and `collection-checklist.md` before and after recording. Use the consent form only as a template; adapt it to the actual study, retention policy, local requirements, and approved review process.

Every approved record needs:

- native-authored or native-recorded Hindi/Telugu content
- participant consent for the specific use
- native transcript review
- PII review
- source/version/checksum provenance
- at least two native annotators
- complete-conversation and speaker split metadata

## Annotation requirements

Annotate emotion, intensity, valence, arousal, trajectory, user goal, preferred behavior, memory retention, safety, and response preference in the participant’s language. Preserve disagreement and adjudication. Follow `research/ANNOTATION_PROTOCOL.md`.

## Hum-Dial relationship

HumDial-EIBench remains external Chinese/English evaluation-only data. Reuse its task structure—trajectory detection, implicit causal reasoning, empathetic response, and acoustic-semantic conflict—but do not train on its evaluation data or translate it into Indic data.

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

Run readiness validation across the target counts:

```bash
python3 research/benchmark/attunebench/readiness.py \\
  --input research/benchmark/attunebench/conversations.jsonl \\
  --manifest research/benchmark/attunebench/split-manifest.example.json
```

The scorer reports language-sliced trajectory accuracy, valence/arousal/intensity MAE, preference distributions, model win rates, and inter-annotator Cohen’s kappa. It is not a replacement for confidence intervals, native human review, or the official Hum-Dial evaluator.
