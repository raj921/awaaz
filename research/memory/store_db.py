"""SQLite persistence for the memory sidecar.

Replaces the previous `pickle.dumps(store)` snapshot, which had three
problems that made it unfit for anything but a single throwaway run:

  1. **Arbitrary code execution.** `pickle.loads` on a file under the working
     directory executes whatever is in it. Anyone able to write that file
     owned the process.
  2. **No schema.** The snapshot was the live object graph, so any change to
     `MemoryStore`/`Memory` — a renamed field, a new index — made every
     existing snapshot unloadable. The bare `except Exception: store =
     MemoryStore()` then *silently discarded the user's entire memory* on
     upgrade.
  3. **Not durable or concurrent.** The whole store was rewritten on every
     mutation with a non-atomic `write_bytes`; a crash mid-write truncated
     the file, and two writers raced.

The durable record here is the *fact log*, not the derived indexes. BM25
postings, vectors and activation traces are all rebuildable from the facts,
so they stay in memory and are reconstructed on boot. That keeps the schema
small, stable and inspectable with the `sqlite3` CLI.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY,
    text          TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'semantic',
    importance    REAL    NOT NULL DEFAULT 0.3,
    status        TEXT    NOT NULL DEFAULT 'active',
    recorded_at   REAL    NOT NULL DEFAULT 0,
    valid_from    REAL    NOT NULL DEFAULT 0,
    valid_to      REAL,
    first_seen    REAL    NOT NULL DEFAULT 0,
    presentations INTEGER NOT NULL DEFAULT 0,
    accesses      TEXT    NOT NULL DEFAULT '[]',
    sources       TEXT    NOT NULL DEFAULT '[]',
    superseded_by INTEGER,
    sensitivity   TEXT    NOT NULL DEFAULT 'ordinary',
    source        TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- The read path lists active facts in id order; without this index that is
-- a full scan plus a sort on every page load.
CREATE INDEX IF NOT EXISTS idx_facts_status_id ON facts(status, id);

-- Forget-by-text and the NOOP/duplicate check both look a fact up by its
-- normalized text.
CREATE INDEX IF NOT EXISTS idx_facts_text ON facts(text);

CREATE TABLE IF NOT EXISTS store_state (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    day      REAL    NOT NULL DEFAULT 0,
    next_id  INTEGER NOT NULL DEFAULT 1,
    pending_importance REAL NOT NULL DEFAULT 0,
    working  TEXT    NOT NULL DEFAULT '[]'
);

-- Hard forget is an auditable event: the fact row is deleted, the tombstone
-- proves it was removed on purpose and stays queryable.
CREATE TABLE IF NOT EXISTS tombstones (
    fact_id    INTEGER NOT NULL,
    day        REAL    NOT NULL,
    forgot_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns persisted per fact, in the order used by INSERT.
_FIELDS = (
    "id", "text", "kind", "importance", "status", "recorded_at", "valid_from",
    "valid_to", "first_seen", "presentations", "accesses", "sources",
    "superseded_by", "sensitivity", "source",
)


class FactDB:
    """Durable fact log behind the in-memory MemoryStore.

    Thread-safe: the sidecar's HTTP server handles one request per thread, and
    SQLite connections are not safe to share across threads without care.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL: readers never block the writer, and a crash cannot leave a
        # half-written database the way the old truncating snapshot could.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # secure_delete overwrites deleted content with zeros instead of just
        # marking the page free. Hard forget is a guarantee this project
        # asserts, and without this the forgotten text stayed plainly
        # readable in the file's freelist long after the row was gone.
        self._conn.execute("PRAGMA secure_delete=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Record and check the schema version.

        A future breaking change adds a branch here instead of throwing the
        user's data away, which is what the pickle path did implicitly.
        """
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            return
        found = int(row["value"])
        if found > SCHEMA_VERSION:
            raise RuntimeError(
                f"memory database schema v{found} is newer than this build "
                f"(v{SCHEMA_VERSION}); upgrade the sidecar instead of "
                f"downgrading the data"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- write path ----------

    def upsert_fact(self, m) -> None:
        """Persist one Memory. Called after every accepted mutation."""
        values = (
            m.id, m.text, m.kind, float(m.importance), m.status,
            float(m.recorded_at), float(m.valid_from),
            None if m.valid_to is None else float(m.valid_to),
            float(m.first_seen), int(m.presentations),
            json.dumps(list(m.accesses)), json.dumps(list(m.sources)),
            m.superseded_by, m.sensitivity, m.source,
        )
        placeholders = ", ".join("?" * len(_FIELDS))
        columns = ", ".join(_FIELDS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _FIELDS if c != "id")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO facts ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}, "
                f"updated_at=datetime('now')",
                values,
            )
            self._conn.commit()

    def upsert_many(self, memories: Iterable) -> None:
        for m in memories:
            self.upsert_fact(m)

    def delete_fact(self, fact_id: int, day: float) -> None:
        """Hard delete + tombstone. Forget must leave no recoverable text."""
        with self._lock:
            self._conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self._conn.execute(
                "INSERT INTO tombstones (fact_id, day) VALUES (?, ?)",
                (fact_id, float(day)),
            )
            self._conn.commit()
            # Checkpoint and truncate the WAL: the delete is durable in the
            # main database, but the pre-delete image of the row still sits
            # in the write-ahead log until it is rolled over.
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")

    def save_state(self, day: float, next_id: int, pending: float,
                   working: Iterable[str]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO store_state (id, day, next_id, pending_importance, working) "
                "VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET day=excluded.day, "
                "next_id=excluded.next_id, "
                "pending_importance=excluded.pending_importance, "
                "working=excluded.working",
                (float(day), int(next_id), float(pending), json.dumps(list(working))),
            )
            self._conn.commit()

    # ---------- read path ----------

    def load_facts(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM facts ORDER BY id"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["accesses"] = json.loads(d["accesses"] or "[]")
            d["sources"] = tuple(json.loads(d["sources"] or "[]"))
            out.append(d)
        return out

    def load_state(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM store_state WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["working"] = json.loads(d["working"] or "[]")
        return d

    def active_facts(self) -> list[dict]:
        """Facts for the UI panel: active, non-empty, id order.

        Filtered in SQL rather than in Python so the sidecar does not load
        the entire history to render a footer.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text FROM facts "
                "WHERE status = 'active' AND text <> '' ORDER BY id"
            ).fetchall()
        return [{"id": r["id"], "text": r["text"]} for r in rows]
