import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from normalize_public_data import normalize_text, text_hash, write_jsonl, write_report

M2H2_LABELS = {"humor", "non-humor"}
EXPECTED_FIELDS = ["Scenes", "Sl. No.", "Start_time", "End_time", "Utterance", "Label", "Speaker"]


def parse_speaker(raw_value):
    parts = [part.strip() for part in raw_value.split(",", 1)]
    speaker = parts[0] if parts and parts[0] else "unknown"
    listener_ref = None
    if len(parts) == 2 and parts[1] and parts[1] != "u-":
        listener_ref = parts[1]
    return speaker, listener_ref


def read_episode_tsv(path, source_version):
    records = []
    skipped = 0
    episode = path.stem.lower()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, [])
        if header != EXPECTED_FIELDS:
            raise ValueError(f"unexpected M2H2 header in {path}: {header}")
        for row_number, row in enumerate(reader, 2):
            if len(row) != len(EXPECTED_FIELDS):
                skipped += 1
                continue
            scene, sl_no, start_time, end_time, raw_text, label, raw_speaker = row
            text = normalize_text(raw_text)
            label = label.strip().lower()
            if not text:
                skipped += 1
                continue
            if label in {"", "nan"}:
                skipped += 1
                continue
            if label not in M2H2_LABELS:
                raise ValueError(f"unknown M2H2 label {label!r} at {path}:{row_number}")
            speaker, listener_ref = parse_speaker(raw_speaker)
            scene_id = scene.strip().lower()
            dialogue_id = f"m2h2-{episode}-{scene_id}"
            key = text_hash(f"{dialogue_id}:{sl_no}:{text}")
            records.append({
                "record_id": f"m2h2-{key[:16]}",
                "source": "m2h2",
                "source_version": source_version,
                "split": "unassigned",
                "language": "hi",
                "script": "native",
                "modality": "text",
                "group_id": f"m2h2-episode-{episode}",
                "text": text,
                "emotion": None,
                "source_label": label,
                "intensity": None,
                "dialogue_id": dialogue_id,
                "speaker_id": speaker,
                "metadata": {
                    "task": "humor_detection",
                    "episode": episode,
                    "scene": scene_id,
                    "utterance_no": sl_no.strip(),
                    "start_time": start_time.strip(),
                    "end_time": end_time.strip(),
                    "listener_ref": listener_ref,
                    "source_row": row_number,
                    "source_file": path.name,
                },
            })
    return records, skipped


def read_m2h2(directory, source_version):
    paths = sorted(directory.glob("Ep-*.tsv"))
    if not paths:
        raise FileNotFoundError(f"no M2H2 episode TSVs below {directory}")
    records = []
    skipped = 0
    for path in paths:
        episode_records, episode_skipped = read_episode_tsv(path, source_version)
        records.extend(episode_records)
        skipped += episode_skipped
    report = {
        "source": "m2h2",
        "duplicates_removed": 0,
        "dedup_policy": "no text-level dedup: repeated short utterances are legitimate dialogue turns",
        "rows_skipped_malformed_empty_or_unlabeled": skipped,
        "episodes": len({record["metadata"]["episode"] for record in records}),
        "dialogues": len({record["dialogue_id"] for record in records}),
        "files": [str(path) for path in paths],
    }
    return records, report


def split_by_episode(records, seed):
    episodes = sorted(
        {record["metadata"]["episode"] for record in records},
        key=lambda episode: hashlib.sha256(f"{seed}:{episode}".encode()).hexdigest(),
    )
    counts = Counter(record["metadata"]["episode"] for record in records)
    total = len(records)
    train_cut = int(total * 0.8)
    dev_cut = int(total * 0.9)
    assignment = {}
    cumulative = 0
    for episode in episodes:
        if cumulative < train_cut:
            split = "train"
        elif cumulative < dev_cut:
            split = "dev"
        else:
            split = "test"
        assignment[episode] = split
        cumulative += counts[episode]
    for record in records:
        record["split"] = assignment[record["metadata"]["episode"]]
    return assignment


def build_report(records, seed, source_report, split_assignment):
    label_counts = Counter(record["source_label"] for record in records)
    speaker_counts = Counter(record["speaker_id"] for record in records)
    return {
        "records": len(records),
        "unique_texts": len({record["text"] for record in records}),
        "split_counts": dict(Counter(record["split"] for record in records)),
        "label_counts": dict(label_counts),
        "speakers": dict(speaker_counts),
        "episodes_in_split": {
            split: sorted(episode for episode, assigned in split_assignment.items() if assigned == split)
            for split in ("train", "dev", "test")
        },
        "grouping": "episode-level group_id; splits assign whole episodes (80/10/10 of utterances) with deterministic seed",
        "seed": seed,
        "sources": [source_report],
        "limitations": [
            "M2H2 labels are humor detection (humor/non-humor), not emotion; the emotion field is intentionally null.",
            "Scripted TV-show dialogue (Shrimaan Shrimati Phir Se), not natural conversation.",
            "Native Devanagari Hindi text with speaker/listener structure; aligned audio/visual segments exist upstream under Main-Dataset/Raw-Audio and Main-Dataset/Raw-Visual (not downloaded).",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Normalize M2H2 multiparty Hindi humor dialogue TSVs.")
    parser.add_argument("--m2h2-dir", required=True, help="Directory containing Ep-*.tsv files")
    parser.add_argument("--output", required=True, help="Normalized JSONL output")
    parser.add_argument("--report", required=True, help="JSON report output")
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--m2h2-version", required=True, help="Upstream commit pinning M2H2 files")
    args = parser.parse_args()

    try:
        records, source_report = read_m2h2(Path(args.m2h2_dir), args.m2h2_version)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    split_assignment = split_by_episode(records, args.seed)
    write_jsonl(records, Path(args.output))
    report = build_report(records, args.seed, source_report, split_assignment)
    write_report(report, Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
