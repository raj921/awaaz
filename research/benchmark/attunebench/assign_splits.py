import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


CORE_SPLITS = ("train", "dev", "test")
LANGUAGE_ORDER = ("hi", "te", "hinglish", "tenglish", "mixed")
AUDIT_LANGUAGES = {"hi", "te"}
MAX_ERRORS_PRINTED = 20


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


def stable_key(record, seed):
    value = f"{seed}:{record['conversation_id']}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


CONSENT_USES = ("recorded", "audio_use", "withdrawal_available", "research_use", "model_training_use", "evaluation_use")
CANDIDATE_REQUIRED_FIELDS = ("conversation_id", "source", "language", "participant", "consent", "provenance", "turns")


def check_missing_fields(record):
    missing = [field for field in CANDIDATE_REQUIRED_FIELDS if field not in record]
    if missing:
        return f"{record.get('conversation_id', '<unknown>')}: missing {', '.join(missing)}"
    return None


def check_source(record):
    if record.get("source") != "project_owned":
        return f"{record['conversation_id']}: only project_owned records can be assigned by this tool"
    return None


def check_collection_status(record):
    if record.get("collection_status") != "approved":
        return f"{record['conversation_id']}: collection_status must be approved"
    return None


def check_split_unassigned(record):
    if record.get("split") not in (None, "", "unassigned"):
        return f"{record['conversation_id']}: split is already assigned"
    return None


def check_language(record):
    if record.get("language") not in LANGUAGE_ORDER:
        return f"{record['conversation_id']}: unsupported language"
    return None


def check_participant(record):
    participant = record.get("participant", {})
    if not participant.get("participant_id") or not participant.get("speaker_id"):
        return f"{record['conversation_id']}: participant and speaker IDs are required"
    return None


def check_consent(record):
    consent = record.get("consent", {})
    if not all(consent.get(field) is True for field in CONSENT_USES):
        return f"{record['conversation_id']}: consent does not authorize all benchmark uses"
    return None


def check_provenance(record):
    provenance = record.get("provenance", {})
    if not provenance.get("pii_reviewed") or not provenance.get("native_reviewed"):
        return f"{record['conversation_id']}: PII/native review is incomplete"
    if not isinstance(provenance.get("annotator_ids"), list) or len(provenance["annotator_ids"]) < 2:
        return f"{record['conversation_id']}: at least two annotators are required"
    return None


def check_turns(record):
    if not isinstance(record.get("turns"), list) or not 3 <= len(record["turns"]) <= 12:
        return f"{record['conversation_id']}: turns must contain 3-12 records"
    return None


CANDIDATE_CHECKS = (
    check_missing_fields,
    check_source,
    check_collection_status,
    check_split_unassigned,
    check_language,
    check_participant,
    check_consent,
    check_provenance,
    check_turns,
)


def validate_candidate(record):
    for check in CANDIDATE_CHECKS:
        error = check(record)
        if error:
            return error
    return None


def check_manifest_status(manifest, force):
    if not force and manifest.get("status") != "finalized":
        return "refusing to assign splits until the manifest status is finalized"
    return None


def check_unique_ids(records):
    if len({record["conversation_id"] for record in records}) != len(records):
        return "conversation_id values must be unique"
    return None


def extract_targets(manifest):
    language_targets = manifest.get("core_language_targets", {})
    split_targets = manifest.get("split_language_targets", {})
    audit_target = manifest.get("audit_target_count")
    if not language_targets or not split_targets or not isinstance(audit_target, int):
        return None
    return language_targets, split_targets, audit_target


def check_total_records(records, language_targets, audit_target):
    expected_total = sum(language_targets.values()) + audit_target
    if len(records) != expected_total:
        return f"record count {len(records)} does not match finalized target {expected_total}"
    return None


def group_by_language(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["language"]].append(record)
    return grouped


def assign_language(language, candidates, language_targets, split_targets, seed):
    candidates = sorted(candidates, key=lambda record: stable_key(record, seed))
    core_target = language_targets.get(language, 0)
    if language in AUDIT_LANGUAGES:
        core_target += split_targets.get("audit", {}).get(language, 0)
    if len(candidates) != core_target:
        return None, f"{language} record count {len(candidates)} does not match target {core_target}"

    assigned = []
    audit_count = split_targets.get("audit", {}).get(language, 0)
    for record in candidates[:audit_count]:
        record["split"] = "audit"
        assigned.append(record)

    core_candidates = candidates[audit_count:]
    for split in CORE_SPLITS:
        count = split_targets.get(split, {}).get(language, 0)
        for record in core_candidates[:count]:
            record["split"] = split
            assigned.append(record)
        core_candidates = core_candidates[count:]
    if core_candidates:
        return None, f"{language} has unassigned records after applying targets"
    return assigned, None


def assign_all(records, language_targets, split_targets, audit_target, seed):
    grouped = group_by_language(records)
    assigned = []
    for language in LANGUAGE_ORDER:
        new_assignments, error = assign_language(language, grouped[language], language_targets, split_targets, seed)
        if error:
            return None, error
        assigned.extend(new_assignments)
    return assigned, None


def check_split_totals(assigned, split_targets, audit_target):
    split_counts = Counter(record["split"] for record in assigned)
    expected_splits = {split: sum(split_targets.get(split, {}).values()) for split in CORE_SPLITS}
    expected_splits["audit"] = audit_target
    if split_counts != expected_splits:
        return f"split assignment mismatch: actual={dict(split_counts)} expected={expected_splits}"
    return None


def validate_all_candidates(records):
    return [error for record in records if (error := validate_candidate(record))]


def print_errors(errors):
    for error in errors[:MAX_ERRORS_PRINTED]:
        print(error, file=sys.stderr)


def write_output(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def print_summary(assigned, seed):
    split_counts = Counter(record["split"] for record in assigned)
    print(f"assigned_records={len(assigned)}")
    print(f"split_counts={dict(split_counts)}")
    print(f"language_counts={dict(Counter(record['language'] for record in assigned))}")
    print(f"seed={seed}")


def fail(message):
    print(message, file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description="Assign approved native conversations to benchmark splits.")
    parser.add_argument("--input", required=True, help="Unassigned approved conversation JSONL")
    parser.add_argument("--manifest", required=True, help="Finalized split manifest JSON")
    parser.add_argument("--output", required=True, help="Output JSONL")
    parser.add_argument("--seed", type=int, default=20260827, help="Deterministic assignment seed")
    parser.add_argument("--force", action="store_true", help="Allow a manifest status other than the example placeholder")
    args = parser.parse_args()

    try:
        records = load_records(args.input)
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    error = check_manifest_status(manifest, args.force)
    if error:
        return fail(error)

    candidate_errors = validate_all_candidates(records)
    if candidate_errors:
        print_errors(candidate_errors)
        return 1

    error = check_unique_ids(records)
    if error:
        return fail(error)

    targets = extract_targets(manifest)
    if targets is None:
        return fail("manifest must contain core_language_targets, split_language_targets, and audit_target_count")
    language_targets, split_targets, audit_target = targets

    error = check_total_records(records, language_targets, audit_target)
    if error:
        return fail(error)

    assigned, error = assign_all(records, language_targets, split_targets, audit_target, args.seed)
    if error:
        return fail(error)

    error = check_split_totals(assigned, split_targets, audit_target)
    if error:
        return fail(error)

    write_output(Path(args.output), assigned)
    print_summary(assigned, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
