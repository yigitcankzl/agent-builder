#!/usr/bin/env python3
"""Self-tests for the independent oracle."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from brief_gen import brief_a_policy
from oracle import deadline_for, expected_ledger, floor_for


class PublicOracleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {case["id"]: case for case in json.loads((ROOT / "public-test-set.json").read_text())}

    def assert_public(self, case_id: str, policy: dict, intent: dict) -> None:
        self.assertEqual(expected_ledger(policy, self.cases[case_id], intent), self.cases[case_id]["expected"])

    def test_brief_a_pub_01_to_10(self) -> None:
        policy = brief_a_policy()
        intents = {
            "PUB-01": {"kind": "pay_today"},
            "PUB-02": {"kind": "third_party", "callback_date": "2026-10-15", "callback_time": "11:00"},
            "PUB-03": {"kind": "identity_fail", "wrong_answers": 3},
            "PUB-04": {"kind": "name_date", "date": "2026-11-06", "accept_adjustment": True},
            "PUB-05": {"kind": "hardship", "accept_transfer": False},
            "PUB-06": {"kind": "too_much", "date": "2026-10-16"},
            "PUB-07": {"kind": "name_date", "date": "2026-10-26", "accept_adjustment": True},
            "PUB-08": {"kind": "paid"},
            "PUB-09": {"kind": "restructure"},
            "PUB-10": {"kind": "name_date", "date": "2026-10-16"},
        }
        for case_id, intent in intents.items():
            with self.subTest(case_id=case_id):
                self.assert_public(case_id, policy, intent)

    def test_brief_b_multi_product_public_cases(self) -> None:
        policy = brief_a_policy()
        policy["multi_product"] = {
            "enabled": True,
            "max_products": 3,
            "processing_order": "account",
            "shared_date_rule": "clamp_each_to_its_deadline",
            "note_unresolved_products": True,
            "suppress_notes_on_transfer": True,
            "promise_wins": True,
        }
        intents = {
            "PUB-11": {"kind": "name_date", "date": "2026-10-16"},
            "PUB-12": {"kind": "per_product", "by_product": {
                "p1": {"kind": "name_date", "date": "2026-10-15"},
                "p2": {"kind": "refuse", "count": 99},
                "p3": {"kind": "refuse", "count": 99},
            }},
            "PUB-13": {"kind": "name_date", "date": "2026-10-30"},
        }
        for case_id, intent in intents.items():
            with self.subTest(case_id=case_id):
                self.assert_public(case_id, policy, intent)


class OracleMechanicsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = brief_a_policy()
        self.customer = {
            "variables": {"now": "2026-10-14T11:00"},
            "products": [{"product_id": "p1", "type": "credit_card", "past_due": 100, "days_late": 5, "minimum_payment": 30}],
        }

    def test_floor_variants_and_rounding(self) -> None:
        product = self.customer["products"][0]
        self.policy["floor_rule"] = {"type": "percent", "percent": 33.33, "rounding": {"mode": "up", "increment": 0.05}}
        self.assertEqual(floor_for(self.policy, product), 33.35)
        self.policy["floor_rule"] = {"type": "fixed", "amount": 27.5}
        self.assertEqual(floor_for(self.policy, product), 27.5)
        self.policy["floor_rule"] = {"type": "max_fixed_percent", "fixed": 35, "percent": 20, "rounding": {"mode": "nearest", "increment": 1}}
        self.assertEqual(floor_for(self.policy, product), 35.0)

    def test_calendar_deadline_and_attempt_limit(self) -> None:
        self.policy["calendar"]["holidays"] = []
        self.policy["lateness_bands"][0]["deadline"] = {"count": 3, "unit": "calendar"}
        self.assertEqual(deadline_for(self.policy, self.customer["products"][0], date(2026, 10, 14)).isoformat(), "2026-10-16")
        self.assertEqual(expected_ledger(self.policy, self.customer, {"kind": "refuse", "count": 0})["promises"][0]["date"], "2026-10-16")
        self.assertEqual(expected_ledger(self.policy, self.customer, {"kind": "refuse", "count": 1})["outcome"], "no_promise")

    def test_wrong_answer_limit_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            expected_ledger(self.policy, self.customer, {"kind": "identity_fail", "wrong_answers": 2})


class FrozenHardSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = HERE / "sample2"
        cls.public = {case["id"]: case for case in json.loads((ROOT / "public-test-set.json").read_text())}
        cls.manifest = json.loads((cls.root / "manifest.json").read_text())

    def policy(self, number: int) -> dict:
        return json.loads((self.root / f"gen-{number:03d}" / "expected_policy.json").read_text())

    def test_frozen_cases_are_oracle_checked_and_keep_public_inputs(self) -> None:
        self.assertEqual([item["id"] for item in self.manifest["briefs"]], [f"GEN-{n:03d}" for n in range(7, 13)])
        for item in self.manifest["briefs"]:
            directory = self.root / item["directory"]
            policy = json.loads((directory / "expected_policy.json").read_text())
            cases = json.loads((directory / "cases.json").read_text())
            with self.subTest(brief=item["id"]):
                self.assertEqual(len(cases), 10)
                self.assertGreaterEqual(len(item["axes"]), 2)
                self.assertEqual(item["axes"], policy["generation"]["axes"])
                self.assertEqual([path.name for path in directory.glob("*.md")], ["brief.md"])
                self.assertIn("LATER OVERRIDE MESSAGE", (directory / "brief.md").read_text())
                self.assertGreaterEqual(len(policy["generation"]["memo_overrides"]), 1)
                for override in policy["generation"]["memo_overrides"]:
                    value = policy
                    for part in override["path"].split("."):
                        value = value[int(part)] if part.isdigit() else value[part]
                    self.assertEqual(value, override["after"])
                for case in cases:
                    source = self.public[case["id"]]
                    self.assertEqual(case["identity"], source["identity"])
                    self.assertEqual(case["products"], source["products"])
                    self.assertEqual(expected_ledger(policy, case, case["intent"]), case["expected"])

    def test_hard_axes_have_concrete_ground_truth(self) -> None:
        gen7 = self.policy(7)
        self.assertEqual(gen7["codes"]["outcomes"]["promise"], "commitment_logged")
        self.assertEqual(gen7["codes"]["reasons"]["refused"], "payment_declined")
        self.assertEqual(gen7["codes"]["queues"]["restructuring"], "support")

        gen8 = self.policy(8)
        self.assertEqual(gen8["identity"]["questions"], ["phone_last4", "full_name", "date_of_birth"])
        self.assertEqual(deadline_for(gen8, self.public["PUB-01"]["products"][0], date(2026, 10, 14)).isoformat(), "2026-10-16")

        gen9 = self.policy(9)
        oas9 = json.loads((self.root / "gen-009" / "openapi.json").read_text())
        self.assertNotIn("/add_note", oas9["paths"])
        self.assertEqual(floor_for(gen9, self.public["PUB-04"]["products"][0]), 416.65)

        gen10 = self.policy(10)
        oas10 = json.loads((self.root / "gen-010" / "openapi.json").read_text())
        self.assertNotIn("/transfer_to_agent", oas10["paths"])
        promise_schema = oas10["paths"]["/create_promise"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertIn("pledged_amount", promise_schema["required"])
        self.assertIn("due_on", promise_schema["required"])

        gen11 = self.policy(11)
        self.assertEqual(gen11["accepted_amount_range"]["partial_mode"], "exact_floor")
        self.assertEqual(gen11["lateness_bands"][0]["persuasion_attempts"][0]["date"]["type"], "last_business_day_this_or_next_week")

        gen12 = self.policy(12)
        self.assertEqual(floor_for(gen12, self.public["PUB-04"]["products"][0]), 47.5)
        self.assertEqual(deadline_for(gen12, self.public["PUB-01"]["products"][0], date(2026, 10, 14)).isoformat(), "2026-10-20")

if __name__ == "__main__":
    unittest.main(verbosity=2)
