"""Fact extraction for automatic memory capture.

The memory store's default `ingest()` has no extractor, so it stores every
utterance verbatim — "umm ok" and "what is the weather" become permanent
"facts" alongside "my name is Raj". That is unusable for automatic capture,
which is why nothing in the app called it.

This module decides what is worth remembering from a conversational turn.
The rule is deliberately conservative: **capture only first-person statements
of enduring personal fact.** A missed fact is invisible; a wrong one is a bot
confidently telling you something false about yourself, so precision beats
recall here.

Rejected by design:
  * questions ("what is the weather")
  * backchannel / filler ("umm ok", "haan", "సరే")
  * commands to the assistant ("play music", "tell me a joke")
  * statements about anyone but the speaker ("he works at a hospital")
  * transient state ("I am tired today") unless emotionally salient

No LLM call: this runs on the voice critical path, where a second model
round-trip would add latency to every turn.
"""

from __future__ import annotations

import re

# --- signals that a turn is NOT a fact -------------------------------------

# A question is a request, never a statement about the speaker.
_QUESTION_MARKS = ("?", "？", "।?")
_QUESTION_WORDS = {
    # English
    "what", "who", "where", "when", "why", "how", "which", "whose", "can",
    "could", "would", "should", "is", "are", "do", "does", "did", "will",
    # Hindi (Devanagari)
    "क्या", "कौन", "कहाँ", "कहां", "कब", "क्यों", "कैसे", "कितना", "कितने",
    # Telugu
    "ఏమిటి", "ఎవరు", "ఎక్కడ", "ఎప్పుడు", "ఎందుకు", "ఎలా", "ఎంత",
}

# Pure filler / acknowledgement.
_FILLER = {
    "umm", "um", "uh", "hmm", "hm", "ok", "okay", "yeah", "yes", "no", "yep",
    "nope", "sure", "thanks", "thank", "hello", "hi", "hey", "bye", "please",
    "haan", "han", "nahi", "acha", "accha", "theek", "thik", "arre", "arey",
    "हाँ", "हां", "नहीं", "अच्छा", "ठीक", "नमस्ते", "हलो", "क्यों", "अरे",
    "అవును", "కాదు", "సరే", "మంచిది", "హలో", "నమస్తే", "అలాగే",
}

# Imperatives aimed at the assistant.
_COMMAND_STARTS = {
    "play", "stop", "pause", "open", "close", "call", "send", "set", "start",
    "tell", "show", "find", "search", "read", "write", "repeat", "translate",
    "बताओ", "बताइए", "सुनाओ", "करो", "कीजिए", "दिखाओ", "खोलो", "बंद",
    "చెప్పు", "చెప్పండి", "చూపించు", "ఆపు", "తెరువు", "పాడు",
}

# --- signals that a turn IS a personal fact --------------------------------

# First-person subject markers. Hindi/Telugu are pro-drop and postpositional,
# so these are matched as substrings of the token stream, not as a subject
# position the way English allows.
_FIRST_PERSON = {
    # English
    "i", "i'm", "im", "my", "mine", "me", "myself", "we", "our", "us",
    # Romanized Hindi
    "mera", "meri", "mere", "main", "mai", "mujhe", "mujhko", "hum", "hamara",
    # Hindi (Devanagari)
    "मैं", "मेरा", "मेरी", "मेरे", "मुझे", "मुझको", "हम", "हमारा", "हमें",
    # Telugu
    "నేను", "నా", "నాకు", "నాది", "మేము", "మా", "మాకు", "నన్ను",
}

