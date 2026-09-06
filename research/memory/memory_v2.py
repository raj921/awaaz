"""memory_v2.py — research-grounded memory for a voice agent.

Ported into AttuneBench as research/memory/memory_v2.py with three fixes
over the proposed draft (all verified by execution, see NOTES):
  1. Syntax: the draft did not compile (mangled `self.memories` line).
  2. Conflict detection uses RAW-token Jaccard (v1 behavior), not
     stopword-stripped Jaccard: on Hinglish the stripped version scores
     0.67 and misses conflicts our oracle asserts (raw scores 0.8).
     BM25 indexing still uses content tokens.
  3. STOP/SALIENT seeded with Devanagari + Telugu lists: the draft's
     English-only heuristics rated every Telugu fact importance 0.3.

Layers (CoALA): working buffer -> semantic facts (+ reflections) with provenance.
Retrieval: BM25 + optional dense cosine, fused with ACT-R base-level activation
(retrievability) and importance (Generative-Agents style scoring).
Write path: Mem0-style extract -> resolve {ADD, UPDATE, DELETE, NOOP}.
Temporal: bi-temporal validity (Zep/Graphiti) so UPDATE keeps history queryable.
Consolidation: reflection with provenance edges.
Hard forget: tombstone — text/vectors/index purged, working memory scrubbed,
derived reflections cascaded. Explicit forget is the ONLY hard delete;
LLM 'DELETE' and low activation are soft.
"""

import math
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

WORD = re.compile(r"[^\W_]+[̀-ͯऀ-ॿఀ-౿]*", re.UNICODE)
STOP = {
    # English
    "a", "an", "the", "i", "my", "me", "is", "am", "are", "was", "to", "of", "in",
    "and", "it", "that", "this", "with", "at", "on", "for",
    # Romanized Hindi (as spoken in Hinglish turns)
    "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "main", "hu", "hoon",
    "mera", "meri", "mere", "tha", "thi", "ho", "kya", "aur",
    # Devanagari Hindi stopwords
    "है", "हैं", "का", "की", "के", "को", "से", "में", "मैं", "हूँ", "मेरा", "मेरी",
    "मेरे", "था", "थी", "हो", "क्या", "और", "यह", "वह", "ये", "वो", "जो", "तो",
    "भी", "नहीं", "पर", "तक", "साथ", "अपने", "आप", "हम", "तुम", "कर", "किया",
    # Telugu stopwords
    "అని", "ఆ", "ఈ", "ఒక", "కు", "లో", "ను", "నా", "మీ", "మా", "అది", "ఇది",
    "ఏ", "కాదు", "ఉంది", "ఉన్నాయి", "చేసి", "మరియు", "లేదా", "కూడా", "అయితే",
    "వారు", "మేము", "నాకు", "మాకు", "నిన్ను", "మిమ్ము", "అలా", "ఇలా", "ఎలా",
}
SALIENT = {
    # English
    "accident", "emergency", "hospital", "sick", "died", "death", "wedding", "married",
    "pregnant", "birthday", "exam", "fired", "job", "love", "scared", "afraid", "angry",
    "arrest", "broken", "insurance",
    # Hindi (Devanagari) equivalents
    "दुर्घटना", "आपातकाल", "अस्पताल", "बीमार", "मौत", "शादी", "गर्भवती", "जन्मदिन",
    "परीक्षा", "नौकरी", "प्यार", "डर", "भय", "गुस्सा", "कोप", "गिरफ्तार", "टूटा",
    "बीमा", "पुलिस", "आग", "मदद",
    # Telugu equivalents
    "ప్రమాదం", "అత్యవసర", "ఆసుపత్రి", "జబ్బు", "మరణం", "పెళ్లి", "పుట్టినరోజు",
    "పరీక్ష", "ఉద్యోగం", "ప్రేమ", "భయం", "కోపం", "బీమా", "పోలీసు", "అగ్ని",
    "సహాయం",
}


def normalize(text: str) -> str:
    return " ".join(WORD.findall(text or "")).strip()


