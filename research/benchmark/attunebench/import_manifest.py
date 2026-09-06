import argparse
import hashlib
import json
import sys
from pathlib import Path


SOURCE_RULES = {
    "emoinhindi": {"languages": {"hi"}, "role": "auxiliary_training_and_diagnostic"},
    "bhaav": {"languages": {"hi"}, "role": "auxiliary_classifier"},
    "doctor_patient_indic": {"languages": {"hi", "te"}, "role": "asr_diarization_turn_taking"},
    "iiith_temd": {"languages": {"te"}, "role": "auxiliary_acoustic_emotion"},
    "telugu_emotion_identification": {"languages": {"te"}, "role": "auxiliary_classifier"},
    "project_owned": {"languages": {"hi", "te", "hinglish", "tenglish", "mixed"}, "role": "primary_benchmark_and_preference"},
}


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def main():
    parser = argparse.ArgumentParser(description="Register a native dataset or local audio manifest with provenance.")
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_RULES))
    parser.add_argument("--language", required=True, choices=("hi", "te", "hinglish", "tenglish", "mixed"))
    parser.add_argument("--input", required=True, help="Local file to checksum")
    parser.add_argument("--version", required=True, help="Repository commit, release, or received dataset version")
    parser.add_argument("--license", required=True, dest="license_name", help="Exact license or terms label")
    parser.add_argument("--citation", required=True)
    parser.add_argument("--allowed-use", required=True)
    parser.add_argument("--output", required=True, help="Output JSON record")
    args = parser.parse_args()

    source = SOURCE_RULES[args.source]
    if args.language not in source["languages"]:
        print(f"{args.source} is not registered for language {args.language}", file=sys.stderr)
        return 1

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"input does not exist: {input_path}", file=sys.stderr)
        return 2

    record = {
        "source_id": f"src-{args.source}",
        "name": args.source,
        "language": args.language,
        "role": source["role"],
        "version": args.version,
        "license_or_terms": args.license_name,
        "citation": args.citation,
        "allowed_use": args.allowed_use,
        "checksum": checksum(input_path),
        "input_path": str(input_path),
        "redistribution": "verify_before_redistribution",
        "status": "registered_pending_data_quality_and_split_review",
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
