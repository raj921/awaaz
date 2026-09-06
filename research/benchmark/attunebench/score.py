import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path


DIMENSION_FIELDS = ("goal_fit", "emotional_appropriateness", "intensity_calibration", "agency")
PAIRWISE_FIELDS = ("preferred_blind_id",) + DIMENSION_FIELDS


def mean(values):
    return sum(values) / len(values) if values else None


def exact_rate(values):
    return mean([1.0 if value else 0.0 for value in values])


def cohen_kappa(left, right):
    if len(left) != len(right) or not left:
        return None
    categories = set(left) | set(right)
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    expected = sum((left.count(category) / len(left)) * (right.count(category) / len(right)) for category in categories)
    if math.isclose(1 - expected, 0.0):
        return 1.0 if math.isclose(observed, 1.0) else None
    return (observed - expected) / (1 - expected)


def load_jsonl(path):
    records = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
    return records


def secondary_matches(secondary, predicted_secondary):
    return secondary == predicted_secondary if secondary is not None else predicted_secondary in (None, "neutral")


def score_turn(prediction, gold):
    emotion = gold["emotion"]
    return {
        "primary": prediction["primary"] == emotion["primary"],
        "secondary": secondary_matches(emotion.get("secondary"), prediction.get("secondary")),
        "valence": abs(prediction["valence"] - emotion["valence"]),
        "arousal": abs(prediction["arousal"] - emotion["arousal"]),
        "intensity": abs(prediction["intensity"] - emotion["intensity"]),
        "trajectory": prediction["trajectory"] == emotion["trajectory"],
    }


def trajectory_overall(totals):
    return {
        "primary_accuracy": exact_rate(totals["primary"]),
        "secondary_accuracy": exact_rate(totals["secondary"]),
        "valence_mae": mean(totals["valence"]),
        "arousal_mae": mean(totals["arousal"]),
        "intensity_mae": mean(totals["intensity"]),
        "trajectory_accuracy": exact_rate(totals["trajectory"]),
    }


def trajectory_slice(values):
    return {
        "turns_scored": len(values["primary"]),
        "primary_accuracy": exact_rate(values["primary"]),
        "valence_mae": mean(values["valence"]),
        "arousal_mae": mean(values["arousal"]),
        "intensity_mae": mean(values["intensity"]),
        "trajectory_accuracy": exact_rate(values["trajectory"]),
    }


def collect_turn_scores(conversations, predictions, totals, slices):
    for conversation_id, prediction_record in predictions.items():
        conversation = conversations.get(conversation_id)
        if conversation is None:
            continue
        gold_turns = {turn["turn_id"]: turn for turn in conversation["turns"]}
        language = conversation["language"]
        for prediction in prediction_record["predictions"]:
            gold = gold_turns.get(prediction["turn_id"])
            if gold is None or gold["speaker"] != "user":
                continue
            for key, value in score_turn(prediction, gold).items():
                totals[key].append(value)
                slices[language][key].append(value)


def score_trajectory(conversation_records, prediction_records):
    conversations = {record["conversation_id"]: record for record in conversation_records}
    predictions = {record["conversation_id"]: record for record in prediction_records}
    totals = defaultdict(list)
    slices = defaultdict(lambda: defaultdict(list))

    collect_turn_scores(conversations, predictions, totals, slices)

    return {
        "task": "trajectory",
        "conversations_scored": len(set(conversations) & set(predictions)),
        "conversations_missing_predictions": sorted(set(conversations) - set(predictions)),
        "turns_scored": len(totals["primary"]),
        "overall": trajectory_overall(totals),
        "by_language": {
            language: trajectory_slice(values)
            for language, values in sorted(slices.items())
        },
    }


def tally_judgment(record, judgment, blind_to_model, counters, pairwise_values):
    preferred = judgment["preferred_blind_id"]
    counters["preference"][preferred] += 1
    if preferred in blind_to_model:
        counters["model_wins"][blind_to_model[preferred]] += 1
    for field in DIMENSION_FIELDS:
        choice = judgment[field]
        counters["dimension"][field][choice] += 1
    annotator_id = judgment["annotator_id"]
    item_key = record["conversation_id"] + ":" + str(record["turn_id"])
    for field in PAIRWISE_FIELDS:
        pairwise_values[field][item_key][annotator_id] = judgment[field]


def tally_record(record, counters, pairwise_values):
    variants = record.get("model_variants", [])
    blind_to_model = {variant["blind_id"]: variant["model_id"] for variant in variants}
    for judgment in record.get("human_judgments", []):
        tally_judgment(record, judgment, blind_to_model, counters, pairwise_values)


def shared_items(items, left_id, right_id):
    left_values = []
    right_values = []
    for values in items.values():
        if left_id in values and right_id in values:
            left_values.append(values[left_id])
            right_values.append(values[right_id])
    return left_values, right_values


def pairwise_kappas(items):
    by_pair = []
    annotator_ids = sorted({annotator for values in items.values() for annotator in values})
    for index, left_id in enumerate(annotator_ids):
        for right_id in annotator_ids[index + 1:]:
            left_values, right_values = shared_items(items, left_id, right_id)
            kappa = cohen_kappa(left_values, right_values)
            if kappa is not None:
                by_pair.append({"annotator_a": left_id, "annotator_b": right_id, "items": len(left_values), "cohen_kappa": kappa})
    return by_pair


def compute_agreement(pairwise_values):
    agreement = {}
    for field, items in pairwise_values.items():
        by_pair = pairwise_kappas(items)
        agreement[field] = {"pairwise": by_pair, "mean_cohen_kappa": mean([item["cohen_kappa"] for item in by_pair])}
    return agreement


def build_response_report(records, counters, agreement):
    preference_counts = counters["preference"]
    total_preference = sum(preference_counts.values())
    return {
        "task": "response_preference",
        "items_scored": len(records),
        "human_judgments": total_preference,
        "preference_distribution": dict(preference_counts),
        "preference_rates": {key: value / total_preference for key, value in preference_counts.items()} if total_preference else {},
        "dimension_distributions": {field: dict(counts) for field, counts in counters["dimension"].items()},
        "selected_model_counts": dict(counters["model_wins"]),
        "selected_model_rates": {model: count / total_preference for model, count in counters["model_wins"].items()} if total_preference else {},
        "agreement": agreement,
    }


def score_responses(records):
    counters = {
        "preference": Counter(),
        "dimension": defaultdict(Counter),
        "model_wins": Counter(),
    }
    pairwise_values = defaultdict(lambda: defaultdict(dict))
    for record in records:
        tally_record(record, counters, pairwise_values)
    return build_response_report(records, counters, compute_agreement(pairwise_values))


def main():
    parser = argparse.ArgumentParser(description="Score native Indic emotional benchmark outputs.")
    subparsers = parser.add_subparsers(dest="task", required=True)

    trajectory = subparsers.add_parser("trajectory")
    trajectory.add_argument("--conversations", required=True)
    trajectory.add_argument("--predictions", required=True)
    trajectory.add_argument("--output")

    responses = subparsers.add_parser("responses")
    responses.add_argument("--input", required=True)
    responses.add_argument("--output")

    args = parser.parse_args()
    try:
        if args.task == "trajectory":
            result = score_trajectory(load_jsonl(args.conversations), load_jsonl(args.predictions))
            output_path = args.output
        else:
            result = score_responses(load_jsonl(args.input))
            output_path = args.output
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if output_path:
        Path(output_path).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
