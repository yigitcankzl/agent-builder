#!/usr/bin/env python3
"""Focused checks for the utterance-label contract."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_utterances import validate_payload, validate_phrases


class UtteranceContractTest(unittest.TestCase):
    def test_secondary_yes_no_and_other_are_rejected(self) -> None:
        for secondary in ("yes", "no", "other"):
            with self.subTest(secondary=secondary), self.assertRaises(ValueError):
                validate_payload(1, {"kind": "topic", "also": secondary, "t": "robot"})

    def test_who_values_are_normalized(self) -> None:
        validate_payload(1, {"kind": "who", "also": None, "who": "self"})
        validate_payload(1, {"kind": "who", "also": None, "who": "other"})
        with self.assertRaises(ValueError):
            validate_payload(1, {"kind": "who", "also": None, "who": "someone_else"})

    def test_partial_year_is_date_of_birth(self) -> None:
        validate_payload(1, {
            "kind": "identity", "also": None, "field": "date_of_birth", "y": 1992, "st": "partial",
        })
        with self.assertRaises(ValueError):
            validate_payload(1, {"kind": "identity", "also": None, "field": "birth_year", "ans": "1992"})

    def test_callback_has_priority_over_who(self) -> None:
        valid = {
            "kind": "callback", "also": "who", "who": "other", "rel": "tomorrow", "tm": "15:00",
        }
        validate_payload(1, valid)
        with self.assertRaises(ValueError):
            validate_payload(1, {**valid, "kind": "who", "also": "callback"})

    def test_purpose_and_stop_phrases_are_enforced(self) -> None:
        validate_phrases(1, {
            "customer_said": "Well, why are you asking?",
            "expect": {"kind": "topic", "also": None, "t": "purpose"},
        })
        with self.assertRaises(ValueError):
            validate_phrases(1, {
                "customer_said": "Who is this?",
                "expect": {"kind": "other", "also": None},
            })
        with self.assertRaises(ValueError):
            validate_phrases(1, {
                "customer_said": "Stop calling me.",
                "expect": {"kind": "topic", "also": "reject", "t": "stop", "why": "flat"},
            })


if __name__ == "__main__":
    unittest.main()