def toks(text: str) -> list:
    return [t.casefold() for t in WORD.findall(text or "")]


def content_toks(text: str) -> list:
    all_ = toks(text)
    kept = [t for t in all_ if t not in STOP]
    return kept or all_


class BM25:
    """Incremental BM25 with inverted index; supports removal (needed for purge)."""

    def __init__(self, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.df = Counter()
        self.postings = {}   # term -> set(doc_id)
        self.docs = {}       # doc_id -> Counter(term)
        self.lens = {}
        self.total_len = 0

    def add(self, doc_id, terms):
        tf = Counter(terms)
        self.docs[doc_id] = tf
        self.lens[doc_id] = len(terms)
        self.total_len += len(terms)
        for t in tf:
            self.df[t] += 1
            self.postings.setdefault(t, set()).add(doc_id)

    def remove(self, doc_id):
        tf = self.docs.pop(doc_id, None)
        if tf is None:
            return
        self.total_len -= self.lens.pop(doc_id)
        for t in tf:
            self.df[t] -= 1
            self.postings[t].discard(doc_id)
            if self.df[t] <= 0:
                del self.df[t]
                del self.postings[t]

    def candidates(self, q_terms):
        out = set()
        for t in set(q_terms):
            out |= self.postings.get(t, set())
        return out

    def score(self, doc_id, q_terms):
        tf = self.docs.get(doc_id)
        if not tf:
            return 0.0
        n = len(self.docs)
        avg = self.total_len / n if n else 1.0
        dl = self.lens[doc_id]
        s = 0.0
        for t in set(q_terms):
            f = tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / avg))
        return s


@dataclass
class Memory:
    id: int
    text: str
    kind: str                    # semantic | reflection | procedural
    importance: float            # 0..1 (LLM-rated 1-10/10 ideally; heuristic fallback)
    recorded_at: float           # transaction time (days) — when we learned it
    valid_from: float            # valid time — when it became true
    valid_to: Optional[float] = None
    status: str = "active"       # active | superseded | forgotten
    first_seen: float = 0.0
    presentations: int = 0
    accesses: list = field(default_factory=list)  # last MAX_TRACES presentation times
    sources: tuple = ()          # provenance (memory ids) for reflections
    superseded_by: Optional[int] = None
    sensitivity: str = "ordinary"
    source: Optional[str] = None


