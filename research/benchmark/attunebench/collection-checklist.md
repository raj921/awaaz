# Native conversation collection checklist

## Before recording

- Assign a random participant ID and consent ID.
- Confirm the participant is a native or near-native Hindi/Telugu speaker.
- Record consent version, allowed uses, withdrawal process, and retention period.
- Explain that participation is voluntary and a topic can be skipped or stopped.
- Do not request real names, phone numbers, addresses, account numbers, or identifying medical details.
- Choose a topic from the balanced collection plan without forcing an emotional state.

## During recording

- Capture a natural 5–10 turn conversation.
- Preserve Hindi/Telugu native script where the participant uses it.
- Preserve Romanized and code-switched language exactly; do not normalize it into English.
- Allow pauses, corrections, mixed emotions, topic shifts, and requests to listen or stop.
- Record audio locally with explicit sample rate and channel metadata.
- Do not coach the participant toward a target label.

## After recording

- Assign a conversation ID that contains no personal information.
- Transcribe in the spoken language before any translation or parallel transcript.
- Segment turns and retain audio-to-turn alignment.
- Run PII review and remove or mask identifiers.
- Run a native-language transcript review.
- Create the source ledger entry and checksum.
- Send the record to two independent native annotators.
- Keep raw audio and unredacted transcripts in restricted storage.

## Annotation gate

Do not include a conversation in training or evaluation until:

- consent permits that use
- native transcript review passes
- PII review passes
- two annotators complete labels
- disagreements are adjudicated where required
- the participant and speaker split is recorded
- duplicate and near-duplicate checks pass

## Exclusion reasons

Use a structured reason instead of silently dropping data:

- consent_missing
- withdrawal_requested
- pii_not_redactable
- poor_audio
- corrupted_audio
- transcript_unrecoverable
- non_native_or_translated
- insufficient_turns
- speaker_identity_conflict
- duplicate_or_near_duplicate
- annotation_disagreement_unresolved
- unsafe_to_retain
- licensing_unclear

## Do not claim yet

The project does not have 200 real conversations merely because templates exist. Report collection counts only from approved records that pass the readiness validator.
