"""eval_locomo.py — LoCoMo benchmark harness for memory_v2.MemoryStore.

Data (not bundled):
    git clone https://github.com/snap-research/locomo
    cp locomo/data/locomo10.json research/benchmark/

Modes
  retrieval-only (no LLM, no network): evidence recall@k + latency
    python eval_locomo.py --data research/benchmark/locomo10.json
  end-to-end (memory -> answer -> judge), any OpenAI-compatible endpoint:
    OPENAI_API_KEY=... python eval_locomo.py --data ... --answer-model gpt-4o-mini --judge-model gpt-4o-mini
  LLM write path (Mem0-style extract + resolve; ~1 call per turn, ~6k calls total):
    ... --extract
  strong baseline you must beat (whole transcript in the prompt):
    ... --mode full
  plumbing check without the dataset:
    python eval_locomo.py --synthetic

Decay note: LoCoMo states each fact once and asks about it up to months later,
so ACT-R inaccessibility (P_MIN) is penalised by construction. Default here is
benchmark parity (P_MIN=0). Pass --human-decay to measure what forgetting costs.

Writes results/locomo_eval.json (summary) and results/locomo_rows.jsonl (per question).
"""

import argparse
import hashlib
import json
import os
import re
import statistics
import string
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from memory_v2 import MemoryStore  # noqa: E402

# LoCoMo category ids. Verify against the printed distribution: the largest
# non-adversarial bucket (~840 q) ingle-hop, adversarial is ~450.
CATEGORY = {1: "multi_hop", 2: "temporal", 3: "open_domain", 4: "single_hop", 5: "adversarial"}
DATE_FORMATS = ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %B %Y", "%d %B, %Y", "%d %B %Y", "%B %d, %Y")

# ----------------------------------------------------------------------------- prompts
ANSWER_SYS = (
    "You answer questions about a conversation between two people using ONLY the provided "
    "memories. Answer with a short phrase (a few words or a date). If the memories do not "
    "contain the answer, reply exactly: No information available"
)
JUDGE_SYS = "You grade question answering. Output exactly one word: CORRECT or WRONG."
JUDGE_USER = (
    "Question: {q}\nGold answer: {gold}\nGenerated answer: {pred}\n\n"
    "Label CORRECT if the generated answer conveys the same essential information as the gold "
    "answer (paraphrase, extra detail, or a date at the gold's granularity are fine). "
    "Otherwise label WRONG."
)
EXTRACT_SYS = (
    "Extract atomic, self-contained facts from the LATEST utterance of a conversation. Write each "
    "fact in third person, present tense, naming the speaker, and keep the date prefix exactly as "
    "given. Return a JSON list of strings. Return [] for chit-chat with nothing worth remembering."
)
RESOLVE_SYS = (
    "You maintain a memory store. Given a NEW fact and EXISTING memories, choose one: "
    "ADD (genuinely new), UPDATE (new fact corrects/replaces one existing memory about the same "
    "thing), NOOP (already known), DELETE (new fact says an existing memory is no longer true and "
    "gives no replacement). Reply with JSON only: {\"op\": \"ADD|UPDATE|NOOP|DELETE\", \"target\": id_or_null}"
)


