# Native Hindi/Telugu Annotation Protocol

## Purpose

Collect labels that public datasets do not provide consistently: emotional trajectory, intensity, user goal, preferred response behavior, memory relevance, and safety. These labels must come from native-language human annotators, not translated English examples or an LLM acting as ground truth.

## Unit of annotation

Annotate complete 3–8 turn conversations. Preserve the original audio and native transcript. Annotators see the conversation in its original script, with Romanized code-switching preserved. They must not see model variant names during response comparison.

## Annotator requirements

- Native or near-native Hindi/Telugu comprehension.
- Familiarity with Romanized Hindi/Telugu and code-switching.
- Training on the rubric with examples and counterexamples.
- Explicit instruction not to diagnose, moralize, or infer facts not present.
- Separate annotator identities from the dataset exported for modeling.

## Per-turn labels

### Emotion

Select up to two emotions from the canonical set:

- joy
- pride
- gratitude
- calm
- hope
- interest
- affection
- relief
- sadness
- disappointment
- loneliness
- worry
- fear
- nervousness
- anger
- irritation
- frustration
- guilt
- shame
- confusion
- overwhelm
- mixed/ambiguous
- neutral

Select `mixed/ambiguous` when the evidence does not support a reliable primary label or when multiple emotions are inseparable.

### Continuous affect

Score each from 0 to 1:

- valence: negative to positive
- arousal: calm to activated
- intensity: strength of expressed emotion
- confidence: annotator confidence in the label

Intensity describes how strongly the emotion is expressed, not how serious the situation objectively is.

### Trajectory

Compared with the previous turn, choose:

- emerging
- intensifying
- stable
- softening
- shifting
- mixed
- unclear

Record the evidence span or phrase that supports the change.

### User goal

Select one primary goal and optionally one secondary goal:

- vent/listen
- comfort/reassurance
- reflection/understanding
- advice/problem solving
- celebration
- companionship
- practice/learning
- message drafting
- factual information
- safety/help seeking
- closure/topic change
- unclear

## Response behavior labels

For each candidate response, annotate:

- acknowledges emotional content
- reflects a concrete detail
- handles mixed emotion
- matches seriousness
- calibrates intensity
- asks before giving advice
- gives advice relevant to the stated goal
- preserves user agency
- asks a useful follow-up
- adapts after correction
- honors language/script preference
- avoids unsupported assumptions
- respects explicit forgetting
- uses safe escalation when required
- contains generic or repetitive comfort
- introduces unwanted direction
- makes an unsupported diagnosis or certainty claim

Use `yes`, `no`, or `not_applicable`; do not force a binary label when the criterion is not relevant.

## Preference annotation

Show two anonymized candidate responses for the same context and ask:

1. Which response better understood the user?
2. Which response better matched what the user wanted in that moment?
3. Which response better calibrated emotional intensity?
4. Which response better respected the user’s agency and boundaries?
5. Which response would you prefer overall?

Allow `tie` and `both_bad`. Require a short native-language reason focused on observable behavior. Randomize A/B order and record the order for bias analysis.

## Memory annotation

For each memory candidate, label:

- durable fact, preference, goal, relationship, episode, correction, or transient/noise
- should store: yes/no/uncertain
- sensitivity: ordinary/personal/restricted
- future usefulness: 0–1
- explicit request to remember: yes/no
- conflict with an existing fact: yes/no/uncertain
- should be forgotten: yes/no

A memory is not automatically valid because it is emotionally intense. Store only information that is durable, useful, and appropriate to retain.

## Safety annotation

Mark whether the conversation contains:

- no safety concern
- ambiguous distress
- possible self-harm or harm-to-others signal
- medical urgency
- abuse or immediate danger
- privacy/identity risk

Annotators do not provide clinical judgments. They label observable risk signals and whether the response should acknowledge limits, encourage appropriate human help, or follow the project’s escalation policy.

## Voice annotation

For audio examples, rate 1–5:

- transcript intelligibility
- pronunciation correctness
- emotional congruence with the target text/context
- naturalness
- pacing and pause appropriateness
- intensity calibration
- code-switch pronunciation
- speaker consistency

Mark artifacts separately: clipping, dropout, repetition, unnatural pause, breath artifact, noise, volume jump, or overlap.

## Agreement and adjudication

Double-label all evaluation items. Compute Cohen’s kappa or Krippendorff’s alpha for categorical labels and intraclass correlation for continuous scores. Disagreements on primary emotion, intensity, goal, response preference winner, memory retention, or safety are adjudicated by a third native annotator.

Do not discard disagreement. Store the individual labels, adjudicated label, confidence, and reason. Ambiguity is part of emotional conversation and should be reported as uncertainty rather than erased.

## Split rules

- Split complete conversations, never individual turns.
- Split speakers for audio experiments.
- Keep project-owned test scenarios private from training and prompt iteration.
- Keep any HumDial-EIBench data external to training and use its official evaluation scripts only for compatible inputs.
- Report metrics by Hindi, Telugu, native script, Romanized script, mixed code-switching, speaker, and scenario type.

## Deliverable format

Export one JSONL record per conversation containing:

```json
{
  "conversation_id": "project-hi-0001",
  "language": "hi",
  "script": "native",
  "source": "project_owned",
  "turns": [
    {
      "turn_id": 1,
      "speaker": "user",
      "text": "...",
      "audio": "audio/project-hi-0001/turn-001.wav",
      "emotion": {
        "primary": "worry",
        "secondary": "hope",
        "valence": -0.25,
        "arousal": 0.55,
        "intensity": 0.6,
        "confidence": 0.9,
        "trajectory": "emerging",
        "evidence": "..."
      },
      "goal": "comfort"
    }
  ],
  "memory_annotations": [],
  "response_preferences": [],
  "safety": {"label": "no_safety_concern"},
  "annotation": {
    "annotator_ids": ["a1", "a2"],
    "adjudicated": true
  }
}
```

## Quality gate

Do not use the project-owned set for model training until agreement, PII review, licensing/consent, speaker split, and duplicate checks pass. Do not claim improvement until the held-out set remains untouched throughout training and tuning.
