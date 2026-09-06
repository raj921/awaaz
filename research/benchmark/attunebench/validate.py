import argparse
import json
import sys
from pathlib import Path


LANGUAGES = {"hi", "te", "hinglish", "tenglish", "mixed"}
SPLITS = {"train", "dev", "test", "audit"}
EMOTIONS = {
    "joy", "pride", "gratitude", "calm", "hope", "interest", "affection", "relief",
    "sadness", "disappointment", "loneliness", "worry", "fear", "nervousness", "anger",
    "irritation", "frustration", "guilt", "shame", "confusion", "overwhelm",
    "mixed/ambiguous", "neutral",
}
TRAJECTORIES = {"initial", "emerging", "intensifying", "stable", "softening", "shifting", "mixed", "unclear"}
GOALS = {"vent", "comfort", "reflection", "advice", "celebration", "companionship", "practice", "message_drafting", "information", "safety_help", "closure", "unclear"}
SAFETY = {"none", "ambiguous_distress", "self_harm_or_harm_signal", "medical_urgency", "abuse_or_danger", "privacy_risk"}
CHOICES = {"a", "b", "tie", "both_bad"}

CONVERSATION_REQUIRED_FIELDS = {"conversation_id", "source", "split", "language", "script", "participant", "consent", "turns", "safety", "provenance"}
CONVERSATION_SOURCES = {"project_owned", "emoinhindi", "bhaav", "doctor_patient_indic", "iiith_temd", "telugu_emotion_identification"}
COLLECTION_STATUSES = {None, "collected", "transcribed", "reviewed", "annotated", "approved", "excluded"}
SCRIPTS = {"native", "romanized", "mixed"}
CONSENT_REQUIRED_FIELDS = ("recorded", "audio_use", "withdrawal_available")
TURN_SPEAKERS = {"user", "assistant", "other"}
EMOTION_RANGE_FIELDS = (("valence", -1, 1), ("arousal", 0, 1), ("intensity", 0, 1), ("confidence", 0, 1))
PREDICTION_RANGE_FIELDS = (("valence", -1, 1), ("arousal", 0, 1), ("intensity", 0, 1))
RESPONSE_REQUIRED_FIELDS = ("conversation_id", "turn_id", "model_variants", "responses", "human_judgments", "provenance")
PREDICTION_REQUIRED_FIELDS = ("conversation_id", "model_id", "model_revision", "predictions")
VARIANT_REQUIRED_FIELDS = ("blind_id", "model_id", "revision")
JUDGMENT_CHOICE_FIELDS = ("goal_fit", "emotional_appropriateness", "intensity_calibration", "agency")
ANNOTATION_LANGUAGES = {"hi", "te", "mixed"}
MAX_ERRORS_PRINTED = 20

SKIP = object()


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def in_range(value, lower, upper):
    return is_number(value) and lower <= value <= upper


def require_string(value, field, errors, minimum=1):
    if not isinstance(value, str) or len(value) < minimum:
        errors.append(f"{field} must be a string with at least {minimum} characters")


def require_ranges(record, path, fields, errors):
    for field, lower, upper in fields:
        if not in_range(record.get(field), lower, upper):
            errors.append(f"{path}.{field} must be between {lower} and {upper}")


def require_fields(record, fields, errors):
    for field in fields:
        if field not in record:
            errors.append(f"missing field: {field}")


def is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def validate_emotion(emotion, path, errors):
    if not isinstance(emotion, dict):
        errors.append(f"{path} must be an object")
        return
    primary = emotion.get("primary")
    if primary not in EMOTIONS:
        errors.append(f"{path}.primary is not a supported emotion")
    secondary = emotion.get("secondary")
    if secondary is not None and secondary not in EMOTIONS:
        errors.append(f"{path}.secondary is not a supported emotion")
    require_ranges(emotion, path, EMOTION_RANGE_FIELDS, errors)
    if emotion.get("trajectory") not in TRAJECTORIES:
        errors.append(f"{path}.trajectory is invalid")
    require_string(emotion.get("evidence"), f"{path}.evidence", errors)


def validate_required_scalars(row, errors):
    missing = sorted(CONVERSATION_REQUIRED_FIELDS - row.keys())
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    require_string(row.get("conversation_id"), "conversation_id", errors, 3)
    if row.get("source") not in CONVERSATION_SOURCES:
        errors.append("source is not an allowed native-data source")
    if row.get("collection_status") not in COLLECTION_STATUSES:
        errors.append("collection_status is invalid")
    if row.get("split") not in SPLITS:
        errors.append("split is invalid")
    if row.get("language") not in LANGUAGES:
        errors.append("language is invalid")
    if row.get("script") not in SCRIPTS:
        errors.append("script is invalid")


