"""Product-specific refusals of the bulk ask consume that product's next attempt."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import generator as G
from builder.engine import event_field as E, reducer as R
from tests.test_reducer_rules import CV, NOW, say, tool, to_statement
from tests.test_reducer_sequences import FIX, POL

CASE = next(c for c in FIX["cases"] if c["id"] == "PUB-12")
ACCOUNT = next(s["tool_event"]["data"]["products"] for s in CASE["steps"]
               if s["source"] == "tool" and "products" in (s["tool_event"].get("data") or {}))
MIXED = "kind=date;also=reject;st=complete;prod=1;rel=tomorrow;amt=510;refused=2,3"


class BulkRefusalTests(unittest.TestCase):
    def setUp(self):
        self.policy = copy.deepcopy(POL["A+B"])
        self.state, _ = to_statement(self.policy, ACCOUNT)

    def test_live_pub12_one_remaining_loan_offer_no_car_offer(self):
        st, act = say(self.policy, self.state, MIXED)
        self.assertEqual([p["attempts"] for p in st["products"]], [0, 2, 1])
        self.assertEqual(st["products"][2]["status"], "refused")
        self.assertEqual(st["products"][1]["offer"], {"amount": 440.0, "date": "2026-10-23"})
        self.assertEqual(st["products"][0]["offer"], {"amount": 510.0, "date": "2026-10-15"})
        self.assertIn("440.00", act["text"])
        self.assertNotIn("1320.00", act["text"])
        self.assertNotIn("140.00", act["text"])
        st, act = say(self.policy, st, "kind=reject;also=none;st=complete;prod=2;why=flat")
        self.assertEqual(st["q"], "readback")
        self.assertEqual([p["attempts"] for p in st["products"]], [0, 2, 1])
        st, act = say(self.policy, st, "kind=yes;also=none;st=complete;prod=")
        calls = []
        while act["type"] == "call_tool":
            calls.append((act["tool"], act["args"]))
            st, act = tool(self.policy, st, {"ok": True})
        self.assertEqual(calls, [
            ("create_promise", {"customer_id": CV["customer_id"], "product_id": "p1", "amount": 510.0,
                                "date": "2026-10-15"}),
            ("add_note", {"customer_id": CV["customer_id"], "product_id": "p2", "reason": "refused"}),
            ("add_note", {"customer_id": CV["customer_id"], "product_id": "p3", "reason": "refused"}),
        ])
        st, act = say(self.policy, st, "kind=other;also=none;st=none;prod=")
        self.assertEqual((act["type"], act["outcome"], act["reason"]), ("close", "promise", None))

    def test_plain_bulk_no_still_starts_each_product_at_attempt_one(self):
        for body in ("kind=reject;also=none;st=complete;prod=all;why=flat",
                     "kind=no;also=none;st=complete;prod=",
                     "kind=no;also=none;st=complete;prod=all"):
            with self.subTest(body=body):
                st, act = say(self.policy, self.state, body)
                self.assertEqual([p["attempts"] for p in st["products"]], [1, 0, 0])
                self.assertEqual(st["cur"], 0)
                self.assertIn("510.00", act["text"])

    def test_named_subset_duplicate_targets_and_per_product_caps(self):
        self.policy["attempts"]["plan"]["late"] *= 2
        st, _ = to_statement(self.policy, ACCOUNT)
        st, act = say(self.policy, st, MIXED.replace("refused=2,3", "refused=2,2,3"))
        self.assertEqual([p["attempts"] for p in st["products"]], [0, 2, 1])
        self.assertEqual(st["products"][2]["status"], "refused")

    def test_only_named_products_are_charged(self):
        st, act = say(self.policy, self.state, "kind=reject;also=none;st=complete;prod=3;why=flat;refused=3")
        self.assertEqual([p["attempts"] for p in st["products"]], [1, 0, 1])
        self.assertEqual(st["products"][2]["status"], "refused")
        self.assertEqual(st["cur"], 0)

    def test_secondary_proposal_processed_once_after_a_question(self):
        body = MIXED.replace("kind=date;also=reject", "kind=topic;also=date") + ";t=robot"
        st, _ = say(self.policy, self.state, body)
        self.assertEqual([p["attempts"] for p in st["products"]], [0, 2, 1])
        self.assertEqual(st["cur"], 1)
        self.assertEqual(st["products"][1]["status"], "proposed")

    def test_proposed_product_cannot_be_consumed_as_refused(self):
        st, _ = say(self.policy, self.state, MIXED.replace("refused=2,3", "refused=1,2,3"))
        self.assertEqual(st["products"][0]["attempts"], 0)
        self.assertEqual(st["products"][0]["status"], "agreed")

    def test_reordered_account_uses_positions_not_product_types(self):
        st, _ = to_statement(self.policy, [ACCOUNT[2], ACCOUNT[1], ACCOUNT[0]])
        st, act = say(self.policy, st, MIXED.replace("prod=1", "prod=3").replace("refused=2,3", "refused=1,2"))
        self.assertEqual([p["attempts"] for p in st["products"]], [1, 2, 0])
        self.assertEqual(st["products"][0]["status"], "refused")
        self.assertEqual(st["products"][2]["offer"], {"amount": 510.0, "date": "2026-10-15"})
        self.assertIn("440.00", act["text"])

    def test_invalid_partial_and_unqualified_targets_do_not_charge_others(self):
        for targets in ("", "all", "rest", "0", "4", "2,4", "2,x", "-1", "2,3,"):
            with self.subTest(targets=targets):
                st, _ = say(self.policy, self.state, MIXED.rsplit("=", 1)[0] + "=" + targets)
                self.assertEqual(st["products"][2]["attempts"], 0)
                self.assertEqual(st["products"][2]["status"], "open")
        st, _ = say(self.policy, self.state, MIXED.replace("st=complete", "st=partial"))
        self.assertEqual([p["attempts"] for p in st["products"]], [0, 0, 0])
        self.policy["attempts"]["flat_refusal_uses_attempt"]["value"] = False
        st, _ = say(self.policy, self.state, MIXED)
        self.assertEqual(st["products"][2]["attempts"], 0)

    def test_no_notes_when_disabled(self):
        self.policy["writes"]["notes"]["enabled"] = False
        st, act = say(self.policy, self.state, "kind=reject;also=none;st=complete;prod=all;why=flat;refused=1,2,3")
        self.assertEqual(st["products"][0]["attempts"], 2)
        self.assertEqual(st["products"][2]["status"], "refused")
        for _ in range(2):
            st, act = say(self.policy, st, "kind=reject;also=none;st=complete;prod=;why=flat")
        self.assertEqual(act["type"], "close")
        self.assertFalse(st["pending"])

    def test_contract_and_packed_hub(self):
        raw = "n=kabcde;src=user;" + MIXED
        self.assertIsNotNone(E.parse(raw))
        self.assertRegex(raw, E.platform_pattern())
        prompt = E.ev_field(self.policy)["extraction_prompt"]
        self.assertIn("refused=", prompt)
        self.assertIn("the others", prompt)
        code = G.pack_hub(R.hub_source(self.policy))
        st = copy.deepcopy(self.state)
        st["tok"] = "kabcde"
        vars = dict(CV, st=json.dumps(st), ev_tok="kabcde", ev=raw)
        exec(compile(code, "packed-bulk-refusal", "exec"), {"vars": vars})
        self.assertFalse(vars.get("hub_error"), vars.get("hub_error"))
        actual = json.loads(vars["st"])
        self.assertEqual([p["attempts"] for p in actual["products"]], [0, 2, 1])
        self.assertEqual(actual["products"][2]["status"], "refused")
        self.assertIn("440.00", vars["say_next"])
        # An event from the previous turn cannot charge another attempt.
        exec(compile(code, "packed-bulk-refusal", "exec"), {"vars": vars})
        self.assertEqual([p["attempts"] for p in json.loads(vars["st"])["products"]], [0, 2, 1])


if __name__ == "__main__":
    unittest.main()