# ----------------------------------------------------------------------------- llm client
class LLM:
    """Minimal OpenAI-compatible chat client with on-disk cache (stdlib only)."""

    def __init__(self, model, cache_path):
        self.model = model
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.key = os.environ.get("OPENAI_API_KEY", "none")
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.calls = 0

    def chat(self, system, user, max_tokens=200):
        h = hashlib.sha256(json.dumps([self.model, system, user]).encode()).hexdigest()
        if h in self.cache:
            return self.cache[h]
        body = json.dumps({
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = json.load(r)["choices"][0]["message"]["content"].strip()
                break
            except (urllib.error.URLError, KeyError, json.JSONDecodeError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        self.calls += 1
        self.cache[h] = out
        if self.calls % 50 == 0:
            self.flush()
        return out

    def flush(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache))


def make_extractor(llm):
    def extract(utterance, working):
        ctx = "\n".join(working[:-1][-4:])
        out = llm.chat(EXTRACT_SYS, f"Previous turns:\n{ctx}\n\nLatest utterance:\n{utterance}\n\nJSON list:", 400)
        try:
            facts = json.loads(out[out.find("["): out.rfind("]") + 1])
        except (ValueError, json.JSONDecodeError):
            facts = [ln.strip("-• ").strip() for ln in out.splitlines()]
        return [f for f in facts if isinstance(f, str) and f.strip()]
    return extract


def make_resolver(llm):
    def resolve(text, neighbours):
        if not neighbours:
            return "ADD", None
        listing = "\n".join(f"[{i}] {t}" for i, t in neighbours)
        out = llm.chat(RESOLVE_SYS, f"NEW fact: {text}\n\nEXISTING memories:\n{listing}\n\nJSON:", 60)
        try:
            j = json.loads(out[out.find("{"): out.rfind("}") + 1])
            op = str(j.get("op", "ADD")).upper()
            tgt = j.get("target")
            tgt = int(tgt) if tgt is not None and str(tgt).lstrip("-").isdigit() else None
            if op not in {"ADD", "UPDATE", "NOOP", "DELETE"} or (op != "ADD" and tgt is None):
                return "ADD", None
            return op, tgt
        except (ValueError, json.JSONDecodeError):
            return "ADD", None
    return resolve


def make_embedder(name):
    from sentence_transformers import SentenceTransformer  # optional dep
    model = SentenceTransformer(name)
    return lambda text: model.encode(text, normalize_embeddings=True).tolist()


# ----------------------------------------------------------------------------- data
def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    m = re.search(r"(\d{1,2}) (\w+),? (\d{4})", s)
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%d %B %Y")
        except ValueError:
            return None
    return None


def sessions(conv):
    keys = sorted((k for k in conv if re.fullmatch(r"session_\d+", k)), key=lambda k: int(k.split("_")[1]))
    for k in keys:
        yield k, conv.get(f"{k}_date_time"), conv[k]


def turn_text(t):
    text = (t.get("text") or "").strip()
    cap = (t.get("blip_caption") or "").strip()
    if cap:
        text = f"{text} [shared a photo: {cap}]".strip()
    return text


def transcript(conv):
    lines = []
    for key, dt_str, turns in sessions(conv):
        lines.append(f"--- {dt_str or key} ---")
        lines.extend(f"{t['speaker']}: {turn_text(t)}" for t in turns if turn_text(t))
    return "\n".join(lines)


def synthetic():
    return [{
        "sample_id": "synthetic-1",
        "conversation": {
            "speaker_a": "Asha", "speaker_b": "Ravi",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "Asha", "dia_id": "D1:1", "text": "I just moved to Hyderabad for a new job at Infosys."},
                {"speaker": "Ravi", "dia_id": "D1:2", "text": "Congrats! I adopted a beagle named Bruno last week."},
            ],
            "session_2_date_time": "7:10 pm on 20 June, 2023",
            "session_2": [
                {"speaker": "Asha", "dia_id": "D2:1", "text": "Update: I left Infosys and joined Zoho in Chennai."},
                {"speaker": "Ravi", "dia_id": "D2:2", "text": "Bruno is finally house-trained."},
            ],
        },
        "qa": [
            {"question": "Where does Asha work now?", "answer": "Zoho", "evidence": ["D2:1"], "category": 4},
            {"question": "Which company did Asha work at before Zoho?", "answer": "Infosys", "evidence": ["D1:1", "D2:1"], "category": 1},
            {"question": "When did Ravi adopt Bruno?", "answer": "early May 2023", "evidence": ["D1:2"], "category": 2},
            {"question": "What is Ravi's cat's name?", "adversarial_answer": "No information available", "evidence": [], "category": 5},
        ],
    }]


# ----------------------------------------------------------------------------- store
def build_store(sample, args, llm_write, embedder):
    kwargs = {"embedder": embedder}
    if llm_write:
        kwargs["extractor"] = make_extractor(llm_write)
        kwargs["resolver"] = make_resolver(llm_write)
    else:
        kwargs["resolver"] = lambda text, neigh: ("ADD", None)   # raw turns are episodic: never supersede
    store = MemoryStore(**kwargs)
    if not args.human_decay:
        store.P_MIN = 0.0
    t0 = None
    n_turns = n_mem = 0
    for key, dt_str, turns in sessions(sample["conversation"]):
        dt = parse_dt(dt_str)
        if dt is not None:
            t0 = t0 or dt
            store.day = (dt - t0).total_seconds() / 86400.0
        else:
            store.day += 7.0
        stamp = dt_str or key
        for t in turns:
            text = turn_text(t)
            if not text:
                continue
            n_turns += 1
            n_mem += len(store.ingest(f"{stamp} — {t['speaker']}: {text}", source=t.get("dia_id")))
    return store, n_turns, n_mem


