"""Human-dynamics eval for MemoryStore. Each assertion can fail:

  1. WORKING: last utterances are in the context verbatim; old ones evicted
  2. REHEARSAL: a fact retrieved repeatedly outranks an unrehearsed twin
  3. SALIENCE: an emotional fact outranks a mundane one at equal relevance
  4. DECAY: after 30 untended days a mundane fact evaporates, a salient one survives
  5. HARD FORGET: even under the new dynamics, a forgotten fact never leaks
     (retrieval by perfect match AND context block)
  6. RE-LEARN: a forgotten fact can be learned again

Writes results/memory_human_eval.json; prints MEMORY_HUMAN_PASS only when
all assertions hold. The legacy guarantee suite stays in run_eval.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from memory import MemoryStore  # noqa: E402

RESULTS = Path("results/memory_human_eval.json")


def check_working():
    store = MemoryStore()
    for i in range(9):
        store.hear(f"turn number {i}")
    block = store.context_block("anything")
    return ("turn number 8" in block and "RECENT:" in block
            and "turn number 0" not in block and "turn number 1" not in block)


def check_rehearsal():
    store = MemoryStore()
    store.add("user works at infosys", salience=0.4)
    store.add("user likes mangoes", salience=0.4)
    for _ in range(3):
        store.retrieve("infosys", k=2)
    ranked = store.retrieve("user", k=2)
    if len(ranked) < 2:
        return False
    first, second = ranked
    return (first["fact"] == "user works at infosys"
            and first["rehearsals"] > second["rehearsals"])


def check_salience():
    store = MemoryStore()
    store.add("my brother bought a new bike")
    store.add("my brother met with an accident")
    ranked = store.retrieve("my brother", k=2)
    return ranked and ranked[0]["fact"] == "my brother met with an accident"


def check_decay():
    store = MemoryStore()
    store.add("i bought bread yesterday", salience=0.4)
    store.add("my father is in hospital", salience=0.9)
    store.tick(30)
    bread_gone = not store.retrieve("bread", k=3)
    hospital_alive = len(store.retrieve("hospital", k=3)) == 1
    return bread_gone and hospital_alive


def check_hard_forget():
    store = MemoryStore()
    store.add("i live in hyderabad")
    if not store.forget("i live in hyderabad"):
        return False
    leaked = bool(store.retrieve("i live in hyderabad", k=5) or store.retrieve("hyderabad", k=5))
    block = store.context_block("hyderabad", k=5)
    return not leaked and "hyderabad" not in block


def check_relearn():
    store = MemoryStore()
    store.add("i play cricket")
    store.forget("i play cricket")
    relearned = store.add("i play cricket")
    return (relearned is not None and relearned["status"] == "active"
            and bool(store.retrieve("cricket", k=2)))


def main():
    checks = {
        "working_memory": check_working(),
        "rehearsal_ranking": check_rehearsal(),
        "salience_ranking": check_salience(),
        "decay_and_survival": check_decay(),
        "hard_forget_holds": check_hard_forget(),
        "relearn_after_forget": check_relearn(),
    }
    failures = [name for name, ok in checks.items() if not ok]
    report = {"checks": checks, "failures": failures}
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        for failure in failures:
            print(f"MEMORY_HUMAN_FAIL: {failure}", file=sys.stderr)
        return 1
    print("MEMORY_HUMAN_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
