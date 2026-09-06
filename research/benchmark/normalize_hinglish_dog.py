import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from normalize_public_data import normalize_text, text_hash, write_jsonl, write_report

SPLIT_PATHS = {
    "train": "train.parquet",
    "dev": "validation.parquet",
    "test": "test.parquet",
}


def load_rows(path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required: run with the project .venv python") from exc
    table = pq.read_table(path).to_pydict()
    columns = list(table.values())
    return [dict(zip(table.keys(), values)) for values in zip(*columns)]


def dialogue_id_for(date_value):
    return f"dog-{text_hash(str(date_value))[:12]}"


def assign_turn_indices(rows):
    by_dialogue = defaultdict(list)
    for row_index, row in enumerate(rows):
        by_dialogue[str(row["date"])].append(row_index)
    turn_indices = {}
    for indices in by_dialogue.values():
        ordered = sorted(indices, key=lambda i: (str(rows[i]["utcTimestamp"]), i))
        for turn_index, row_index in enumerate(ordered, 1):
            turn_indices[row_index] = turn_index
    return turn_indices


def build_records(rows, split, source_file, source_version):
    records = []
    skipped = 0
    turn_indices = assign_turn_indices(rows)
    for row_index, row in enumerate(rows):
        translation = row.get("translation") or {}
        text = normalize_text(str(translation.get("hi_en") or ""))
        if not text:
            skipped += 1
            continue
        text_en = normalize_text(str(translation.get("en") or ""))
        dialogue_id = dialogue_id_for(row["date"])
        key = text_hash(f"{dialogue_id}:{turn_indices[row_index]}:{text}")
        records.append({
            "record_id": f"dog-{key[:16]}",
            "source": "cmu_hinglish_dog",
            "source_version": source_version,
            "split": split,
            "language": "hi-en",
            "script": "latin",
            "modality": "text",
            "group_id": dialogue_id,
            "text": text,
            "emotion": None,
            "source_label": None,
            "intensity": None,
            "dialogue_id": dialogue_id,
            "speaker_id": str(row["uid"]),
            "metadata": {
                "text_en": text_en or None,
                "turn_index": turn_indices[row_index],
                "wiki_document_idx": row["wikiDocumentIdx"],
                "doc_idx": row["docIdx"],
                "utc_timestamp": str(row["utcTimestamp"]),
                "source_row": row_index + 1,
                "source_file": source_file,
            },
        })
    return records, skipped


def build_report(records, source_reports):
    turns_per_dialogue = Counter(record["dialogue_id"] for record in records)
    return {
        "records": len(records),
        "unique_texts": len({record["text"] for record in records}),
        "split_counts": dict(Counter(record["split"] for record in records)),
        "dialogues": len(turns_per_dialogue),
        "turns_per_dialogue": {
            "min": min(turns_per_dialogue.values()),
            "max": max(turns_per_dialogue.values()),
            "mean": round(len(records) / len(turns_per_dialogue), 2),
        },
        "speaker_counts": dict(Counter(record["speaker_id"] for record in records)),
        "grouping": "dialogue_id derived from conversation session timestamp; source train/validation/test splits preserved (validation mapped to dev)",
        "sources": source_reports,
        "limitations": [
            "No emotion, intensity, goal, or preference labels: structure/register resource only.",
            "Task-grounded movie-chat domain (Wikipedia documents), not open emotional conversation.",
            "HF card tags annotations_creators as machine-generated; the Hinglish utterances show human typing variance. Treat the Hinglish side as human-authored and the English parallel as auxiliary reference only.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Normalize CMU Hinglish document-grounded conversations.")
    parser.add_argument("--dog-dir", required=True, help="Directory with train/validation/test parquet files")
    parser.add_argument("--output", required=True, help="Normalized JSONL output")
    parser.add_argument("--report", required=True, help="JSON report output")
    parser.add_argument("--dog-version", required=True, help="Hugging Face commit pinning the files")
    args = parser.parse_args()

    records = []
    source_reports = []
    try:
        for split, filename in SPLIT_PATHS.items():
            path = Path(args.dog_dir) / filename
            if not path.is_file():
                raise FileNotFoundError(f"missing DoG split: {path}")
            split_records, skipped = build_records(load_rows(path), split, filename, args.dog_version)
            records.extend(split_records)
            source_reports.append({
                "source": "cmu_hinglish_dog",
                "split": split,
                "file": str(path),
                "rows_skipped_empty": skipped,
                "duplicates_removed": 0,
                "dedup_policy": "no text-level dedup: repeated short utterances are legitimate dialogue turns",
            })
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    write_jsonl(records, Path(args.output))
    report = build_report(records, source_reports)
    write_report(report, Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
