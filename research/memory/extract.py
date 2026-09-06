"""Rule-based durable-fact extraction — the precision half of the capture trade.

Fires only on explicit first-person durable phrasings (cue lists, en/hi/te).
Everything else returns []: the LLM enricher (llm_extract.py) exists for the
sideways phrasings this module deliberately misses.

Tokenization matches memory_v2.WORD (letters with combining marks attached),
so grounding overlap in llm_extract.py compares the same units the index uses.
"""

from __future__ import annotations

import re

# Same shape as memory_v2.WORD: letters, marks stay attached to their base.
# Without the mark ranges, "राज" tokenizes as ["र", "ज"] and both the cue
# match and the grounding check fall apart for Hindi/Telugu.
_TOKEN = re.compile(r"[^\W_]+[̀-ͯऀ-ॿఀ-౿]*", re.UNICODE)

MIN_CHARS = 6
MAX_CHARS = 400

# A cue must contain a first-person token AND a durable marker. The token
# check is a backstop for bare markers like "born in" with no subject.
FIRST_PERSON = frozenset(
    "i my me mine myself "
    "मैं मुझे मुझको मुझसे मेरा मेरी मेरे हमारा हमारी ".split()
    + "నేను నాకు నన్ను నా నాది నాతో మా మాది మేము".split()
)

# Substring cues on the casefolded utterance. Kept as phrases, not words:
# "my name is" fires, a bare "name" does not.
DURABLE_CUES = frozenset(
    [
        "my name is",
        "i live in",
        "i live at",
        "i work",
        "i am a",
        "i'm a",
        "i speak",
        "i was born",
        "born in",
        "my favorite",
        "my favourite",
        "my wife",
        "my husband",
        "my son",
        "my daughter",
        "my mother",
        "my father",
        "my mom",
        "my dad",
        "my family",
        "my dog",
        "my cat",
        "my pet",
        "my car",
        "my phone",
        "my birthday",
        "my job",
        "i own",
        "i have a",
        "i am from",
        "i'm from",
        "मेरा नाम",
        "मेरी ",
        "मेरा ",
        "मेरे ",
        "मैं रहता",
        "मैं रहती",
        "मैं काम",
        "मैं बोलता",
        "मैं बोलती",
        "मुझे ",
        "मेरा जन्म",
        "मेरी पत्नी",
        "मेरा पति",
        "मेरा बेटा",
        "मेरी बेटी",
        "मेरी माँ",
        "मेरे पिता",
        "मेरा परिवार",
        "मेरा कुत्ता",
        "मेरी बिल्ली",
        "मेरी भाषा",
        "मैं हिंदी",
        "मैं तेलुगु",
        "నా పేరు",
        "నేను ",
        "నాకు ",
        "నాది",
        "మా ",
        "నా భార్య",
        "నా భర్త",
        "నా కొడుకు",
        "నా కూతురు",
        "నా తల్లి",
        "నా తండ్రి",
        "నా కుటుంబం",
        "నా కుక్క",
        "నా పిల్లి",
        "నా భాష",
        "నేను హిందీ",
        "నేను తెలుగు",
        "పుట్టాను",
        "పుట్టింది",
        "నా పుట్టినరోజు",
        "నా ఉద్యోగం",
    ]
)

_COMMAND_FIRST = frozenset(
    "remember forget remind tell show play open call search set add delete remove "
    "start stop turn send book order find translate calculate repeat speak say "
    "बताओ करो देखो खोलो चलाओ भेजो చెప్పు చేయి చూడు తెరువు పంపు".split()
)

_FILLER = frozenset(
    "ok okay sure yeah yes no hmm uh um thanks thank alright great cool fine "
    "hi hello hey bye morning evening night please welcome sorry "
    "हाँ अच्छा ठीक नमस्ते धन्यवाद शुक्रिया अरे हम्म "
    "సరే అవును కాదు హలో నమస్తే ధన్యవాదాలు ఊహూ".split()
)

_QUESTION_OPENERS = frozenset(
    "what where when why how who which whose whom is are do does did can could "
    "will would should have has may might ".split()
    + "क्या कैसे कहाँ कब क्यों कौन किस ".split()
    + "ఏమిటి ఏంటి ఎక్కడ ఎలా ఎప్పుడు ఎందుకు ఎవరు ఏది".split()
)


def is_command(toks: list[str]) -> bool:
    """Leading imperative verb addressed at the assistant."""
    if not toks:
        return False
    first = toks[0]
    if first == "please" and len(toks) > 1:
        first = toks[1]
    return first in _COMMAND_FIRST


def is_filler(toks: list[str]) -> bool:
    """Whole utterance is a short acknowledgement/greeting, nothing durable."""
    return 0 < len(toks) <= 4 and all(t in _FILLER for t in toks)


def is_question(text: str, toks: list[str]) -> bool:
    """Ends with ? or opens with a question word. Questions state nothing."""
    if text.rstrip().endswith("?"):
        return True
    return bool(toks) and toks[0] in _QUESTION_OPENERS


def extract_facts(utterance: str, working: list[str] | None = None) -> list[str]:
    """Return [utterance] when it is an explicit durable first-person fact.

    `working` is accepted for interface parity with richer extractors and
    currently unused: re-hearing flows through to MemoryStore.add(), whose
    NOOP path handles rehearsal. Returns [] for everything else — the LLM
    enricher owns the sideways phrasings.
    """
    text = (utterance or "").strip()
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return []
    toks = [t.casefold() for t in _TOKEN.findall(text)]
    if not toks or is_filler(toks) or is_question(text, toks) or is_command(toks):
        return []
    if not any(t in FIRST_PERSON for t in toks):
        return []
    low = text.casefold()
    if not any(cue in low for cue in DURABLE_CUES):
        return []
    return [text]
