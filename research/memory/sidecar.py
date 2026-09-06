"""Memory sidecar: serves one MemoryStore over local HTTP (stdlib only).

Single-user demo store ("local"); durable via SQLite (see store_db.py).

Endpoints (JSON):
  GET  /healthz                 -> {"status": "ok", "facts": N, "llm_enrichment": bool}
  POST /add     {"text": "..."} -> {"id": N, "text": "..."}
  POST /forget  {"text": "..."} -> {"forgot": true|false}
  GET  /facts                   -> {"facts": [{"id": N, "text": "..."}]}
  POST /context {"query": "..."} -> {"block": "MEMORY:\\n- ..."} ("" when empty)
  POST /observe {"utterance": "..."} -> {"captured": [{...}]} (rules sync, LLM async)

Fixes over the previous version:
  * Persistence was `pickle` — arbitrary code execution on load, and any
    change to the dataclasses silently wiped every stored fact. Now SQLite
    with a versioned schema.
  * `save()` swallowed every exception, so a full disk looked like success.
  * Request bodies were unbounded: `Content-Length: 10000000000` allocated
    until the process died.
  * The single-threaded HTTPServer meant one slow client blocked the gateway's
    recall call, which stalled every chat turn behind it.
  * Errors escaping a handler killed the connection with a stack trace and no
    response; the Go client then reported "sidecar unreachable".
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory_v2 import Memory, MemoryStore  # noqa: E402
from store_db import FactDB  # noqa: E402
from extract import extract_facts  # noqa: E402
from llm_extract import enabled as llm_enabled  # noqa: E402
from llm_extract import extract_facts_llm  # noqa: E402

HOST = os.environ.get("MEMORY_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMORY_PORT", "18081"))
DB_PATH = Path(os.environ.get("MEMORY_DB", Path(__file__).with_name("memory.db")))
MAX_BODY_BYTES = 1 << 20  # 1 MiB: a "fact" is a sentence, not a file
MAX_TEXT_CHARS = 4000

log = logging.getLogger("memory-sidecar")


class Enricher:
    """Background worker running the LLM extractor off the request path.

    One thread and a bounded queue. When the queue is full the turn is
    dropped rather than queued: enrichment is a best-effort bonus, and an
    unbounded backlog would turn a slow LLM into unbounded memory growth and
    facts landing minutes after they were said.
    """

    MAX_PENDING = 32

    def __init__(self, store: "DurableStore"):
        self.store = store
        self.queue: queue.Queue = queue.Queue(maxsize=self.MAX_PENDING)
        self.dropped = 0
        self._thread = threading.Thread(
            target=self._run, name="memory-enricher", daemon=True
        )
        self._thread.start()

    def submit(
        self, utterance: str, context: str, known: set[str], raw_ids: list[int]
    ) -> bool:
        try:
            self.queue.put_nowait((utterance, context, known, raw_ids))
            return True
        except queue.Full:
            self.dropped += 1
            log.warning("enrichment queue full, dropped turn (%d total)", self.dropped)
            return False

    def _run(self) -> None:
        while True:
            utterance, context, known, raw_ids = self.queue.get()
            try:
                self.store.enrich(utterance, context, known, raw_ids)
            except Exception:
                # A crashed worker would silently disable enrichment for the
                # process lifetime; log and keep serving.
                log.exception("enrichment worker error")
            finally:
                self.queue.task_done()


class DurableStore:
    """MemoryStore + SQLite, guarded by one lock.

    MemoryStore is not thread-safe (it mutates dicts, a deque and BM25
    postings), and the server is now threaded, so every entry point is
    serialized here. The lock is re-entrant because context_block() retrieves,
    which rehearses, which persists.
    """

    def __init__(self, db: FactDB):
        self.db = db
        self.lock = threading.RLock()
        self.store = MemoryStore()
        self.enricher: Enricher | None = None
        self._restore()

    def _restore(self) -> None:
        """Rebuild the in-memory store from the durable fact log.

        Derived structures (BM25 index, vectors) are reconstructed rather than
        stored, so they can never drift out of sync with the facts.
        """
        rows = self.db.load_facts()
        for row in rows:
            m = Memory(
                id=row["id"], text=row["text"], kind=row["kind"],
                importance=row["importance"], recorded_at=row["recorded_at"],
                valid_from=row["valid_from"], valid_to=row["valid_to"],
                status=row["status"], first_seen=row["first_seen"],
                presentations=row["presentations"], accesses=list(row["accesses"]),
                sources=tuple(row["sources"]), superseded_by=row["superseded_by"],
                sensitivity=row["sensitivity"], source=row["source"],
            )
            self.store.memories[m.id] = m
            if m.status != "forgotten" and m.text:
                self.store._by_text[m.text.casefold()] = m
                self.store.bm25.add(m.id, _content_toks(m.text))

        state = self.db.load_state()
        if state:
            self.store.day = state["day"]
            self.store._next_id = max(
                state["next_id"],
                max((m.id for m in self.store.memories.values()), default=0) + 1,
            )
            self.store._pending_importance = state["pending_importance"]
            for utterance in state["working"]:
                self.store.working.append(utterance)
        else:
            self.store._next_id = (
                max((m.id for m in self.store.memories.values()), default=0) + 1
            )
        log.info("restored %d facts from %s", len(rows), self.db.path)

    def _persist_state(self) -> None:
        self.db.save_state(
            self.store.day, self.store._next_id,
            self.store._pending_importance, list(self.store.working),
        )

    def add(self, text: str):
        with self.lock:
            m = self.store.add(text)
            if m is not None:
                self.db.upsert_fact(m)
                # add() can supersede a neighbour; persist those too.
                for other in self.store.memories.values():
                    if other.superseded_by == m.id:
                        self.db.upsert_fact(other)
            self._persist_state()
            return m

    def _store_fact(self, text: str, source: str | None = None) -> dict | None:
        """Add one fact and persist it. Caller holds the lock.

        Returns the fact only when it is genuinely new — re-hearing a known
        one is a NOOP rehearsal, and reporting it as "learned" every time
        would be noise.
        """
        before = len(self.store.memories)
        m = self.store.add(text, source=source)
        if m is None:
            return None
        self.db.upsert_fact(m)
        for other in self.store.memories.values():
            if other.superseded_by == m.id:
                self.db.upsert_fact(other)
        if len(self.store.memories) <= before:
            return None
        return {"id": m.id, "text": m.text}

    def observe(self, utterance: str) -> list[dict]:
        """Automatic capture from a conversational turn.

        Runs the utterance through the rule extractor and stores only what
        looks like an enduring first-person fact. Everything the user says
        also enters working memory, so "RECENT:" context works even for turns
        that are not worth storing permanently.

        When an LLM extractor is configured, the turn is additionally queued
        for background enrichment. The rules answer now; the LLM catches what
        they missed a moment later. Nothing waits on the network.
        """
        with self.lock:
            self.store.hear(utterance)
            context = "\n".join(list(self.store.working)[-4:-1])
            captured = []
            for text in extract_facts(utterance, list(self.store.working)):
                fact = self._store_fact(text, source="rules")
                if fact:
                    captured.append(fact)
            self._persist_state()

        if self.enricher is not None:
            already = {m.text for m in self.store.memories.values() if m.text}
            # Ids the rules stored verbatim from THIS utterance. If the LLM
            # produces a cleaner rendering of the same turn, these are
            # superseded rather than left alongside it as near-duplicates.
            raw_ids = [f["id"] for f in captured]
            self.enricher.submit(utterance, context, already, raw_ids)
        return captured

    def enrich(
        self,
        utterance: str,
        context: str,
        known: set[str],
        raw_ids: list[int] | None = None,
    ) -> list[dict]:
        """Second-pass LLM capture. Runs on the worker thread, never a turn."""
        facts = extract_facts_llm(utterance, context, known)
        if not facts:
            return []
        with self.lock:
            stored = [f for f in (self._store_fact(t, source="llm") for t in facts) if f]
            # The rules store the utterance verbatim ("yeah I have been at the
            # hospital fifteen years now"); the LLM rewrites it into a clean
            # fact. Keeping both leaves two entries saying the same thing, and
            # the raw one is the worse of the two. Supersede it — a soft,
            # bi-temporal invalidation, so history stays queryable with as_of.
            if stored and raw_ids:
                by = self.store.memories.get(stored[0]["id"])
                for raw_id in raw_ids:
                    raw = self.store.memories.get(raw_id)
                    if raw is None or raw.status != "active":
                        continue
                    if raw.text.casefold() != utterance.strip().casefold():
                        continue  # rules found a real fact, not the raw turn
                    self.store._invalidate(raw, by=by)
                    self.db.upsert_fact(raw)
                    log.info("superseded raw capture %d with refined fact", raw_id)
            self._persist_state()
        if stored:
            log.info("llm enrichment stored %d fact(s): %s",
                     len(stored), [f["text"] for f in stored])
        return stored

    def forget(self, text: str) -> bool:
        with self.lock:
            victims = self._victims(text)
            ok = self.store.forget(text)
            if ok:
                # Hard forget must remove the text from disk, not just from
                # RAM. The pickle version rewrote a snapshot whose purged
                # rows still carried empty-but-present records; here the row
                # is deleted outright and a tombstone records the event.
                for fact_id in victims:
                    self.db.delete_fact(fact_id, self.store.day)
            self._persist_state()
            return ok

    def _victims(self, text: str) -> list[int]:
        from memory_v2 import normalize

        m = self.store._by_text.get(normalize(text).casefold())
        if m is None:
            return []
        return [m.id] + [
            o.id for o in self.store.memories.values()
            if m.id in o.sources and o.status != "forgotten"
        ]

    def facts(self) -> list[dict]:
        with self.lock:
            return self.db.active_facts()

    def context_block(self, query: str) -> str:
        with self.lock:
            block = self.store.context_block(query)
            # retrieve() rehearses, which updates activation traces; persist
            # so recall history survives a restart.
            for m in self.store.memories.values():
                if m.status == "active" and m.text:
                    self.db.upsert_fact(m)
            self._persist_state()
            return block

    def count(self) -> int:
        with self.lock:
            return len(self.db.active_facts())


def _content_toks(text: str):
    from memory_v2 import content_toks

    return content_toks(text)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "awaaz-memory/2.0"

    store: DurableStore  # injected on the server instance

    # ---------- plumbing ----------

    def _send(self, obj, code: int = 200) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, code: int, message: str) -> None:
        self._send({"error": {"code": code, "message": message}}, code)

    def _body(self) -> dict | None:
        """Read and parse a JSON body, or None if it is unusable.

        The body is always drained: leaving bytes in the socket desynchronizes
        the next request on a keep-alive connection.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            return None
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _text_arg(self, body: dict) -> str | None:
        value = body.get("text")
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value or len(value) > MAX_TEXT_CHARS:
            return None
        return value

    # ---------- routes ----------

    def do_GET(self) -> None:
        try:
            if self.path == "/healthz":
                return self._send({
                    "status": "ok",
                    "facts": self.store.count(),
                    "llm_enrichment": self.store.enricher is not None,
                })
            if self.path == "/facts":
                return self._send({"facts": self.store.facts()})
            return self._error(404, "not found")
        except Exception:
            # An unhandled error used to drop the connection with no reply,
            # which the Go client reported as "sidecar unreachable".
            log.exception("GET %s failed", self.path)
            return self._error(500, "internal error")

    def do_POST(self) -> None:
        try:
            body = self._body()
            if body is None:
                return self._error(400, "invalid or oversized JSON body")

            if self.path == "/add":
                text = self._text_arg(body)
                if text is None:
                    return self._error(422, "text must be a non-empty string")
                m = self.store.add(text)
                if m is None:
                    return self._error(422, "text contained no indexable content")
                return self._send({"id": m.id, "text": m.text})

            if self.path == "/forget":
                text = self._text_arg(body)
                if text is None:
                    return self._error(422, "text must be a non-empty string")
                return self._send({"forgot": self.store.forget(text)})

            if self.path == "/context":
                query = body.get("query")
                if not isinstance(query, str) or not query.strip():
                    # An empty query is a valid no-op, not an error: the
                    # gateway calls this on every turn.
                    return self._send({"block": ""})
                return self._send({"block": self.store.context_block(query.strip())})

            if self.path == "/observe":
                # Automatic per-turn capture (rules sync, LLM in background).
                # Fire-and-forget from the gateway: the reply never waits.
                # NOTE: reads "utterance", not "text" — _text_arg serves the
                # /add and /forget routes and would 422 every observe call.
                utterance = body.get("utterance")
                if not isinstance(utterance, str):
                    return self._error(422, "utterance must be a non-empty string")
                utterance = utterance.strip()
                if not utterance or len(utterance) > MAX_TEXT_CHARS:
                    return self._error(422, "utterance must be a non-empty string")
                return self._send({"captured": self.store.observe(utterance)})

            return self._error(404, "not found")
        except Exception:
            log.exception("POST %s failed", self.path)
            return self._error(500, "internal error")

    def log_message(self, fmt: str, *args) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("MEMORY_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db = FactDB(DB_PATH)
    store = DurableStore(db)

    # LLM enrichment is opt-in: without MEMORY_LLM_URL/KEY the sidecar runs
    # rules-only and behaves exactly as before.
    if llm_enabled():
        store.enricher = Enricher(store)
        log.info("llm enrichment enabled (model=%s)", os.environ.get(
            "MEMORY_LLM_MODEL", "sarvam-105b-conversations"))
    else:
        log.info("llm enrichment disabled (set MEMORY_LLM_URL and MEMORY_LLM_KEY)")

    # ThreadingHTTPServer: the single-threaded version serialized every
    # request, so one slow /context call stalled all chat traffic behind it.
    Handler.store = store
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True

    def shutdown(signum, _frame):
        log.info("shutting down (signal %s)", signum)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("memory sidecar listening on http://%s:%d (db=%s)", HOST, PORT, DB_PATH)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        db.close()
        log.info("stopped")


if __name__ == "__main__":
    main()
