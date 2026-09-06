"""Tests for automatic fact extraction.

Automatic capture is only safe if it is *precise*. A missed fact is invisible;
a wrongly-captured one is the assistant permanently believing something false
about the user, so these tests weight false positives heavily.

Run: python3 research/memory/test_extract.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from extract import extract_facts, should_remember  # noqa: E402


class KeepTest(unittest.TestCase):
    """Enduring first-person facts must be captured, in all three languages."""

    CASES = [
        # English
        "I work at a hospital in Vijayawada",
        "I am allergic to peanuts",
        "my daughter has an exam tomorrow",
        "my wife is a teacher",
        "I live in Andhra Pradesh",
        "I love filter coffee",
        # Hindi (Devanagari)
        "मेरा नाम राज है",
        "मुझे फ़िल्टर कॉफ़ी पसंद है",
        "मेरी बहन डॉक्टर है",
        # Telugu
        "నా పేరు రాజు",
        "నాకు కాఫీ ఇష్టం",
    ]

    def test_captured(self):
        for text in self.CASES:
            with self.subTest(text=text):
                self.assertTrue(should_remember(text), f"missed: {text}")

    def test_captured_verbatim(self):
        """The user's own words are stored, not a paraphrase."""
        self.assertEqual(
            extract_facts("I work at a hospital"), ["I work at a hospital"]
        )

    def test_whitespace_normalised(self):
        self.assertEqual(
            extract_facts("I  work   at a  hospital"), ["I work at a hospital"]
        )


class DropTest(unittest.TestCase):
    """Everything that is not an enduring personal fact must be rejected."""

    FILLER = ["umm ok", "ok thanks", "हाँ", "अच्छा ठीक", "సరే", "hello", "yeah sure"]
    QUESTIONS = [
        "what is the weather",
        "how are you today",
        "where is the nearest hospital?",
        "क्या आप ठीक हैं",
        "ఏమిటి ఇది",
        "can you help me",
    ]
    COMMANDS = [
        "play some music",
        "tell me a joke",
        "translate this for me",
        "बताओ मुझे कुछ",
        "చెప్పండి ఒక కథ",
    ]
    THIRD_PARTY = [
        "he works at a hospital",
        "she is a doctor",
        "they live in Delhi",
        "वह डॉक्टर है",
    ]
    TOO_SHORT = ["hi", "ok", "no", "", "   ", "?"]

    def _assert_all_dropped(self, cases, label):
        for text in cases:
            with self.subTest(case=label, text=text):
                self.assertFalse(
                    should_remember(text), f"false positive ({label}): {text!r}"
                )

    def test_filler_dropped(self):
        self._assert_all_dropped(self.FILLER, "filler")

    def test_questions_dropped(self):
        self._assert_all_dropped(self.QUESTIONS, "question")

    def test_commands_dropped(self):
        self._assert_all_dropped(self.COMMANDS, "command")

    def test_third_party_statements_dropped(self):
        """A fact about someone else is not a fact about the user."""
        self._assert_all_dropped(self.THIRD_PARTY, "third-party")

    def test_too_short_dropped(self):
        self._assert_all_dropped(self.TOO_SHORT, "too-short")

    def test_possessive_rescues_third_person_mention(self):
        """'he is my brother' IS about the user, unlike 'he is a doctor'."""
        self.assertTrue(should_remember("he is my brother"))

    def test_very_long_turn_dropped(self):
        """A monologue is not a clean fact; capture would store noise."""
        self.assertFalse(should_remember("I " + "really " * 100 + "like coffee"))


class IndicTokenisationTest(unittest.TestCase):
    """Regression: Python's \\w splits Indic graphemes apart.

    A naive `[^\\W_]+` tokenises 'मेरा नाम' as ['म','र','न','म'], so no Hindi
    or Telugu fact ever matched a cue and automatic capture silently worked
    for English only.
    """

    def test_devanagari_fact_matches(self):
        self.assertTrue(should_remember("मेरा नाम राज है"))

    def test_telugu_fact_matches(self):
        self.assertTrue(should_remember("నా పేరు రాజు"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
