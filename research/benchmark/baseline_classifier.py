"""Baseline emotion classifiers for the native Indic pipeline.

GOAL
    Per-language TF-IDF + LogisticRegression baselines over
    data/processed/native_emotion_classification.jsonl (66,591 records).
    Produces the first real numbers for the project; everything downstream
    (AttuneBench model comparison) gets judged against these.

ENV (one-time)
    .venv already exists (has pyarrow). Add sklearn:
        .venv/bin/pip install scikit-learn
    Run:
        .venv/bin/python research/benchmark/baseline_classifier.py

OUTPUT
    results/baseline.json   (schema at the bottom of this file)
    + a small printed table (per-language macro-F1 on dev and test)
"""

import json
import pickle
from pathlib import Path
from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.pipeline import Pipeline

# ---------------------------------------------------------------------------
# INPUT: data/processed/native_emotion_classification.jsonl (66,591 records)
#   Fields used: text, emotion, language, split, group_id.
#   Labels: hi 5-class, te 5-class, hi-en 8-class (already normalized).
#   Use record["split"] as-is (train/dev/test). Never re-split randomly:
#   MaSaC episodes span official splits -- re-split by group_id only.
#   Neutral dominates (~58% hi / ~72% te / ~27% hi-en): macro-F1 is the metric.
#   3 separate models: hi-en is romanized, never mix with Devanagari hi.
#   Reproduce: see results/RESULTS.md; provenance: data/DATA_MANIFEST.json.
# ---------------------------------------------------------------------------


def load_records(path):
    """Read the JSONL and return a list of dicts.

    TODO: open `path` (utf-8), json.loads each non-empty line, return the list.
    """
    data_list = []

    with open(path, "r", encoding="utf-8") as file:
        for l in file:
            l = l.strip()
            if l:
                data_list.append(json.loads(l))

    return data_list
    

def by_language(records):
    """Group records into {"hi": [...], "te": [...], "hi-en": [...]}."""
    grouped = defaultdict(list)

    for r in records:
        grouped[r["language"]].append(r)

    return dict(grouped)

def train_baseline(train_records, label_key="emotion"):
    """Fit TF-IDF + LogisticRegression on TRAIN records only."""

    texts = [r["text"] for r in train_records]
    labels = [r[label_key] for r in train_records]

    model = Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=2,
            max_features=50_000,
        )),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
        )),
    ])

    model.fit(texts, labels)

    return model

    


def evaluate(model, records, label_key="emotion"):
    """Score a fitted pipeline on dev/test records.

    Returns {"macro_f1": float, "accuracy": float,
             "per_class": {label: {"precision", "recall", "f1", "support"}}}
    or None when records is empty (split absent for this language).
    """
    if not records:
        return None
    texts = [r["text"] for r in records]
    labels = [r[label_key] for r in records]
    predictions = model.predict(texts)
    report = classification_report(labels, predictions, output_dict=True, zero_division=0)
    skip = {"accuracy", "macro avg", "weighted avg"}
    return {
        "macro_f1": round(report["macro avg"]["f1-score"], 4),
        "accuracy": round(report["accuracy"], 4),
        "per_class": {
            label: {
                "precision": round(scores["precision"], 4),
                "recall": round(scores["recall"], 4),
                "f1": round(scores["f1-score"], 4),
                "support": scores["support"],
            }
            for label, scores in report.items()
            if label not in skip
        },
    }
def evaluate_language(language_records):
    """Train and evaluate one language's baseline. Returns (results, fitted model)."""
    by_split = defaultdict(list)
    for record in language_records:
        by_split[record["split"]].append(record)
    model = train_baseline(by_split["train"])
    result = {
        "train": len(by_split["train"]),
        "dev": evaluate(model, by_split["dev"]),
        "test": evaluate(model, by_split["test"]),
    }
    return result, model


def print_summary(languages):
    """Print the compact language | dev macro-F1 | test macro-F1 table."""
    print(f"{'language':<10} {'dev macro-F1':>12} {'test macro-F1':>13}")
    for language, result in languages.items():
        dev = result["dev"]["macro_f1"] if result["dev"] else None
        test = result["test"]["macro_f1"] if result["test"] else None
        print(f"{language:<10} {dev!s:>12} {test!s:>13}")


def main():
    records = load_records(Path("data/processed/native_emotion_classification.jsonl"))
    languages = {}
    models = {}
    for language, language_records in by_language(records).items():
        languages[language], models[language] = evaluate_language(language_records)
    Path("results").mkdir(parents=True, exist_ok=True)
    output = {"generated_on": "2026-08-31", "model": "tfidf-logreg", "languages": languages}
    Path("results/baseline.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # ponytail: pickled sklearn pipelines; swap for a fine-tuned transformer artifact only if one beats these numbers
    Path("data/checkpoints").mkdir(parents=True, exist_ok=True)
    with open("data/checkpoints/emotion_models.pkl", "wb") as handle:
        pickle.dump(models, handle)
    print_summary(languages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