# ----------------------------------------------------------------------------- metrics
def norm_ans(s):
    s = str(s).lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def f1(pred, gold):
    p, g = norm_ans(pred).split(), norm_ans(gold).split()
    if not p or not g:
        return float(p == g)
    n = sum((Counter(p) & Counter(g)).values())
    if n == 0:
        return 0.0
    pr, rc = n / len(p), n / len(g)
    return 2 * pr * rc / (pr + rc)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research/benchmark/locomo10.json")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--mode", choices=["memory", "full"], default="memory")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--answer-model", default=None)
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--extract", action="store_true", help="LLM extract+resolve on write (uses --answer-model)")
    ap.add_argument("--embed", default=None, help="sentence-transformers model, e.g. paraphrase-multilingual-MiniLM-L12-v2")
    ap.add_argument("--human-decay", action="store_true", help="keep ACT-R P_MIN (measure cost of forgetting)")
    ap.add_argument("--include-adversarial", action="store_true")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--limit-qa", type=int, default=None, help="per sample, for quick runs")
    ap.add_argument("--out", default="results/locomo_eval.json")
    args = ap.parse_args()

    data = synthetic() if args.synthetic else json.loads(Path(args.data).read_text(encoding="utf-8"))
    if args.samples:
        data = data[: args.samples]

    dist = Counter(CATEGORY.get(qa.get("category"), "unknown") for s in data for qa in s["qa"])
    print(f"loaded {len(data)} conversations; category distribution: {dict(dist)}")

    answer_llm = LLM(args.answer_model, "results/llm_cache.json") if args.answer_model else None
    judge_llm = LLM(args.judge_model, "results/llm_cache.json") if args.judge_model else None
    if args.extract and not answer_llm:
        sys.exit("--extract needs --answer-model")
    embedder = make_embedder(args.embed) if args.embed else None

    rows, lat_ms, ingest_stats = [], [], []
    for sample in data:
        t = time.perf_counter()
        store, n_turns, n_mem = build_store(sample, args, answer_llm if args.extract else None, embedder)
        ingest_stats.append({"sample": sample.get("sample_id"), "turns": n_turns, "memories": n_mem,
                             "ingest_s": round(time.perf_counter() - t, 1)})
        full_ctx = transcript(sample["conversation"]) if args.mode == "full" else None

        qas = sample["qa"][: args.limit_qa] if args.limit_qa else sample["qa"]
        for qa in qas:
            cat = CATEGORY.get(qa.get("category"), "unknown")
            if cat == "adversarial" and not args.include_adversarial:
                continue
            q = qa["question"]
            gold = str(qa.get("answer", qa.get("adversarial_answer", "")))
            evidence = [str(e) for e in qa.get("evidence", []) or []]

            t = time.perf_counter()
            retrieved = store.retrieve(q, k=args.k, rehearse=False)
            ms = (time.perf_counter() - t) * 1000
            lat_ms.append(ms)
            got = {m.source for m in retrieved}
            ev_recall = mean([float(e in got) for e in evidence]) if evidence else None

            row = {"sample": sample.get("sample_id"), "category": cat, "question": q, "gold": gold,
                   "evidence": evidence, "retrieved": [m.source for m in retrieved],
                   "evidence_recall": ev_recall, "retrieve_ms": round(ms, 2)}
            if answer_llm:
                ctx = full_ctx if full_ctx is not None else "\n".join(f"- {m.text}" for m in retrieved) or "(none)"
                label = "Conversation" if full_ctx is not None else "Memories"
                pred = answer_llm.chat(ANSWER_SYS, f"{label}:\n{ctx}\n\nQuestion: {q}\nAnswer:", 80)
                row["pred"] = pred
                row["f1"] = round(f1(pred, gold), 4)
                if judge_llm:
                    verdict = judge_llm.chat(JUDGE_SYS, JUDGE_USER.format(q=q, gold=gold, pred=pred), 5)
                    row["judge"] = float(verdict.strip().upper().startswith("CORRECT"))
            rows.append(row)
        print(f"  {sample.get('sample_id')}: {n_turns} turns -> {n_mem} memories, {len(qas)} q")

    for llm in (answer_llm, judge_llm):
        if llm:
            llm.flush()

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    by_cat["ALL"] = rows

    def agg(rs):
        return {"n": len(rs),
                "evidence_recall@k": mean([r["evidence_recall"] for r in rs]),
                "f1": mean([r.get("f1") for r in rs]),
                "llm_judge_acc": mean([r.get("judge") for r in rs])}

    summary = {
        "config": {k: v for k, v in vars(args).items()},
        "ingest": ingest_stats,
        "retrieval_latency_ms": {"p50": pct(lat_ms, 0.5), "p95": pct(lat_ms, 0.95), "max": pct(lat_ms, 1.0)},
        "by_category": {c: agg(rs) for c, rs in by_cat.items()},
        "llm_calls": {"answer": answer_llm.calls if answer_llm else 0, "judge": judge_llm.calls if judge_llm else 0},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(out.with_name("locomo_rows.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n{'category':<14}{'n':>6}{'ev_recall':>11}{'f1':>8}{'judge':>8}")
    for c in ["single_hop", "multi_hop", "temporal", "open_domain", "adversarial", "unknown", "ALL"]:
        if c in by_cat:
            a = summary["by_category"][c]
            fmt = lambda v: "   -" if v is None else f"{v:.3f}"
            print(f"{c:<14}{a['n']:>6}{fmt(a['evidence_recall@k']):>11}{fmt(a['f1']):>8}{fmt(a['llm_judge_acc']):>8}")
    lat = summary["retrieval_latency_ms"]
    print(f"\nretrieve latency ms: p50={lat['p50']} p95={lat['p95']} max={lat['max']}")
    if lat["p95"] and lat["p95"] > 50:
        print("WARNING: p95 retrieval latency exceeds the 50 ms voice budget", file=sys.stderr)
    print(f"wrote {out} and {out.with_name('locomo_rows.jsonl')}")


if __name__ == "__main__":
    main()
