#!/usr/bin/env python3
"""Synthetic trigger and non-trigger cases for every judge-lint rule."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import judge_lint as lint


def assistant(text: str) -> dict:
    return {"role": "assistant", "node": "agent", "message": text, "t": 0}


def user(text: str) -> dict:
    return {"role": "user", "node": "customer", "message": text, "t": 0}


def start(name: str, args: dict | None = None) -> dict:
    return {
        "role": "system",
        "node": "tool",
        "message": "",
        "t": 0,
        "event": {"event": "function_call_start", "function": name, "args": args or {}},
    }


def complete(name: str, result: dict | None = None) -> dict:
    return {
        "role": "system",
        "node": "tool",
        "message": "",
        "t": 0,
        "event": {
            "event": "function_call_complete",
            "function": name,
            "result": result or {"status": "success", "data": {"ok": True}},
        },
    }


def transcript(*messages: dict) -> lint.Transcript:
    return lint.parse_export(
        {
            "case": "SYN-1",
            "call_id": "call-1",
            "expected": {},
            "checks": [],
            "tools": [],
            "messages": list(messages),
        }
    )


PROMISE = {"body": {"product_id": "p1", "amount": 125.50, "date": "2026-10-22"}}


class JudgeLintTests(unittest.TestCase):
    def test_r1_honesty_before_tool_success(self) -> None:
        good = transcript(
            start("create_promise", PROMISE),
            complete("create_promise"),
            assistant("Your payment promise has been recorded."),
            assistant("We keep a recording of this call."),
            assistant("This call may be recorded."),
        )
        bad = transcript(
            start("create_promise", PROMISE),
            complete("create_promise"),
            start("create_promise", PROMISE),
            complete("create_promise", {"status": "success", "data": {"ok": False}}),
            assistant("Your payment promise has been saved."),
        )
        self.assertEqual([], lint.rule_r1(good))
        self.assertEqual(["R1"], [item.rule for item in lint.rule_r1(bad)])

    def test_r2_disclosure_before_identity(self) -> None:
        verified = [
            start("verify_identity", {"field": "postcode", "answer": "SW1A 1AA"}),
            complete("verify_identity", {"status": "success", "data": {"ok": True, "all_verified": True}}),
        ]
        good = transcript(*verified, assistant("Your credit card balance is £50."))
        bad = transcript(assistant("Your credit card balance is £50."), *verified)
        self.assertEqual([], lint.rule_r2(good))
        self.assertEqual(["R2"], [item.rule for item in lint.rule_r2(bad)])

    def test_r3_reasking_accepted_identity(self) -> None:
        rejected = [
            start("verify_identity", {"field": "postcode", "answer": "SW1A 1AA"}),
            complete("verify_identity", {"status": "success", "data": {"ok": True, "verified": False}}),
        ]
        accepted = [
            start("verify_identity", {"field": "postcode", "answer": "SW1A 1AA"}),
            complete("verify_identity", {"status": "success", "data": {"ok": True, "verified": True}}),
        ]
        good = transcript(*rejected, assistant("Could you confirm your postcode again?"))
        bad = transcript(*accepted, assistant("Could you confirm your postcode again?"))
        self.assertEqual([], lint.rule_r3(good))
        self.assertEqual(["R3"], [item.rule for item in lint.rule_r3(bad)])

    def test_r4_repeated_policy_clause(self) -> None:
        good = transcript(
            assistant("The rest will remain overdue."),
            user("Understood."),
            assistant("Would Friday work?"),
        )
        bad = transcript(
            assistant("The rest will remain overdue."),
            user("Understood."),
            assistant("The remainder stays overdue."),
        )
        self.assertEqual([], lint.rule_r4(good))
        self.assertEqual(["R4"], [item.rule for item in lint.rule_r4(bad)])

    def test_r5_template_leak_or_duplicate(self) -> None:
        good = transcript(assistant("Welcome to North Bank. How may I help?"))
        bad = transcript(assistant("Welcome to Bank of North Bank, {{customer_name}}."))
        self.assertEqual([], lint.rule_r5(good))
        self.assertEqual(["R5"], [item.rule for item in lint.rule_r5(bad)])

    def test_r6_readback_argument_mismatch(self) -> None:
        good = transcript(
            assistant("To confirm, you will pay £125.50 on 22 October 2026."),
            user("Yes."),
            start("create_promise", PROMISE),
            complete("create_promise"),
        )
        bad = transcript(
            assistant("To confirm, you will pay £150 on 23 October 2026."),
            user("Yes."),
            start("create_promise", PROMISE),
            complete("create_promise"),
        )
        self.assertEqual([], lint.rule_r6(good))
        self.assertEqual(["R6"], [item.rule for item in lint.rule_r6(bad)])

    def test_r7_promise_requires_readback_and_yes(self) -> None:
        good = transcript(
            assistant("To confirm, you will pay £125.50 on 22 October 2026."),
            user("Yes, that's right."),
            start("create_promise", PROMISE),
            complete("create_promise"),
        )
        bad = transcript(
            assistant("I can take £125.50 on 22 October 2026."),
            user("Maybe."),
            start("create_promise", PROMISE),
            complete("create_promise"),
        )
        self.assertEqual([], lint.rule_r7(good))
        self.assertEqual(["R7"], [item.rule for item in lint.rule_r7(bad)])

    def test_r8_robot_answer(self) -> None:
        good = transcript(user("Are you a robot?"), assistant("I am a digital assistant for North Bank."))
        bad = transcript(user("Is this AI?"), assistant("I am calling from North Bank."))
        self.assertEqual([], lint.rule_r8(good))
        self.assertEqual(["R8"], [item.rule for item in lint.rule_r8(bad)])

    def test_r9_farewell_and_no_talking_after_close(self) -> None:
        good = transcript(
            assistant("Thank you for your time. Goodbye."),
            start("close_call", {"body": {"outcome": "promise_made"}}),
            complete("close_call"),
        )
        bad = transcript(
            assistant("Thank you."),
            start("close_call", {"body": {"outcome": "no_agreement"}}),
            complete("close_call"),
            assistant("One more thing."),
        )
        self.assertEqual([], lint.rule_r9(good))
        self.assertEqual(["R9", "R9"], [item.rule for item in lint.rule_r9(bad)])

    def test_required_sentences_feed_r4(self) -> None:
        tx = transcript(
            assistant("Only a successful tool response confirms the arrangement."),
            user("Okay."),
            assistant("Only a successful tool response confirms the arrangement."),
        )
        self.assertEqual(
            ["R4"],
            [item.rule for item in lint.rule_r4(tx, ["Only a successful tool response confirms the arrangement."])],
        )

    def test_json_string_tool_events_are_parsed(self) -> None:
        tx = transcript(
            {
                "role": "system",
                "node": "tool",
                "message": json.dumps({"event": "function_call_start", "function": "add_note", "args": {"body": {"note": "x"}}}),
                "t": 0,
            },
            {
                "role": "system",
                "node": "tool",
                "message": json.dumps({"event": "function_call_complete", "function": "add_note", "result": {"status": "success"}}),
                "t": 0,
            },
            assistant("That has been noted."),
        )
        self.assertEqual(1, len(tx.calls))
        self.assertEqual([], lint.rule_r1(tx))

    def test_cli_prints_synthetic_fixture(self) -> None:
        export = {
            "case": "SYN-CLI",
            "call_id": "call-cli",
            "expected": {},
            "checks": [],
            "tools": [],
            "messages": [assistant("Your balance is £99."), assistant("Hello {{name}}.")],
        }
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "SYN-CLI.json").write_text(json.dumps(export), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = lint.main([directory])
        self.assertEqual(1, status)
        self.assertIn("case", output.getvalue())
        self.assertIn("SYN-CLI", output.getvalue())
        self.assertIn("R2", output.getvalue())
        self.assertIn("R5", output.getvalue())


if __name__ == "__main__":
    unittest.main()
