"""LLM-backed fact extraction — higher recall, off the critical path.

`extract.py` is deliberately rule-based and high-precision: it only fires on
phrasings in its cue lists, so it misses anything said sideways ("been at the
hospital fifteen years now" has no first-person marker at all). This module
is the recall half of that trade.

It is **not** a drop-in replacement. The rules run synchronously on every turn
and are what the user sees immediately; this runs afterwards, in a background
worker, and can only *add* facts the rules missed. Three consequences that
shape the whole design:

  * **A slow or dead LLM costs nothing.** No turn ever waits on it. If the
    call times out the turn has already been answered and stored.
  * **It is disabled unless configured.** No `MEMORY_LLM_URL` means the
    sidecar behaves exactly as it does today, rules only.
  * **Its output is untrusted.** An LLM asked to extract facts will happily
    invent them, and a fabricated memory is worse than a missed one — the
    assistant would state it back as truth. Everything it returns is
    validated and grounded against the source utterance before it is stored.

The grounding check is the load-bearing part: a returned fact must be built
from words the user actually said. That turns "hallucinated a plausible
detail" into "dropped", which is the failure mode we can live with.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

from extract import MAX_CHARS, MIN_CHARS, _TOKEN, is_command, is_filler, is_question

log = logging.getLogger("memory-sidecar.llm")

# Configuration. Absent URL/key => disabled, and the sidecar runs rules-only.
LLM_URL = os.environ.get("MEMORY_LLM_URL", "")
LLM_KEY = os.environ.get("MEMORY_LLM_KEY", "")
LLM_MODEL = os.environ.get("MEMORY_LLM_MODEL", "sarvam-105b-conversations")
LLM_TIMEOUT = float(os.environ.get("MEMORY_LLM_TIMEOUT", "20"))

# Hard ceilings. A turn that attracts nine facts is a model that has started
# narrating, not a user listing nine things about themselves.
MAX_FACTS_PER_TURN = 3
MAX_FACT_CHARS = 200

# Fraction of a candidate fact's content words that must appear in the source
# utterance. Below this the model is writing, not extracting.
#
# Not 1.0: extraction legitimately rewrites "been there fifteen years" into
# "I have worked at the hospital for fifteen years", pulling context from the
# conversation. 0.6 admits that while still rejecting invented specifics —
# a fabricated name or number drags the score well below it.
GROUNDING_THRESHOLD = 0.6

SYSTEM_PROMPT = """You extract durable personal facts from what a user said.

Return ONLY a JSON object: {"facts": ["...", "..."]}
Return {"facts": []} when there is nothing durable to store.

Store a fact ONLY if it is:
- about the speaker themselves (or their immediate family/possessions), and
- durable — true next month, not just right now.

Never store:
- questions, requests or commands to the assistant
- greetings, acknowledgements, filler
- facts about other people that do not involve the speaker
- passing states ("I'm tired right now", "it's raining")
- anything the user did not actually say

Write each fact as a short first-person statement, in the SAME LANGUAGE the
user spoke. Use only information present in the user's words. Do not guess,
infer specifics, or add detail that was not said.

Examples:
User: "umm ok sure"
{"facts": []}
User: "what's the weather like"
{"facts": []}
User: "yeah I've been at the hospital fifteen years now"
{"facts": ["I have worked at the hospital for fifteen years"]}
User: "मेरा नाम राज है"
{"facts": ["मेरा नाम राज है"]}"""


def enabled() -> bool:
    """True when an LLM endpoint is configured."""
    return bool(LLM_URL and LLM_KEY)


def _content_words(text: str) -> set[str]:
    return {t.casefold() for t in _TOKEN.findall(text or "") if len(t) > 1}


def is_grounded(fact: str, utterance: str, context: str = "") -> bool:
    """True when `fact` is built from words the speaker actually used.

    This is the hallucination guard. An LLM that invents "I work at Apollo
    Hospital in Mumbai" from "I work at a hospital" scores poorly here and is
    dropped: a fabricated memory gets repeated back to the user as fact, so
    the bias has to be toward silence. (Single-word substitutions in very
    short facts can still pass — "Apollo" for "a" in a three-word fact scores
    0.67 — so the prompt's "do not guess" and temperature 0 are the first
    line of defense; this check catches wholesale fabrication.)
    """
    fact_words = _content_words(fact)
    if not fact_words:
        return False
    source_words = _content_words(utterance) | _content_words(context)
    # Function words the model legitimately adds when forming a sentence.
    scaffolding = {
        "i", "my", "me", "have", "has", "had", "am", "is", "are", "was", "were",
        "the", "a", "an", "of", "in", "at", "on", "for", "to", "and", "with",
        "years", "year", "user", "speaker",
    }
    meaningful = fact_words - scaffolding
    if not meaningful:
        # Nothing but scaffolding is not a fact worth keeping.
        return False
    overlap = len(meaningful & source_words) / len(meaningful)
    return overlap >= GROUNDING_THRESHOLD


def _parse_facts(raw: str) -> list[str]:
    """Pull the fact list out of a model response.

    Models wrap JSON in prose or fences no matter how firmly the prompt asks
    them not to, so the object is located rather than assumed.
    """
    if not raw:
        return []
    text = raw.strip()
    # Strip ``` fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # Locate the outermost JSON object.
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, dict):
        return []
    facts = parsed.get("facts")
    if not isinstance(facts, list):
        return []
    return [f for f in facts if isinstance(f, str)]


def _call_llm(utterance: str, context: str) -> str:
    """One chat-completions call. Raises on transport/HTTP failure."""
    user_content = utterance
    if context:
        user_content = f"Recent conversation:\n{context}\n\nUser just said: {utterance}"

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 200,
        "temperature": 0,
    }).encode("utf-8")

    req = urllib.request.Request(
        LLM_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    choices = body.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def extract_facts_llm(
    utterance: str,
    context: str = "",
    known: set[str] | None = None,
) -> list[str]:
    """Extract durable facts with the LLM. Returns [] on any failure.

    `known` is the set of casefolded facts the rules already captured, so the
    two extractors never produce duplicates of each other.
    """
    if not enabled():
        return []
    text = (utterance or "").strip()
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return []

    # Cheap local rejects first: no point spending a network call on "ok".
    toks = [t.casefold() for t in _TOKEN.findall(text)]
    if not toks or is_filler(toks) or is_question(text, toks) or is_command(toks):
        return []

    try:
        raw = _call_llm(text, context)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Never propagate: this runs in a background worker and a failed
        # enrichment must be invisible to the user.
        log.warning("llm extraction failed: %s", exc)
        return []

    known = {k.casefold() for k in (known or set())}
    out: list[str] = []
    for fact in _parse_facts(raw):
        fact = " ".join(fact.split())
        if not (MIN_CHARS <= len(fact) <= MAX_FACT_CHARS):
            continue
        if fact.casefold() in known:
            continue
        if not is_grounded(fact, text, context):
            log.info("dropped ungrounded llm fact: %r (from %r)", fact, text)
            continue
        out.append(fact)
        known.add(fact.casefold())
        if len(out) >= MAX_FACTS_PER_TURN:
            break
    return out
