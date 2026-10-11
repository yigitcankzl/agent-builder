"""Raw-5 build1's saved extraction: opening scope must not become per-product persuasion. Offline only."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import generator as G, policy_bridge as B
from builder.engine import reducer as R
from builder.graph_walk import walk
from builder.validate_workflow import validate
from tests.test_graph_walk import FIX, bank_for
from tests.test_rehearsal import FLAT, NO, OTHER, REL, V, YES, run_case

OAS = os.path.join(ROOT, "tools/openapi.json")
with open(os.path.join(ROOT, "tests/fixtures/reducer/raw5.extracted.json")) as f:
    RAW = json.load(f)
PUBLIC = next(c for c in FIX["cases"] if c["id"] == "PUB-12")
CASE = dict(id=PUBLIC["id"], variables=PUBLIC["call_variables"], identity=PUBLIC["identity"], products=PUBLIC["account"])


class BulkTodayTests(unittest.TestCase):
    def policy(self, raw=RAW):
        policy, report = B.to_reducer(raw, OAS)
        self.assertEqual(report["errors"], [])
        self.assertEqual(validate(G.generate(policy, OAS), policy, OAS), [])
        return policy

    def assert_once(self, actions, state):
        lines = [a.get("text", "") for a in actions if a["type"] == "say_exact"]
        self.assertEqual(sum(line.count(R.D_ALL_TODAY) for line in lines), 1)
        self.assertTrue(state["all_today_asked"])
        self.assertFalse(any(R.say_date(R._d(CASE["variables"]["now"])) in line
                             for line in lines if "Could you pay" in line), lines)

    def test_partial_payment_then_other_product_offers(self):
        policy = self.policy()
        ledger, actions, state = run_case(policy, CASE, V(CASE) + [REL("tomorrow", "1"), FLAT, FLAT, YES])
        self.assert_once(actions, state)
        offers = [a["text"] for a in actions if a["type"] == "say_exact" and "Could you pay" in a.get("text", "")]
        loan = state["_pd"][1]
        self.assertEqual(len(offers), 2)
        self.assertIn(R.money(loan["past_due"]), offers[0])
        self.assertIn(R.money(loan["floor"]), offers[1])
        self.assertTrue(all(R.say_date(R._d(loan["deadline"])) in line for line in offers))
        self.assertEqual(state["products"][1]["attempts"], 2)
        self.assertEqual(ledger["promises"], [dict(product_id="p1", amount=510.0, date="2026-10-15")])
        self.assertEqual(ledger["notes"], [dict(product_id="p2", reason="refused")])
        self.assertEqual(ledger["transfers"], [dict(queue="restructuring")])

    def test_generic_no_does_not_consume_all_products(self):
        policy = self.policy()
        _, actions, state = run_case(policy, CASE, V(CASE) + [NO])
        self.assert_once(actions, state)
        self.assertEqual([p["attempts"] for p in state["products"]], [1, 0, 0])
        self.assertEqual(state["products"][1]["status"], "open")
        self.assertEqual(state["offer"]["product_ids"], ["p1"])
        _, actions, state = run_case(policy, CASE, V(CASE) + [NO, FLAT])
        self.assert_once(actions, state)
        self.assertEqual([p["attempts"] for p in state["products"]], [2, 0, 0])
        self.assertEqual(state["offer"]["amount"], state["_pd"][0]["floor"])
        _, actions, state = run_case(policy, CASE, V(CASE) + [NO, FLAT, FLAT])
        self.assert_once(actions, state)
        self.assertEqual([p["attempts"] for p in state["products"]], [2, 1, 0])
        self.assertEqual(state["offer"]["product_ids"], ["p2"])
        self.assertEqual(state["offer"]["amount"], state["_pd"][1]["past_due"])

    def test_explicit_refusals_still_consume_only_named_products(self):
        policy = self.policy()
        for refusal, expected in (("2", [1, 1, 0]), ("1,2", [2, 1, 0])):
            with self.subTest(refusal=refusal):
                _, actions, state = run_case(policy, CASE, V(CASE) + [FLAT + ";refused=" + refusal])
                self.assert_once(actions, state)
                self.assertEqual([p["attempts"] for p in state["products"]], expected)
                if refusal == "1,2":
                    self.assertEqual(state["offer"]["product_ids"], ["p1"])
                    self.assertEqual(state["offer"]["amount"], state["_pd"][0]["floor"])

    def test_independent_per_product_today_rule_is_preserved(self):
        raw = copy.deepcopy(RAW)
        step = raw["attempts"]["plan"]["early"][0]
        step["source"].append({"file": "memo.md", "quote": "Offer the full payment for this product today."})
        policy = self.policy(raw)
        self.assertEqual(policy["attempts"]["plan"]["early"][0]["date_rule"], "today")

    def test_generic_common_question_wording(self):
        original = RAW["multi_product"]["source"][0]["quote"]
        for question in ("Can you pay all of them today?", "Ask whether all three products can be paid today."):
            with self.subTest(question=question):
                raw = copy.deepcopy(RAW)
                for section in [raw["multi_product"]] + [s for steps in raw["attempts"]["plan"].values() for s in steps]:
                    for source in section["source"]:
                        if source["quote"] == original:
                            source["quote"] = question
                policy = self.policy(raw)
                self.assertTrue(all(steps[0]["date_rule"] == "deadline" for steps in policy["attempts"]["plan"].values()))

    def test_shorter_common_question_citation_is_still_opening_only(self):
        raw = copy.deepcopy(RAW)
        for steps in raw["attempts"]["plan"].values():
            steps[0]["source"][0]["quote"] = RAW["multi_product"]["source"][0]["quote"].split("then ")[1]
        policy = self.policy(raw)
        self.assertTrue(all(steps[0]["date_rule"] == "deadline" for steps in policy["attempts"]["plan"].values()))

    def test_generated_workflow_has_one_global_question(self):
        policy = self.policy()
        events = V(CASE) + [REL("tomorrow", "1"), FLAT, FLAT, YES, OTHER, OTHER]
        with open(OAS) as f:
            api = json.load(f)
        base_bank, verified = bank_for(PUBLIC), set()
        def bank(tool, body):
            if tool == "verify_identity":
                self.assertEqual(body["answer"], CASE["identity"][body["field"]])
                verified.add(body["field"])
                return 200, dict(ok=True, verified=True, all_verified=set(CASE["identity"]) <= verified, wrong_answers_left=3)
            return base_bank(tool, body)
        rep = walk(G.generate(policy, OAS), api, CASE["variables"],
                   ["n=aaaaaa;src=user;" + e for e in events], bank)
        self.assertEqual(rep["errors"], [])
        self.assertTrue(rep["ended"])
        speech = [text for _, text in rep["speech"]]
        self.assertEqual(sum(text.count(R.D_ALL_TODAY) for text in speech), 1)
        self.assertFalse(any("Wednesday 14 October" in text for text in speech if "Could you pay" in text))
        self.assertEqual([c["body"]["product_id"] for c in rep["calls"] if c["tool"] == "create_promise"], ["p1"])

    def test_no_unsourced_replacement_date(self):
        raw = copy.deepcopy(RAW)
        raw["date_rules"]["after_deadline"]["source"] = []
        policy, report = B.to_reducer(raw, OAS)
        self.assertIsNone(policy["attempts"]["plan"]["early"][0]["date_rule"])
        self.assertTrue(any(m["policy_path"] == "attempts.plan.early[0].date_rule"
                            and m["action"] == "reextract" for m in report["api_mismatch"]))
        self.assertTrue(report["errors"])

    def test_public_persuasion_plans_unchanged(self):
        for name in ("brief-a", "brief-ab"):
            with self.subTest(name=name):
                with open(os.path.join(ROOT, "tests/e2e-int/submission", name + ".extracted.json")) as f:
                    raw = json.load(f)
                self.assertEqual(self.policy(raw)["attempts"]["plan"], raw["attempts"]["plan"])


if __name__ == "__main__":
    unittest.main()
