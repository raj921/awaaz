import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


BHAAV_LABELS = {
    "0": "anger",
    "1": "joy",
    "2": "suspense",
    "3": "sadness",
    "4": "neutral",
}
TELUGU_LABELS = {
    "angry": "anger",
    "happy": "joy",
    "sad": "sadness",
    "fear": "fear",
    "no": "neutral",
}
MASAC_LABELS = {
    "anger",
    "contempt",
    "disgust",
    "fear",
    "joy",
    "neutral",
    "sadness",
    "surprise",
}
XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def normalize_text(value):
    value = value.replace("\ufeff", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_shared_strings(workbook):
    shared_strings = []
    if "xl/sharedStrings.xml" in workbook.namelist():
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        for item in root.findall("main:si", XML_NS):
            shared_strings.append("".join(node.text or "" for node in item.iter("{%s}t" % XML_NS["main"])))
    return shared_strings


def first_sheet_target(workbook):
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    relationship_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    relationships = {item.attrib["Id"]: item.attrib["Target"] for item in relationship_root}
    sheet = workbook_root.find("main:sheets/main:sheet", XML_NS)
    relationship_id = "{%s}id" % XML_NS["rel"]
    target = relationships[sheet.attrib[relationship_id]]
    return target if target.startswith("xl/") else "xl/" + target


def read_sheet_rows(workbook, target, shared_strings):
    rows = []
    sheet_root = ET.fromstring(workbook.read(target))
    for row in sheet_root.findall(".//main:row", XML_NS):
        values = []
        for cell in row.findall("main:c", XML_NS):
            value = cell.find("main:v", XML_NS)
            text = value.text if value is not None and value.text is not None else ""
            if cell.attrib.get("t") == "s" and text:
                text = shared_strings[int(text)]
            values.append(text)
        rows.append(values)
    return rows


def read_bhaav_workbook(path):
    with ZipFile(path) as workbook:
        shared_strings = read_shared_strings(workbook)
        return read_sheet_rows(workbook, first_sheet_target(workbook), shared_strings)


def find_bhaav_workbook(root):
    candidates = sorted(root.rglob("Bhaav-Dataset.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"canonical BHAAV workbook not found below {root}")
    return candidates[0]


def read_bhaav(root, source_version):
    workbook = find_bhaav_workbook(root)
    rows = read_bhaav_workbook(workbook)
    if not rows or rows[0][:2] != ["Sentences", "Annotation"]:
        raise ValueError(f"unexpected BHAAV header in {workbook}: {rows[:1]}")

    records = []
    seen = set()
    duplicate_count = 0
    for row_number, row in enumerate(rows[1:], 2):
        if len(row) < 2:
            continue
        text = normalize_text(row[0])
        label = str(row[1]).strip().removesuffix(".0")
        if not text:
            continue
        if label not in BHAAV_LABELS:
            raise ValueError(f"unknown BHAAV label {label!r} at row {row_number}")
        key = text_hash(text)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        records.append({
            "record_id": f"bhaav-{key[:16]}",
            "source": "bhaav",
            "source_version": source_version,
            "split": "source_train_test_unknown",
            "language": "hi",
            "script": "native",
            "modality": "text",
            "group_id": f"bhaav-text-{key}",
            "text": text,
            "emotion": BHAAV_LABELS[label],
            "source_label": label,
            "intensity": None,
            "dialogue_id": None,
            "speaker_id": None,
            "metadata": {"source_row": row_number, "source_workbook": workbook.name},
        })
    return records, {"source": "bhaav", "duplicates_removed": duplicate_count, "workbook": str(workbook)}


def read_telugu(directory, source_version):
    split_paths = {
        "train": directory / "Emotion_train.csv",
        "dev": directory / "Emotion_valid.csv",
        "test": directory / "Emotion_test.csv",
    }
    records = []
    seen = set()
    duplicate_count = 0
    for split, path in split_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing Telugu split: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            expected_fields = {"Sentence", "Emotion"}
            if not expected_fields <= set(reader.fieldnames or []):
                raise ValueError(f"unexpected Telugu fields in {path}: {reader.fieldnames}")
            for row_number, row in enumerate(reader, 2):
                text = normalize_text(row["Sentence"])
                source_label = row["Emotion"].strip().lower()
                if not text:
                    continue
                if source_label not in TELUGU_LABELS:
                    raise ValueError(f"unknown Telugu label {source_label!r} at {path}:{row_number}")
                key = text_hash(text)
                if key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                records.append({
                    "record_id": f"telugu-emotion-{key[:16]}",
                    "source": "telugu_emotion",
                    "source_version": source_version,
                    "split": split,
                    "language": "te",
                    "script": "native",
                    "modality": "text",
                    "group_id": f"telugu-text-{key}",
                    "text": text,
                    "emotion": TELUGU_LABELS[source_label],
                    "source_label": source_label,
                    "intensity": None,
                    "dialogue_id": None,
                    "speaker_id": None,
                    "metadata": {"source_row": row_number, "source_file": path.name},
                })
    return records, {"source": "telugu_emotion", "duplicates_removed": duplicate_count, "files": [str(path) for path in split_paths.values()]}


def read_masac(directory, source_version):
    split_paths = {
        "train": directory / "MaSaC_train_erc.json",
        "dev": directory / "MaSaC_val_erc.json",
        "test": directory / "MaSaC_test_erc.json",
    }
    records = []
    for split, path in split_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing MaSaC ERC split: {path}")
        dialogues = json.loads(path.read_text(encoding="utf-8"))
        for dialogue_index, dialogue in enumerate(dialogues):
            label_key = "emotions" if "emotions" in dialogue else "labels"
            utterances = dialogue["utterances"]
            speakers = dialogue["speakers"]
            labels = dialogue[label_key]
            if not (len(utterances) == len(speakers) == len(labels)):
                raise ValueError(f"length mismatch in {path} dialogue {dialogue_index}")
            episode = str(dialogue.get("episode", "unknown"))
            dialogue_id = f"masac-erc-{split}-{dialogue_index}"
            for utterance_index, raw_text in enumerate(utterances):
                text = normalize_text(raw_text)
                if not text:
                    continue
                label = str(labels[utterance_index]).strip().lower()
                if label not in MASAC_LABELS:
                    raise ValueError(
                        f"unknown MaSaC label {label!r} at {path} dialogue {dialogue_index} utterance {utterance_index}"
                    )
                speaker = normalize_text(str(speakers[utterance_index]))
                key = text_hash(f"{dialogue_id}:{utterance_index}:{text}")
                records.append({
                    "record_id": f"masac-erc-{key[:16]}",
                    "source": "masac_erc",
                    "source_version": source_version,
                    "split": split,
                    "language": "hi-en",
                    "script": "latin",
                    "modality": "text",
                    "group_id": f"masac-episode-{episode}",
                    "text": text,
                    "emotion": label,
                    "source_label": label,
                    "intensity": None,
                    "dialogue_id": dialogue_id,
                    "speaker_id": speaker,
                    "metadata": {
                        "episode": episode,
                        "dialogue_index": dialogue_index,
                        "utterance_index": utterance_index,
                        "source_file": path.name,
                    },
                })
    return records, {
        "source": "masac_erc",
        "duplicates_removed": 0,
        "dedup_policy": "no text-level dedup: repeated short utterances are legitimate dialogue turns",
        "files": [str(path) for path in split_paths.values()],
    }


def split_bhaav(records, seed):
    ordered = sorted(records, key=lambda record: hashlib.sha256(f"{seed}:{record['record_id']}".encode()).hexdigest())
    total = len(ordered)
    train_end = int(total * 0.8)
    dev_end = int(total * 0.9)
    for index, record in enumerate(ordered):
        if index < train_end:
            record["split"] = "train"
        elif index < dev_end:
            record["split"] = "dev"
        else:
            record["split"] = "test"
    return ordered


def write_jsonl(records, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def load_sources(args):
    bhaav_records, bhaav_report = read_bhaav(Path(args.bhaav_root), args.bhaav_version)
    telugu_records, telugu_report = read_telugu(Path(args.telugu_dir), args.telugu_version)
    source_reports = [bhaav_report, telugu_report]
    extra_records = []
    if args.masac_dir:
        masac_records, masac_report = read_masac(Path(args.masac_dir), args.masac_version)
        source_reports.append(masac_report)
        extra_records = masac_records
    bhaav_records = split_bhaav(bhaav_records, args.seed)
    return bhaav_records + telugu_records + extra_records, source_reports


def build_report(records, seed, source_reports):
    source_counts = Counter(record["source"] for record in records)
    language_counts = Counter(record["language"] for record in records)
    split_counts = Counter(record["split"] for record in records)
    label_counts = defaultdict(Counter)
    for record in records:
        label_counts[record["source"]][record["emotion"]] += 1

    return {
        "records": len(records),
        "unique_texts": len({record["text"] for record in records}),
        "source_counts": dict(source_counts),
        "language_counts": dict(language_counts),
        "split_counts": dict(split_counts),
        "label_counts": {source: dict(counts) for source, counts in label_counts.items()},
        "intensity_available": sum(record["intensity"] is not None for record in records),
        "dialogue_id_available": sum(record["dialogue_id"] is not None for record in records),
        "grouping": "text_hash; BHAAV shuffled with deterministic seed, Telugu source splits preserved, MaSaC ERC official splits preserved with episode-level group_id",
        "seed": seed,
        "sources": source_reports,
        "limitations": [
            "BHAAV is narrative sentence classification, not conversational dialogue.",
            "Telugu Emotion is sentence classification with five labels and no intensity field.",
            "MaSaC ERC is romanized Hinglish TV-show dialogue; the same episode can appear in multiple official splits, so re-split by group_id for leakage-safe evaluation.",
            "No normalized source supplies intensity labels, human response preference, user goal, or voice audio.",
            "EmoInHindi remains request-accessed and is not included in this output.",
        ],
    }


def write_report(report, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Normalize public native Hindi/Telugu emotion datasets.")
    parser.add_argument("--bhaav-root", required=True, help="Extracted BHAAV root")
    parser.add_argument("--telugu-dir", required=True, help="Downloaded Telugu Emotion CSV directory")
    parser.add_argument("--output", required=True, help="Normalized JSONL output")
    parser.add_argument("--report", required=True, help="JSON report output")
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--bhaav-version", required=True)
    parser.add_argument("--telugu-version", required=True)
    parser.add_argument("--masac-dir", help="Downloaded MaSaC ERC directory (optional)")
    parser.add_argument("--masac-version", help="Upstream commit pinning MaSaC ERC files")
    args = parser.parse_args()

    try:
        records, source_reports = load_sources(args)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    write_jsonl(records, Path(args.output))
    report = build_report(records, args.seed, source_reports)
    write_report(report, Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
