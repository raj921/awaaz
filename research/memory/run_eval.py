"""Evaluate the memory prototype against research/benchmark/scenarios.jsonl.

Hard asserts (each can fail):
  1. every ACTIVE fact is retrievable by its own text (positive control for retrieval)
  2. no FORGOTTEN fact is retrievable even by its own text
     (negative control: the query matches perfectly, so absence proves forgetting)
  3. forget() API removes a newly added fact from retrieval
  4. near-duplicate add supersedes the old fact (conflict), only newest retrieved
  5. context_block injects active facts and never forgotten/superseded content

Measured (reported, not asserted): turn-text -> fact retrieval hits.
Writes results/memory_eval.json; prints MEMORY_EVAL_PASS only when all
assertions hold. Exit nonzero on any failure.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from memory import MemoryStore, normalize_fact  # noqa: E402

SCENARIOS = Path("research/benchmark/scenarios.jsonl")
RESULTS = Path("results/memory_eval.json")


def seed_store(record):
    store = MemoryStore()
    for fact in record.get("memory_facts", []):
        entry = store.add(fact["fact"], source=fact.get("source"))
        if fact.get("status") == "forgotten":
            store.forget(fact["fact"])
    return store


def self_recall_check(records):
    """Assert 1 + 2: active facts self-retrievable, forgotten never retrievable."""
    hits = required = forgotten_leaks = 0
    for record in records:
        store = seed_store(record)
        for fact in record.get("memory_facts", []):
            retrieved = store.retrieve(fact["fact"], k=5)
            found = any(entry["fact"] == normalize_fact(fact["fact"]) for entry in retrieved)
            if fact.get("status") == "forgotten":
                forgotten_leaks += found
            else:
                required += 1
                hits += found
    return hits, required, forgotten_leaks


def turn_text_hits(records):
    """Measured metric: scenario turns lexically recalling active facts."""
    hits = 0
    for record in records:
        store = seed_store(record)
        active = [normalize_fact(f["fact"]) for f in record.get("memory_facts", []) if f.get("status") != "forgotten"]
        for turn in record.get("turns", []):
            retrieved = {entry["fact"] for entry in store.retrieve(turn.get("user", ""), k=3)}
            hits += sum(1 for fact in active if fact in retrieved)
    return hits


def api_forget_check():
    """Assert 3: forget() removes a fresh fact from retrieval."""
    store = MemoryStore()
    store.add("I love filter coffee")
    forgotten = store.forget("I love filter coffee")
    return forgotten and not store.retrieve("filter coffee")


def conflict_check():
    """Assert 4: near-duplicate supersedes, newest wins, old never retrieved."""
    store = MemoryStore()
    store.add("mera naam raj hai")
    store.add("mera naam raj kumar hai")
    retrieved = store.retrieve("mera naam", k=5)
    newest_only = [e["fact"] for e in retrieved] == ["mera naam raj kumar hai"]
    superseded = any(e["status"] == "superseded" for e in store.entries)
    conflict_recorded = any(e["conflicts_with"] for e in store.entries)
    return newest_only and superseded and conflict_recorded


def injection_check(records):
    """Assert 5: context_block injects active, never forgotten/superseded."""
    leaks = 0
    injected = 0
    for record in records:
        store = seed_store(record)
        forgotten = [f["fact"] for f in record.get("memory_facts", []) if f.get("status") == "forgotten"]
        for turn in record.get("turns", []):
            block = store.context_block(turn.get("user", ""), k=3)
            injected += block.startswith("MEMORY:") if block else 0
            leaks += sum(1 for fact in forgotten if fact in block)
    return injected, leaks


def main():
    records = [json.loads(line) for line in SCENARIOS.read_text(encoding="utf-8").splitlines() if line.strip()]

    hits, required, forgotten_leaks = self_recall_check(records)
    api_ok = api_forget_check()
    conflict_ok = conflict_check()
    injected, injection_leaks = injection_check(records)
    measured_turn_hits = turn_text_hits(records)

    failures = []
    if required == 0:
        failures.append("no active facts found in scenarios (fixture invalid)")
    if hits != required:
        failures.append(f"self-recall {hits}/{required}")
    if forgotten_leaks:
        failures.append(f"forgotten facts leaked into retrieval: {forgotten_leaks}")
    if not api_ok:
        failures.append("forget() API failed")
    if not conflict_ok:
        failures.append("conflict supersede failed")
    if injected == 0:
        failures.append("context_block never injected active facts")
    if injection_leaks:
        failures.append(f"blocked facts leaked into injection: {injection_leaks}")

    report = {
        "scenarios": len(records),
        "active_facts_required": required,
        "self_recall_hits": hits,
        "forgotten_leaks": forgotten_leaks,
        "turn_text_retrieval_hits_measured": measured_turn_hits,
        "conflict_supersede_pass": conflict_ok,
        "api_forget_pass": api_ok,
        "injection_blocks": injected,
        "injection_leaks": injection_leaks,
        "failures": failures,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if failures:
        for failure in failures:
            print(f"MEMORY_EVAL_FAIL: {failure}", file=sys.stderr)
        return 1
    print("MEMORY_EVAL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