def validate_participant(participant, errors):
    if not isinstance(participant, dict):
        errors.append("participant must be an object")
        return
    require_string(participant.get("participant_id"), "participant.participant_id", errors)
    require_string(participant.get("speaker_id"), "participant.speaker_id", errors)


def validate_consent(consent, errors):
    if not isinstance(consent, dict):
        errors.append("consent must be an object")
        return
    for field in CONSENT_REQUIRED_FIELDS:
        if consent.get(field) is not True:
            errors.append(f"consent.{field} must be true")
    require_string(consent.get("consent_version"), "consent.consent_version", errors)


def validate_turn(turn, index, errors):
    path = f"turns[{index}]"
    if not isinstance(turn, dict):
        errors.append(f"{path} must be an object")
        return SKIP
    turn_id = turn.get("turn_id")
    if turn_id != index + 1:
        errors.append(f"{path}.turn_id must be sequential")
    if turn.get("speaker") not in TURN_SPEAKERS:
        errors.append(f"{path}.speaker is invalid")
    require_string(turn.get("text"), f"{path}.text", errors)
    if turn.get("speaker") == "user":
        validate_emotion(turn.get("emotion"), f"{path}.emotion", errors)
        if turn.get("goal") not in GOALS:
            errors.append(f"{path}.goal is invalid")
    elif "emotion" in turn or "goal" in turn:
        errors.append(f"{path} assistant/other turns must not contain user emotion or goal labels")
    return turn_id


def validate_turns(turns, errors):
    if not isinstance(turns, list) or not 3 <= len(turns) <= 12:
        errors.append("turns must contain between 3 and 12 records")
        return
    turn_ids = []
    for index, turn in enumerate(turns):
        turn_id = validate_turn(turn, index, errors)
        if turn_id is not SKIP:
            turn_ids.append(turn_id)
    if len(set(turn_ids)) != len(turn_ids):
        errors.append("turn_id values must be unique")


def validate_safety_label(safety, errors):
    if not isinstance(safety, dict) or safety.get("label") not in SAFETY:
        errors.append("safety.label is invalid")


def validate_provenance(provenance, errors):
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
        return
    require_string(provenance.get("collection_date"), "provenance.collection_date", errors)
    annotators = provenance.get("annotator_ids")
    if not isinstance(annotators, list) or len(annotators) < 2 or not all(isinstance(item, str) and item for item in annotators):
        errors.append("provenance.annotator_ids must contain at least two IDs")
    if provenance.get("pii_reviewed") is not True:
        errors.append("provenance.pii_reviewed must be true")
    if provenance.get("native_reviewed") is not True:
        errors.append("provenance.native_reviewed must be true")


def validate_conversation(row, line_number):
    if not isinstance(row, dict):
        return [f"line {line_number}: record must be an object"]
    errors = []
    validate_required_scalars(row, errors)
    validate_participant(row.get("participant"), errors)
    validate_consent(row.get("consent"), errors)
    validate_turns(row.get("turns"), errors)
    validate_safety_label(row.get("safety"), errors)
    validate_provenance(row.get("provenance"), errors)
    return [f"line {line_number}: {error}" for error in errors]


def validate_model_variants(variants, errors):
    variant_ids = []
    if not isinstance(variants, list) or len(variants) < 2:
        errors.append("model_variants must contain at least two records")
        return variant_ids
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            errors.append(f"model_variants[{index}] must be an object")
            continue
        for field in VARIANT_REQUIRED_FIELDS:
            require_string(variant.get(field), f"model_variants[{index}].{field}", errors)
        variant_ids.append(variant.get("blind_id"))
    if len(set(variant_ids)) != len(variant_ids):
        errors.append("model_variants blind_id values must be unique")
    return variant_ids


def validate_responses(responses, variant_ids, errors):
    response_ids = []
    if not isinstance(responses, list) or len(responses) < 2:
        errors.append("responses must contain at least two records")
        return response_ids
    for index, response in enumerate(responses):
        if not isinstance(response, dict):
            errors.append(f"responses[{index}] must be an object")
            continue
        require_string(response.get("blind_id"), f"responses[{index}].blind_id", errors)
        require_string(response.get("text"), f"responses[{index}].text", errors)
        response_ids.append(response.get("blind_id"))
    if set(response_ids) != set(variant_ids):
        errors.append("response blind IDs must match model variant blind IDs")
    return response_ids


def validate_judgment_item(judgment, index, response_ids, errors):
    annotator_id = judgment.get("annotator_id")
    require_string(annotator_id, f"human_judgments[{index}].annotator_id", errors)
    preferred = judgment.get("preferred_blind_id")
    if preferred not in set(response_ids) | {"tie", "both_bad"}:
        errors.append(f"human_judgments[{index}].preferred_blind_id is invalid")
    for field in JUDGMENT_CHOICE_FIELDS:
        if judgment.get(field) not in CHOICES:
            errors.append(f"human_judgments[{index}].{field} is invalid")
    require_string(judgment.get("reason_native"), f"human_judgments[{index}].reason_native", errors)
    return annotator_id


