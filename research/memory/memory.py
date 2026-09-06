"""Human-like memory: working memory, salience, decay, rehearsal, hard forgetting.

Human retention dynamics on top of the hard-delete guarantee:
  - working memory: last WORKING_CAPACITY utterances, verbatim, fast-evicting
  - salience: emotional/important facts start stronger and decay slower
    (tau = 5 + 10 x salience days, Ebbinghaus-style exponential decay)
  - rehearsal: re-adding, hearing, or retrieving a fact strengthens it and
    resets its decay clock (spaced-repetition behavior)
  - evaporation: unrehearsed facts below STRENGTH_FLOOR fade out naturally
  - re-learning: a forgotten fact can be added fresh again

Deliberately NOT human: explicit forget() stays a hard, instant, permanent
delete — proven by negative controls in run_eval.py. Human forgetting is
unreliable; a delete API must not be. run_human_eval.py asserts the dynamics.

Ponytail ceiling: lexical token-overlap scoring only (no semantic matching);
upgrade paths named above in project NOTES. Retrieval stays sub-50 ms
inside the voice budget (spec.md 2026-09-02).
"""

import math
import re
from collections import deque

WORD = re.compile(r"[^\W_]+", re.UNICODE)

SALIENT_WORDS = (
    "accident", "emergency", "hospital", "sick", "died", "death", "wedding",
    "married", "pregnant", "birthday", "exam", "fired", "job", "love",
    "scared", "afraid", "angry", "arrest", "broken", "insurance",
)


def tokens(text):
    return {token.casefold() for token in WORD.findall(text or "")}


def normalize_fact(text):
    """Canonical stored/comparable form: unicode words, single spaces, trimmed."""
    return " ".join(WORD.findall(text or "")).strip()


class MemoryStore:
    """Layered store: durable facts with human dynamics + hard forgetting."""

    CONFLICT_SIMILARITY = 0.8
    WORKING_CAPACITY = 7
    STRENGTH_FLOOR = 0.05

    def __init__(self):
        self.entries = []
        self._seen_text = {}
        self.working = deque(maxlen=self.WORKING_CAPACITY)
        self.day = 0.0

    def _salience(self, text):
        lowered = text.casefold()
        return 0.9 if any(word in lowered for word in SALIENT_WORDS) else 0.4

    def add(self, fact, source=None, fact_type=None, sensitivity="ordinary", salience=None):
        """Store/reinforce a fact. Near-duplicate of an active fact conflicts:
        the new fact supersedes, the old is archived, never silently dropped.
        Re-adding an active fact rehearses it (strength +, decay clock reset)."""
        normalized = normalize_fact(fact)
        if not normalized:
            return None
        key = normalized.casefold()
        prior = self._seen_text.get(key)
        if prior is not None and prior["status"] in ("active", "superseded"):
            prior["strength"] = min(1.0, prior["strength"] + 0.15)
            prior["rehearsals"] += 1
            prior["last_access_day"] = self.day
            return prior
        level = salience if salience is not None else self._salience(normalized)
        entry = {
            "id": len(self.entries) + 1,
            "fact": normalized,
            "source": source,
            "fact_type": fact_type,
            "sensitivity": sensitivity,
            "status": "active",
            "conflicts_with": [],
            "salience": level,
            "strength": 0.6 + 0.4 * level,
            "rehearsals": 0,
            "last_access_day": self.day,
        }
        self.entries.append(entry)
        self._seen_text[key] = entry
        self._supersede_conflicts(entry)
        return entry

    def _supersede_conflicts(self, new_entry):
        new_tokens = tokens(new_entry["fact"])
        for entry in self.entries:
            if entry is new_entry or entry["status"] != "active":
                continue
            union = new_tokens | tokens(entry["fact"])
            similarity = len(new_tokens & tokens(entry["fact"])) / len(union) if union else 0.0
            if similarity >= self.CONFLICT_SIMILARITY:
                entry["status"] = "superseded"
                new_entry["conflicts_with"].append(entry["id"])

    def hear(self, utterance):
        """Working-memory intake: keep the recent utterance verbatim; any active
        long-term fact it touches gets a small rehearsal bump."""
        self.working.append(utterance)
        heard = tokens(utterance)
        for entry in self.entries:
            if entry["status"] == "active" and heard & tokens(entry["fact"]):
                entry["strength"] = min(1.0, entry["strength"] + 0.05)
                entry["rehearsals"] += 1
                entry["last_access_day"] = self.day

    def tick(self, days):
        """Advance the store's clock (days) — time-driven decay for testing."""
        self.day += days

    def _effective_strength(self, entry):
        tau = 5.0 + 10.0 * entry["salience"]
        age = max(0.0, self.day - entry["last_access_day"])
        return entry["strength"] * math.exp(-age / tau)

    def _active_entries(self):
        out = []
        for entry in self.entries:
            if entry["status"] != "active":
                continue
            if self._effective_strength(entry) < self.STRENGTH_FLOOR:
                entry["status"] = "evaporated"
                continue
            out.append(entry)
        return out

    def forget(self, fact):
        """Explicit forgetting: matched fact leaves retrieval forever. Hard, instant."""
        key = normalize_fact(fact).casefold()
        for entry in self.entries:
            if entry["status"] == "active" and entry["fact"].casefold() == key:
                entry["status"] = "forgotten"
                self._seen_text.pop(key, None)
                return True
        return False

    def retrieve(self, query, k=3):
        """Top-k active facts: overlap x effective strength. Retrieving a fact
        rehearses it (strength +, decay clock reset) — recall reinforces."""
        query_tokens = tokens(query)
        scored = []
        for entry in self._active_entries():
            overlap = len(query_tokens & tokens(entry["fact"]))
            if overlap:
                score = overlap * (0.3 + 0.7 * self._effective_strength(entry))
                scored.append((score, -entry["id"], entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result = [entry for _, _, entry in scored[:k]]
        for entry in result:
            entry["strength"] = min(1.0, entry["strength"] + 0.1)
            entry["rehearsals"] += 1
            entry["last_access_day"] = self.day
        return result

    def context_block(self, query, k=3):
        """Prompt-injection block: active facts (strongest first) plus recent
        working memory. Never contains forgotten, superseded, evaporated facts."""
        retrieved = self.retrieve(query, k=k)
        recent = list(self.working)[-2:]
        if not retrieved and not recent:
            return ""
        lines = ["MEMORY:"]
        lines.extend(f"- {entry['fact']}" for entry in retrieved)
        if recent:
            lines.append("RECENT:")
            lines.extend(f"- {utterance}" for utterance in recent)
        return "\n".join(lines)
