"""Humor baseline (TF-IDF + LogisticRegression) over M2H2 dialogue utterances.

Input:  data/processed/m2h2_humor_dialogue.jsonl (6,185 records)
    Fields used: text, source_label ("humor" | "non-humor"), split.
    emotion is null by design (humor is not emotion).
    Episode-grouped splits (train 5,300 / dev 408 / test 477) used as-is.
Output: results/humor_baseline.json + printed table.
Run:    .venv/bin/python research/benchmark/humor_baseline.py
"""

import json
from pathlib import Path
from collections import defaultdict

from baseline_classifier import evaluate, load_records, train_baseline

INPUT = Path("data/processed/m2h2_humor_dialogue.jsonl")
OUTPUT = Path("results/humor_baseline.json")
LABEL_KEY = "source_label"


def by_split(records):
    """Group records by their pre-assigned split."""
    grouped = defaultdict(list)
    for record in records:
        grouped[record["split"]].append(record)
    return grouped


def main():
    splits = by_split(load_records(INPUT))
    model = train_baseline(splits["train"], LABEL_KEY)
    results = {
        "train": len(splits["train"]),
        "dev": evaluate(model, splits["dev"], LABEL_KEY),
        "test": evaluate(model, splits["test"], LABEL_KEY),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"generated_on": "2026-09-01", "model": "tfidf-logreg", "task": "m2h2_humor", **results},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for split in ("dev", "test"):
        metrics = results[split] or {"macro_f1": None, "accuracy": None}
        print(f"{split:<5} macro-F1 {metrics['macro_f1']!s:<8} accuracy {metrics['accuracy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
