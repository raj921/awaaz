import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


CORE_SPLITS = {"train": 140, "dev": 30, "test": 30}
ALL_SPLITS = {**CORE_SPLITS, "audit": 20}
CORE_LANGUAGES = {"hi": 80, "te": 80, "hinglish": 20, "tenglish": 10, "mixed": 10}
REQUIRED_LANGUAGES = set(CORE_LANGUAGES)
CONSENT_FIELDS = ("recorded", "audio_use", "withdrawal_available", "research_use", "evaluation_use")


def load_records(path):
    records = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
    return records


def count_diff(actual, expected):
    keys = sorted(set(actual) | set(expected))
    return {key: {"actual": actual.get(key, 0), "expected": expected.get(key, 0)} for key in keys if actual.get(key, 0) != expected.get(key, 0)}


def summarize(records):
    core_records = [record for record in records if record.get("split") in CORE_SPLITS]
    audit_records = [record for record in records if record.get("split") == "audit"]
    return {
        "split_counts": Counter(record.get("split") for record in records),
        "core_records": core_records,
        "audit_records": audit_records,
        "core_language_counts": Counter(record.get("language") for record in core_records),
    }


def check_unique_ids(records):
    ids = [record.get("conversation_id") for record in records]
    if len(ids) != len(set(ids)):
        return ["conversation_id values must be unique"]
    return []


def expected_split_targets(manifest):
    targets = manifest.get("core_target_counts", CORE_SPLITS).copy()
    targets["audit"] = manifest.get("audit_target_count", ALL_SPLITS["audit"])
    return targets


def check_count_targets(records, stats, manifest):
    errors = []
    expected_splits = expected_split_targets(manifest)
    if stats["split_counts"] != expected_splits:
        errors.append(f"split_counts_mismatch={count_diff(stats['split_counts'], expected_splits)}")

    expected_languages = manifest.get("core_language_targets", CORE_LANGUAGES)
    if stats["core_language_counts"] != expected_languages:
        errors.append(f"core_language_counts_mismatch={count_diff(stats['core_language_counts'], expected_languages)}")

    for split, expected in manifest.get("split_language_targets", {}).items():
        actual = Counter(record.get("language") for record in records if record.get("split") == split)
        if actual != expected:
            errors.append(f"{split}_language_counts_mismatch={count_diff(actual, expected)}")

    if len(stats["core_records"]) != sum(CORE_SPLITS.values()):
        errors.append(f"core_record_count={len(stats['core_records'])} expected={sum(CORE_SPLITS.values())}")
    if len(stats["audit_records"]) != expected_splits["audit"]:
        errors.append(f"audit_record_count={len(stats['audit_records'])} expected={expected_splits['audit']}")
    return errors


def collect_participation(records):
    participants_by_split = defaultdict(set)
    speakers_by_split = defaultdict(set)
    for record in records:
        split = record.get("split")
        participant = record.get("participant", {})
        participant_id = participant.get("participant_id")
        speaker_id = participant.get("speaker_id")
        if participant_id:
            participants_by_split[split].add(participant_id)
        if speaker_id:
            speakers_by_split[split].add(speaker_id)
    return participants_by_split, speakers_by_split


def check_record(record):
    errors = []
    conversation_id = record.get("conversation_id")
    if record.get("collection_status") != "approved":
        errors.append(f"record_not_approved={conversation_id}")
    consent = record.get("consent", {})
    if not all(consent.get(field) is True for field in CONSENT_FIELDS):
        errors.append(f"consent_incomplete={conversation_id}")
    if record.get("split") == "train" and consent.get("model_training_use") is not True:
        errors.append(f"training_consent_missing={conversation_id}")
    provenance = record.get("provenance", {})
    if not provenance.get("pii_reviewed"):
        errors.append(f"pii_review_missing={conversation_id}")
    if not provenance.get("native_reviewed"):
        errors.append(f"native_review_missing={conversation_id}")
    if not isinstance(provenance.get("annotator_ids"), list) or len(provenance["annotator_ids"]) < 2:
        errors.append(f"annotation_count_insufficient={conversation_id}")
    return errors


def check_records(records):
    errors = []
    for record in records:
        errors.extend(check_record(record))
    return errors


def check_speaker_isolation(speakers_by_split):
    train_dev_speakers = speakers_by_split["train"] | speakers_by_split["dev"]
    overlap = train_dev_speakers & speakers_by_split["test"]
    if overlap:
        return [f"speaker_overlap_train_dev_test={sorted(overlap)}"]
    return []


def check_manifest(manifest):
    if manifest.get("status") != "finalized":
        return ["manifest status must be finalized before readiness can pass"]
    return []


def build_report(records, stats, participants_by_split, speakers_by_split, errors):
    return {
        "ready": not errors,
        "records": len(records),
        "core_records": len(stats["core_records"]),
        "audit_records": len(stats["audit_records"]),
        "split_counts": dict(stats["split_counts"]),
        "core_language_counts": dict(stats["core_language_counts"]),
        "participants_by_split": {key: len(value) for key, value in sorted(participants_by_split.items())},
        "speakers_by_split": {key: len(value) for key, value in sorted(speakers_by_split.items())},
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Check readiness of the native Indic benchmark.")
    parser.add_argument("--input", required=True, help="Approved conversation JSONL")
    parser.add_argument("--manifest", required=True, help="Split manifest JSON")
    parser.add_argument("--allow-incomplete", action="store_true", help="Print readiness report without failing incomplete counts")
    args = parser.parse_args()

    try:
        records = load_records(args.input)
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    stats = summarize(records)
    participants_by_split, speakers_by_split = collect_participation(records)

    errors = []
    errors += check_unique_ids(records)
    errors += check_count_targets(records, stats, manifest)
    errors += check_records(records)
    errors += check_speaker_isolation(speakers_by_split)
    errors += check_manifest(manifest)

    report = build_report(records, stats, participants_by_split, speakers_by_split, errors)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors and not args.allow_incomplete:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