class MemoryStore:
    WORKING_CAPACITY = 7
    MAX_TRACES = 32
    # ACT-R retrievability: P = sigmoid((B - TAU) / S); below P_MIN = inaccessible.
    # Calibrated so a once-seen mundane fact (imp 0.3) is inaccessible by ~day 20,
    # a salient one (imp 0.9) still accessible at day 30, and two spaced presentations
    # (day 0, day 15) keep a mundane fact alive at day 30. Fit these on your data.
    TAU, S, P_MIN = -1.2, 0.3, 0.2
    W_REL, W_ACT, W_IMP = 0.6, 0.25, 0.15
    LEXICAL_UPDATE_SIM = 0.8
    REFLECT_THRESHOLD = 3.0      # summed importance since last reflection

    def __init__(
        self,
        embedder: Optional[Callable[[str], Sequence[float]]] = None,
        extractor: Optional[Callable[[str, list], list]] = None,
        resolver: Optional[Callable[[str, list], tuple]] = None,
        reflector: Optional[Callable[[list], list]] = None,
        importance_fn: Optional[Callable[[str], float]] = None,
    ):
        self.embedder, self.extractor = embedder, extractor
        self.resolver, self.reflector = resolver, reflector
        self.importance_fn = importance_fn
        self.memories: dict = {}
        self.bm25 = BM25()
        self.vecs: dict = {}
        self._by_text: dict = {}
        self.working = deque(maxlen=self.WORKING_CAPACITY)
        self.tombstones: list = []
        self.day = 0.0
        self._pending_importance = 0.0
        self._next_id = 1

    # ---------- clock ----------
    def tick(self, days: float):
        self.day += days

    # ---------- ACT-R ----------
    def _decay(self, m: Memory) -> float:
        return 0.6 - 0.3 * m.importance          # salient memories decay slower

    def _activation(self, m: Memory) -> float:
        d = self._decay(m)
        total = sum((max(self.day - t, 0.0) + 0.02) ** -d for t in m.accesses)
        older = m.presentations - len(m.accesses)
        if older > 0:                            # ACT-R "optimized learning" for truncated history
            span = max(self.day - m.first_seen, 0.0) + 0.02
            total += older / (1 - d) * span ** -d
        return math.log(total) if total > 0 else -math.inf

    def retrievability(self, m: Memory) -> float:
        return 1.0 / (1.0 + math.exp(-(self._activation(m) - self.TAU) / self.S))

    def _rehearse(self, m: Memory):
        m.presentations += 1
        m.accesses.append(self.day)
        if len(m.accesses) > self.MAX_TRACES:
            del m.accesses[0]

    # ---------- write path ----------
    def hear(self, utterance: str):
        """Working memory only. No implicit LTM rehearsal here (see ingest/resolve)."""
        self.working.append(utterance)

    def ingest(self, utterance: str, source=None) -> list:
        """hear + extract + resolve. Run this OFF the voice critical path (async)."""
        self.hear(utterance)
        facts = self.extractor(utterance, list(self.working)) if self.extractor else [utterance]
        return [m for m in (self.add(f, source=source) for f in facts) if m]

    def _importance(self, text: str) -> float:
        if self.importance_fn:
            return max(0.0, min(1.0, self.importance_fn(text)))
        return 0.9 if set(toks(text)) & SALIENT else 0.3

    def _neighbours(self, text: str, k=5) -> list:
        return self.retrieve(text, k=k, rehearse=False)

    def _resolve(self, text: str, neighbours: list) -> tuple:
        """-> (op, target). LLM resolver (Mem0-style) if provided, else lexical.

        Lexical fallback uses RAW-token Jaccard (v1 behavior): stopword-stripped
        Jaccard scores 0.67 on the Hinglish conflict pair our oracle asserts and
        misses the UPDATE; raw scores 0.8 and catches it. BM25 indexing still
        uses content tokens — only the conflict decision keeps stopwords.
        """
        if self.resolver:
            op, target_id = self.resolver(text, [(n.id, n.text) for n in neighbours])
            return op, self.memories.get(target_id) if target_id is not None else None
        exact = self._by_text.get(text.casefold())
        if exact and exact.status == "active":
            return "NOOP", exact
        a = set(toks(text))
        for n in neighbours:
            b = set(toks(n.text))
            if a and b and len(a & b) / len(a | b) >= self.LEXICAL_UPDATE_SIM:
                return "UPDATE", n
        return "ADD", None

    def add(self, text, importance=None, kind="semantic", valid_from=None,
            sources=(), sensitivity="ordinary", source=None) -> Optional[Memory]:
        text = normalize(text)
        if not text:
            return None
        op, target = self._resolve(text, self._neighbours(text))
        if op == "NOOP" and target is not None:
            self._rehearse(target)               # re-hearing a known fact = spaced repetition
            return target
        if op == "DELETE":
            if target is not None:               # LLM-decided: SOFT invalidation only
                self._invalidate(target, by=None)
            return None
        imp = importance if importance is not None else self._importance(text)
        m = Memory(id=self._next_id, text=text, kind=kind, importance=imp,
                   recorded_at=self.day, valid_from=self.day if valid_from is None else valid_from,
                   first_seen=self.day, sources=tuple(sources), sensitivity=sensitivity, source=source)
        self._next_id += 1
        self.memories[m.id] = m
        self._by_text[text.casefold()] = m
        self.bm25.add(m.id, content_toks(text))
        if self.embedder:
            self.vecs[m.id] = list(self.embedder(text))
        self._rehearse(m)
        if op == "UPDATE" and target is not None:
            self._invalidate(target, by=m)
        self._pending_importance += imp
        return m

    def _invalidate(self, old: Memory, by: Optional[Memory]):
        """Bi-temporal supersede: stays queryable with as_of=, never in current context."""
        old.status = "superseded"
        old.valid_to = self.day
        old.superseded_by = by.id if by else None

    # ---------- hard forget ----------
    def forget(self, text_or_id) -> bool:
        m = (self.memories.get(text_or_id) if isinstance(text_or_id, int)
             else self._by_text.get(normalize(text_or_id).casefold()))
        if m is None or m.status == "forgotten":
            return False
        key = m.text.casefold()
        victims = [m] + [o for o in self.memories.values()
                         if m.id in o.sources and o.status != "forgotten"]
        for v in victims:
            self._purge(v)
        self.working = deque((u for u in self.working if key not in normalize(u).casefold()),
                             maxlen=self.WORKING_CAPACITY)
        self.tombstones.append((m.id, self.day))
        return True

    def _purge(self, m: Memory):
        self.bm25.remove(m.id)
        self.vecs.pop(m.id, None)
        self._by_text.pop(m.text.casefold(), None)
        m.text, m.accesses, m.sources = "", [], ()
        m.presentations = 0
        m.status = "forgotten"

    # ---------- read path ----------
    def _visible(self, m: Memory, as_of: Optional[float]) -> bool:
        if m.status == "forgotten":
            return False
        if as_of is None:
            return m.status == "active"
        return m.valid_from <= as_of and (m.valid_to is None or as_of < m.valid_to)

    @staticmethod
    def _cos(a, b) -> float:
        num = sum(x * y for x, y in zip(a, b))
        den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
        return num / den if den else 0.0

    def retrieve(self, query: str, k=3, as_of: Optional[float] = None, rehearse=True) -> list:
        q_terms = content_toks(query)
        cands = self.bm25.candidates(q_terms)
        qvec = list(self.embedder(query)) if self.embedder else None
        if qvec is not None:
            cands |= set(self.vecs)              # brute force; swap for hnswlib/faiss past ~20k
        raw = {}
        for mid in cands:
            m = self.memories[mid]
            if not self._visible(m, as_of):
                continue
            bm = self.bm25.score(mid, q_terms)
            cs = max(self._cos(qvec, self.vecs[mid]), 0.0) if qvec is not None else 0.0
            raw[mid] = (bm, cs)
        if not raw:
            return []
        max_bm = max(b for b, _ in raw.values()) or 1.0
        scored = []
        for mid, (bm, cs) in raw.items():
            m = self.memories[mid]
            rel = 0.5 * bm / max_bm + 0.5 * cs if qvec is not None else bm / max_bm
            if rel <= 0:
                continue
            p = self.retrievability(m)
            if as_of is None and p < self.P_MIN:
                continue                          # inaccessible (not deleted): can be reminded/re-learned
            scored.append((self.W_REL * rel + self.W_ACT * p + self.W_IMP * m.importance, mid, m))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)   # ties -> newest first
        out = [m for _, _, m in scored[:k]]
        if rehearse:
            for m in out:
                self._rehearse(m)
        return out

    # ---------- consolidation ----------
    def consolidate(self) -> list:
        """Reflection (Generative Agents): once enough importance has accumulated,
        derive higher-level memories; provenance lets forget() cascade."""
        if not self.reflector or self._pending_importance < self.REFLECT_THRESHOLD:
            return []
        recent = sorted((m for m in self.memories.values()
                         if m.status == "active" and m.kind != "reflection"),
                        key=lambda m: m.recorded_at, reverse=True)[:50]
        insights = self.reflector([(m.id, m.text) for m in recent])   # -> [(text, [source_ids])]
        self._pending_importance = 0.0
        out = [self.add(t, kind="reflection", sources=tuple(src), importance=0.7) for t, src in insights]
        return [m for m in out if m]

    def context_block(self, query: str, k=3) -> str:
        retrieved = self.retrieve(query, k=k)
        recent = list(self.working)[-2:]
        lines = []
        if retrieved:
            lines.append("MEMORY:")
            lines.extend(f"- {m.text}" for m in retrieved)
        if recent:
            lines.append("RECENT:")
            lines.extend(f"- {u}" for u in recent)
        return "\n".join(lines)