# Enduring-fact predicates: identity, relationships, work, place, preference,
# health, plans. Presence of one of these plus a first-person marker is the
# core signal.
_FACT_CUES = {
    # English — identity & attributes
    "name", "am", "is", "was", "live", "living", "lives", "from", "born",
    "work", "works", "working", "job", "study", "studies", "studying",
    "school", "college", "office", "company", "married", "wife", "husband",
    "son", "daughter", "mother", "father", "brother", "sister", "family",
    "friend", "like", "likes", "love", "loves", "hate", "hates", "prefer",
    "favourite", "favorite", "allergic", "diabetic", "birthday", "age",
    "years", "speak", "speaks", "own", "have", "has", "need", "want",
    "exam", "wedding", "hospital", "doctor", "appointment", "flight",
    "accident", "insurance", "pregnant", "medicine", "surgery",
    # Hindi
    "नाम", "रहता", "रहती", "रहते", "काम", "नौकरी", "पढ़ाई", "पढ़ता", "पढ़ती",
    "शादी", "पत्नी", "पति", "बेटा", "बेटी", "माँ", "पिता", "भाई", "बहन",
    "परिवार", "दोस्त", "पसंद", "नापसंद", "जन्मदिन", "उम्र", "साल", "बोलता",
    "बोलती", "चाहिए", "चाहता", "चाहती", "परीक्षा", "अस्पताल", "डॉक्टर",
    "दुर्घटना", "बीमा", "दवा", "गर्भवती", "ऑपरेशन", "है", "हूँ", "हूं",
    # Telugu
    "పేరు", "ఉంటాను", "ఉంటున్నాను", "పని", "ఉద్యోగం", "చదువు", "చదువుతున్నాను",
    "పెళ్లి", "భార్య", "భర్త", "కొడుకు", "కూతురు", "అమ్మ", "నాన్న", "అన్న",
    "అక్క", "కుటుంబం", "స్నేహితుడు", "ఇష్టం", "పుట్టినరోజు", "వయస్సు",
    "సంవత్సరాలు", "మాట్లాడతాను", "కావాలి", "పరీక్ష", "ఆసుపత్రి", "డాక్టర్",
    "ప్రమాదం", "బీమా", "మందు", "ఆపరేషన్",
}

# Third-person subjects: a fact about someone else is not a fact about the
# user, and storing it as one is how a memory system starts lying.
_THIRD_PERSON = {
    "he", "she", "they", "his", "her", "their", "him", "them", "it",
    "वह", "वो", "उसका", "उसकी", "उनका", "उन्हें", "उसे",
    "అతను", "ఆమె", "వారు", "అతని", "ఆమె", "వాళ్ళు",
}

# Indic combining marks (matras, virama) are not word characters to Python's
# `\w`, so a naive `[^\W_]+` shatters "मेरा नाम" into ['म','र','न','म'] and
# every Hindi/Telugu fact silently fails to match. Trailing combining ranges
# keep the grapheme cluster together — same pattern memory_v2.WORD uses.
_TOKEN = re.compile(r"[^\W_]+[\u0300-\u036f\u0900-\u097f\u0c00-\u0c7f]*", re.UNICODE)

MIN_CHARS = 6
MAX_CHARS = 300


def _tokens(text: str) -> list[str]:
    return [t.casefold() for t in _TOKEN.findall(text or "")]


def is_question(text: str, toks: list[str]) -> bool:
    if any(text.rstrip().endswith(q) for q in _QUESTION_MARKS):
        return True
    # Leading interrogative ("what is ...", "क्या आप ...").
    return bool(toks) and toks[0] in _QUESTION_WORDS


def is_filler(toks: list[str]) -> bool:
    """True when the turn carries no content beyond acknowledgement."""
    return bool(toks) and all(t in _FILLER for t in toks)


def is_command(toks: list[str]) -> bool:
    return bool(toks) and toks[0] in _COMMAND_STARTS


def extract_facts(utterance: str, _working: list | None = None) -> list[str]:
    """Return the facts worth storing from one user turn (usually 0 or 1).

    Signature matches MemoryStore's `extractor` hook so it can be passed
    straight in: `MemoryStore(extractor=extract_facts)`.
    """
    text = (utterance or "").strip()
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return []

    toks = _tokens(text)
    if not toks:
        return []
    if is_filler(toks) or is_question(text, toks) or is_command(toks):
        return []

    token_set = set(toks)
    if not (token_set & _FIRST_PERSON):
        return []
    if not (token_set & _FACT_CUES):
        return []
    # "he is my brother" is about the user; "he works at a hospital" is not.
    # Require the third-person mention to be outweighed by a possessive.
    if token_set & _THIRD_PERSON and not (token_set & {
        "my", "mine", "our", "mera", "meri", "mere", "hamara",
        "मेरा", "मेरी", "मेरे", "हमारा", "నా", "నాది", "మా",
    }):
        return []

    # Store the utterance as spoken. Rewriting it into a canonical third-person
    # form needs an LLM; keeping the user's own words is honest and reversible.
    return [" ".join(text.split())]


def should_remember(utterance: str) -> bool:
    """Convenience predicate for callers that only need the decision."""
    return bool(extract_facts(utterance))
