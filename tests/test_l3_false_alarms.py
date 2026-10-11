"""Briefs the engine runs must not go to L3 for the wrong reason (Fork 4 analysis on f4eb538: 9/12 synthetic, raw-4,
raw-2 rejected by validator 24; raw-5 lost its car route silently). No model or platform calls.

    python3 -m tests.test_l3_false_alarms
"""
import copy, json, os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = sys.argv[:1]
from builder import policy_bridge as B
from builder.engine import date_policy as DP
from builder.generator import arg_map, generate, oas_tools
from builder.policy_extract import date_rule_supported
from builder.validate_workflow import validate
from tests.test_rehearsal import V, REL, DT, TOO, YES, NO, FLAT, OTHER, run_case, diff

OAS = os.path.join(ROOT, "tools/openapi.json")
FIX = os.path.join(ROOT, "tests/fixtures/brief_reading")


def load(n):
    d = os.path.join(FIX, f"raw-{n}-single")
    return json.load(open(d + "/extracted.json")), open(d + "/brief.md").read(), json.load(open(d + "/cases.json"))


def main_path(rp, oas=OAS):
    return validate(generate(rp, oas), rp, oas, [])


class L3FalseAlarms(unittest.TestCase):
    def test_n_days_rules_are_known_and_quote_backed(self):
        q = [{"quote": "then offer the floor amount on 2 business days after today"}]
        self.assertTrue(DP.date_rule_known("2_business_days_after_today"))
        self.assertTrue(date_rule_supported("2_business_days_after_today", q))
        self.assertTrue(date_rule_supported("2_business_days_after_today", [{"quote": "two business days from today"}]))
        self.assertFalse(date_rule_supported("3_business_days_after_today", q))
        self.assertFalse(date_rule_supported("2_calendar_days_after_today", q))
        p, text, _ = load(4)
        step = p["attempts"]["plan"]["late"][1]
        step.update(date_rule="2_calendar_days_after_today", source=[{"file": "brief.md", "quote": "Its latest promise date is the 2nd calendar day after today."}])
        rp, _ = B.to_reducer(p, OAS, brief_text=text)
        self.assertEqual(rp["attempts"]["plan"]["late"][1]["date_rule"], "2_calendar_days_after_today")
        self.assertFalse(DP.unsupported_rules(rp))

    def test_raw4_undated_attempt_takes_the_quoted_general_rule(self):
        p, text, cases = load(4)
        for first in ("customer_named", "deadline"):      # h677/h791 and h376
            q = copy.deepcopy(p)
            for steps in q["attempts"]["plan"].values():
                steps[0]["date_rule"] = first
            rp, rep = B.to_reducer(q, OAS, brief_text=text)
            self.assertEqual([s[0]["date_rule"] for s in rp["attempts"]["plan"].values()], ["deadline", "deadline"])
            self.assertFalse(DP.unsupported_rules(rp))
            self.assertEqual(main_path(rp), [])
        c = next(c for c in cases if c["id"] == "PUB-10")
        ledger, _, _ = run_case(rp, c, V(c) + [NO, YES, YES, OTHER])
        self.assertEqual(diff(c["expected"], ledger), [])
        q = copy.deepcopy(p)        # no general rule quoted anywhere: still rejected
        q["date_rules"].pop("after_deadline")
        rp, _ = B.to_reducer(q, OAS, brief_text=text)
        self.assertTrue(any("date_rule" in e for e in DP.unsupported_rules(rp)))

    def test_empty_callback_window_is_not_an_error(self):
        p, text, _ = load(4)
        p["writes"]["callback"].update(start="", end="")
        rp, rep = B.to_reducer(p, OAS, brief_text=text)
        self.assertNotIn("start", rp["writes"]["callback"])
        self.assertFalse([e for e in DP.unsupported_rules(rp) if "callback" in e])

    def test_raw5_car_route_recovered_from_the_brief(self):
        p, text, cases = load(5)
        p["events"] = [e for e in p.get("events") or [] if "car" not in str(e.get("topic"))]
        (p.get("products") or {}).pop("route_by_type", None)
        p["writes"]["transfer"]["queue_map"] = {"car_loan": "restructuring"}
        rp, rep = B.to_reducer(p, OAS, brief_text=text)
        r = rp["products"]["route_by_type"]["car_loan"]
        self.assertEqual((r["action"], r["queue"], r["note"]), ("transfer", "restructuring", False))
        self.assertEqual(DP.bad_quotes({"route": r}, text), [])
        self.assertEqual(rp["tool_status"]["transfer_to_agent"]["status"], "enabled")
        scripts = {"PUB-11": lambda c: V(c) + [DT(16, 10, "all"), YES, YES, OTHER, OTHER],
                   "PUB-12": lambda c: V(c) + [REL("tomorrow", "1"), FLAT, FLAT, YES, OTHER, OTHER],
                   "PUB-13": lambda c: V(c) + [NO, TOO, YES, TOO, YES, YES, OTHER, OTHER]}
        for c in cases:
            ledger, _, _ = run_case(rp, c, scripts[c["id"]](c))
            self.assertEqual(diff(c["expected"], ledger), [], c["id"])

    def test_field_names_bind_before_descriptions(self):
        spec = oas_tools(os.path.join(ROOT, "tests/gen/sample2/gen-010/openapi.json"))["close_call"]
        m, _, _ = arg_map("close_call", spec)
        self.assertEqual((m.get("disposition"), m.get("reason_code")), ("outcome", "reason"))


if __name__ == "__main__":
    unittest.main()