def validate_judgments(judgments, response_ids, errors):
    if not isinstance(judgments, list) or len(judgments) < 2:
        errors.append("human_judgments must contain at least two records")
        return
    annotator_ids = []
    for index, judgment in enumerate(judgments):
        if not isinstance(judgment, dict):
            errors.append(f"human_judgments[{index}] must be an object")
            continue
        annotator_ids.append(validate_judgment_item(judgment, index, response_ids, errors))
    if len(set(annotator_ids)) != len(annotator_ids):
        errors.append("human_judgments annotator IDs must be unique per item")


def validate_evaluation_provenance(provenance, errors):
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
        return
    seed = provenance.get("blind_order_seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        errors.append("provenance.blind_order_seed must be an integer")
    if provenance.get("annotation_language") not in ANNOTATION_LANGUAGES:
        errors.append("provenance.annotation_language is invalid")
    if provenance.get("adjudicated") is not True:
        errors.append("provenance.adjudicated must be true")


def validate_response_evaluation(row, line_number):
    if not isinstance(row, dict):
        return [f"line {line_number}: record must be an object"]
    errors = []
    require_fields(row, RESPONSE_REQUIRED_FIELDS, errors)
    require_string(row.get("conversation_id"), "conversation_id", errors)
    if not is_positive_int(row.get("turn_id")):
        errors.append("turn_id must be a positive integer")
    variant_ids = validate_model_variants(row.get("model_variants"), errors)
    response_ids = validate_responses(row.get("responses"), variant_ids, errors)
    validate_judgments(row.get("human_judgments"), response_ids, errors)
    validate_evaluation_provenance(row.get("provenance"), errors)
    return [f"line {line_number}: {error}" for error in errors]


def validate_prediction_item(prediction, index, errors):
    path = f"predictions[{index}]"
    if not isinstance(prediction, dict):
        errors.append(f"{path} must be an object")
        return
    if not is_positive_int(prediction.get("turn_id")):
        errors.append(f"{path}.turn_id must be a positive integer")
    if not isinstance(prediction.get("primary"), str) or not prediction.get("primary"):
        errors.append(f"{path}.primary must be a non-empty string")
    require_ranges(prediction, path, PREDICTION_RANGE_FIELDS, errors)
    if prediction.get("trajectory") not in TRAJECTORIES:
        errors.append(f"{path}.trajectory is invalid")


def validate_prediction(row, line_number):
    if not isinstance(row, dict):
        return [f"line {line_number}: record must be an object"]
    errors = []
    require_fields(row, PREDICTION_REQUIRED_FIELDS, errors)
    require_string(row.get("conversation_id"), "conversation_id", errors)
    require_string(row.get("model_id"), "model_id", errors)
    require_string(row.get("model_revision"), "model_revision", errors)
    predictions = row.get("predictions")
    if not isinstance(predictions, list) or not 3 <= len(predictions) <= 12:
        errors.append("predictions must contain between 3 and 12 records")
    else:
        for index, prediction in enumerate(predictions):
            validate_prediction_item(prediction, index, errors)
    return [f"line {line_number}: {error}" for error in errors]


def validate_file(path, kind, validator):
    errors = []
    records = 0
    ids = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            errors.append(f"line {line_number}: blank lines are not allowed")
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc}")
            continue
        records += 1
        record_id = record.get("conversation_id") if isinstance(record, dict) else None
        if kind != "response" and record_id in ids:
            errors.append(f"line {line_number}: duplicate conversation_id: {record_id}")
        if kind != "response":
            ids.add(record_id)
        errors.extend(validator(record, line_number))
    return errors, records


def print_errors(errors):
    for error in errors[:MAX_ERRORS_PRINTED]:
        print(error, file=sys.stderr)
    if len(errors) > MAX_ERRORS_PRINTED:
        print(f"... and {len(errors) - MAX_ERRORS_PRINTED} more errors", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Validate native Indic benchmark JSONL records.")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--kind", required=True, choices=("conversation", "response", "prediction"))
    args = parser.parse_args()

    validators = {"conversation": validate_conversation, "response": validate_response_evaluation, "prediction": validate_prediction}
    path = Path(args.input)
    if not path.is_file():
        print(f"input file does not exist: {path}", file=sys.stderr)
        return 2

    errors, records = validate_file(path, args.kind, validators[args.kind])
    if errors:
        print_errors(errors)
        return 1
    print(f"valid_records={records}")
    print(f"kind={args.kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
