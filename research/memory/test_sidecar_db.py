"""Tests for the durable memory store (SQLite persistence + forget semantics).

Run: python3 research/memory/test_sidecar_db.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sidecar import DurableStore  # noqa: E402
from store_db import SCHEMA_VERSION, FactDB  # noqa: E402


class DurableStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "memory.db"

    def open_store(self) -> DurableStore:
        db = FactDB(self.path)
        self.addCleanup(db.close)
        return DurableStore(db)

    def test_add_and_list(self):
        s = self.open_store()
        m = s.add("मेरा नाम राज है")
        self.assertIsNotNone(m)
        self.assertEqual([f["text"] for f in s.facts()], ["मेरा नाम राज है"])

    def test_facts_survive_restart(self):
        s = self.open_store()
        s.add("I work at a hospital")
        s.add("నా పేరు రాజు")
        before = s.facts()

        # Reopen from scratch: this is the upgrade/restart path that the old
        # pickle snapshot silently wiped whenever a dataclass changed.
        s2 = self.open_store()
        self.assertEqual(before, s2.facts())

    def test_ids_do_not_restart_after_reload(self):
        s = self.open_store()
        first = s.add("my exam is on Monday")
        s2 = self.open_store()
        second = s2.add("my wedding is in June")
        self.assertGreater(second.id, first.id, "id counter must not reuse ids")

    def test_forget_purges_text_from_disk(self):
        s = self.open_store()
        s.add("I had an accident yesterday")
        s.add("मुझे चाय पसंद है")
        self.assertTrue(s.forget("I had an accident yesterday"))

        self.assertEqual([f["text"] for f in s.facts()], ["मुझे चाय पसंद है"])
        # Hard forget is a guarantee: the bytes must be gone, not tombstoned
        # in place with the text intact.
        raw = self.path.read_bytes()
        wal = self.path.with_name(self.path.name + "-wal")
        if wal.exists():
            raw += wal.read_bytes()
        self.assertNotIn(b"accident yesterday", raw)

    def test_forget_is_recorded_as_a_tombstone(self):
        s = self.open_store()
        s.add("I had an accident yesterday")
        s.forget("I had an accident yesterday")
        conn = sqlite3.connect(self.path)
        self.addCleanup(conn.close)
        rows = conn.execute("SELECT fact_id FROM tombstones").fetchall()
        self.assertEqual(len(rows), 1)

    def test_forget_survives_restart(self):
        s = self.open_store()
        s.add("I had an accident yesterday")
        s.forget("I had an accident yesterday")
        s2 = self.open_store()
        self.assertEqual(s2.facts(), [])
        self.assertEqual(s2.context_block("accident"), "")

    def test_forget_unknown_text_is_false(self):
        s = self.open_store()
        self.assertFalse(s.forget("never stored"))

    def test_context_block_retrieves_relevant_fact(self):
        s = self.open_store()
        s.add("I had an accident yesterday")
        block = s.context_block("tell me about the accident")
        self.assertIn("accident", block)

    def test_empty_text_is_rejected(self):
        s = self.open_store()
        self.assertIsNone(s.add("   "))

    def test_schema_version_recorded(self):
        self.open_store()
        conn = sqlite3.connect(self.path)
        self.addCleanup(conn.close)
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        self.assertEqual(int(row[0]), SCHEMA_VERSION)

    def test_newer_schema_refuses_to_load(self):
        """A downgrade must fail loudly instead of destroying data."""
        self.open_store()
        conn = sqlite3.connect(self.path)
        conn.execute(
            "UPDATE schema_meta SET value=? WHERE key='version'",
            (str(SCHEMA_VERSION + 1),),
        )
        conn.commit()
        conn.close()
        with self.assertRaises(RuntimeError):
            FactDB(self.path)

    def test_duplicate_add_does_not_duplicate_rows(self):
        s = self.open_store()
        s.add("मेरा नाम राज है")
        s.add("मेरा नाम राज है")
        self.assertEqual(len(s.facts()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
