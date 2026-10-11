"""Re-bridge frozen extractions from the raw-4/5 failures; no model or platform calls."""
import copy
import datetime
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import generator as G, policy_bridge as B
from builder.engine import dates as D, date_policy as DP, reducer as R
from builder.degrade import mandatory_tools
from builder.graph_walk import walk
from builder.validate_workflow import validate as validate_workflow
from tests.test_rehearsal import V, TOPIC, REL, DT, TOO, YES, NO, FLAT, OTHER, run_case, diff

OAS = os.path.join(ROOT, "tools/openapi.json")
FIX = os.path.join(ROOT, "tests/fixtures/brief_reading")


def load(n):
    d = os.path.join(FIX, f"raw-{n}-single")
    with open(d + "/extracted.json") as f, open(d + "/brief.md") as b, open(d + "/cases.json") as c:
        return json.load(f), b.read(), json.load(c)


class BriefReadingTests(unittest.TestCase):
    def test_hardship_trigger_is_not_an_agent_line(self):
        p, text, cases = load(4)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        row = next(e for e in rp["events"] if e["topic"] == "hardship")
        self.assertEqual(row["say"], "")
        c = next(c for c in cases if c["id"] == "PUB-05")
        ledger, said, st = run_case(rp, c, V(c) + [TOPIC("hardship"), FLAT, OTHER])
        self.assertEqual(diff(c["expected"], ledger), [])
        lines = " ".join(a.get("text") or "" for a in said)
        self.assertIn("Would you like", lines)
        self.assertNotIn("They cannot pay", lines)
        ledger, said, st = run_case(rp, c, V(c) + [TOPIC("hardship"), YES])
        self.assertEqual(ledger["transfers"], [{"queue": "support"}])

    def test_prohibition_does_not_authorize_a_close(self):
        p, text, cases = load(4)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        terms = next(e for e in rp["events"] if e["topic"] == "terms")
        self.assertFalse(terms.get("outcome"))
        self.assertTrue(any("ASSUMPTION" in s and ".close" in s for s in report["notes"]))
        c = next(c for c in cases if c["id"] == "PUB-05")
        ledger, said, st = run_case(rp, c, V(c) + [TOPIC("hardship"), TOPIC("terms")])
        self.assertEqual(st["q"], "support_offer")
        self.assertIsNone(ledger["outcome"])
        self.assertEqual(said[-1]["type"], "say_exact")
        e = {"topic": "terms", "outcome": "no_promise", "source": [{"file": "t.md", "quote": "Do not close the call for a discount question."}]}
        B.source_guard({"events": [e]})
        self.assertFalse(e["outcome"])

    def test_unsourced_rows_sentences_mappings_are_dropped_and_flagged(self):
        p, text, _ = load(4)
        p.pop("topic_checklist", None)
        p["events"].append({"topic": "paid", "say": "You owe an extra fee.", "outcome": "paid", "source": []})
        p["sentences"]["invented"] = {"text": "You owe an extra fee.", "source": []}
        p["aliases"].append({"field": "close_call.outcome", "brief_value": "mystery", "api_value": "paid", "source": []})
        p["writes"]["transfer"]["source"] = []
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        self.assertNotIn("You owe an extra fee", json.dumps(rp))
        self.assertFalse(any(a.get("brief_value") == "mystery" for a in rp["aliases"]))
        self.assertEqual(rp["transfer"]["queue_map"], {})
        self.assertEqual(rp["writes"]["transfer"]["queue_map"], {})
        self.assertTrue(any("ASSUMPTION" in s and "dropped" in s for s in report["notes"]))
        self.assertIn("x.value", B.source_gaps({"x": {"value": 1}}))
        unsafe = {"identity": {"on_decline": {"outcome": "paid", "reason": "refused", "source": []}}}
        notes = B.source_guard(unsafe)
        self.assertFalse(unsafe["identity"]["on_decline"]["outcome"])
        self.assertTrue(any("identity.on_decline.close" in n for n in notes))
        p["products"]["source"] = []
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        self.assertEqual(rp["products"]["floor_by_type"], {})
        self.assertTrue(any("missing source for a floor" in e for e in DP.unsupported_rules(rp)))

    def test_raw4_counting_is_per_band(self):
        p, text, _ = load(4)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        today = datetime.date(2026, 10, 14)
        self.assertEqual(D.deadline_for(today, 5, rp), datetime.date(2026, 10, 21))
        self.assertEqual(D.deadline_for(today, 16, rp), datetime.date(2026, 10, 15))
        for b in rp["deadline"]["bands"]:
            self.assertTrue(b.get("source"))
        self.assertEqual(DP.bad_quotes({"bands": rp["deadline"]["bands"]}, text), [])

    def test_calendar_rollover_and_legacy_rule(self):
        p, text, _ = load(4)
        rp, _ = B.to_reducer(p, OAS, brief_text=text)
        b = rp["deadline"]["bands"][1]
        b["roll"] = "next"
        self.assertEqual(D.deadline_for(datetime.date(2026, 10, 14), 16, rp), datetime.date(2026, 10, 19))
        b.pop("roll")
        b.pop("rule")
        self.assertEqual(D.deadline_for(datetime.date(2026, 10, 14), 16, rp), datetime.date(2026, 10, 15))
        b["rule"] = "nonsense"
        self.assertTrue(any("rule unknown" in e for e in DP.validate(rp)))
        self.assertTrue(any("rule unknown" in e for e in DP.unsupported_rules(rp)))
        b["rule"] = False
        self.assertTrue(any("rule unknown" in e for e in DP.unsupported_rules(rp)))

    def test_ambiguous_or_unquoted_overrides_are_rejected(self):
        p, text, _ = load(4)
        p["deadline"]["bands"] = [{"name": "band", "days": 2, "max_days_late": 999}]
        p["deadline"]["source"] = [{"file": "t.md", "quote": "2 business days after today. 2 calendar days after today."}]
        B.band_rules(p)
        self.assertNotIn("rule", p["deadline"]["bands"][0])
        self.assertTrue(p["source_errors"])
        p, text, _ = load(4)
        p["deadline"]["bands"][0].update(rule="calendar_days_after_today", source=[{"file": "brief.md", "quote": "Fabricated deadline instruction."}])
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        self.assertTrue(any("source quote is not in the brief" in e for e in DP.unsupported_rules(rp)))
        p, text, _ = load(5)
        p["products"]["route_by_type"] = {"car_loan": {"action": "transfer", "queue": "restructuring", "note": False, "source": []}}
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        self.assertNotIn("route_by_type", rp["products"])
        self.assertTrue(any("missing source for a mandatory route" in e for e in DP.unsupported_rules(rp)))

    def test_raw5_route_and_expected_ledgers(self):
        p, text, cases = load(5)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        self.assertNotIn("car_loan", rp["transfer"]["queue_map"])
        self.assertNotIn("car_loan", rp["writes"]["transfer"]["queue_map"])
        route = rp["products"]["route_by_type"]["car_loan"]
        self.assertEqual((route["action"], route["queue"], route["note"]), ("transfer", "restructuring", False))
        self.assertEqual(DP.bad_quotes({"route": route}, text), [])
        self.assertIn("transfer_to_agent", mandatory_tools(rp))
        scripts = {
            "PUB-11": lambda c: V(c) + [DT(16, 10, "all"), YES, YES, OTHER, OTHER],
            "PUB-12": lambda c: V(c) + [REL("tomorrow", "1"), FLAT, FLAT, YES, OTHER, OTHER],
            "PUB-13": lambda c: V(c) + [NO, TOO, YES, TOO, YES, YES, OTHER, OTHER],
        }
        for c in cases:
            with self.subTest(case=c["id"]):
                ledger, said, st = run_case(rp, c, scripts[c["id"]](c))
                self.assertEqual(diff(c["expected"], ledger), [])
                self.assertFalse(any(it["product_id"] == "p3" for it in (st.get("readback") or {}).get("items", [])))
                calls = [a for a in said if a["type"] == "call_tool"]
                car_writes = [a for a in calls if a.get("args", {}).get("product_id") == "p3"]
                self.assertEqual(car_writes, [])
                if ledger["transfers"]:
                    order = [a["tool"] for a in calls]
                    self.assertEqual(order[-1], "transfer_to_agent")
                    self.assertTrue(all("car loan" not in a.get("text", "").lower() for a in said))

    def test_packed_runtime_includes_routes_and_band_rules(self):
        p, text, cases = load(5)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        code = G.pack_hub(R.hub_source(rp))
        self.assertNotIn("{{", code)
        self.assertLess(len(code.encode()), 70000)
        ns = {"vars": dict(customer_id="test", now="2026-10-14T11:00")}
        exec(compile(code, "packed-reading", "exec"), ns)
        self.assertFalse(ns["vars"].get("hub_error"))

    def test_fresh_raw5_graph_and_transfer_failure(self):
        p, text, cases = load(5)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        wf = G.generate(rp, OAS)
        self.assertEqual(report["errors"], [])
        self.assertEqual(validate_workflow(wf, rp, OAS), [])
        with open(OAS) as f:
            oas = json.load(f)
        c = cases[0]
        for fail_transfer in (False, True):
            calls, passed = [], set()
            def bank(tool, body):
                calls.append((tool, body))
                if tool == "verify_identity":
                    field = body["field"]
                    matched = body["answer"] == c["identity"][field]
                    if matched:
                        passed.add(field)
                    return 200, dict(ok=True, verified=matched, all_verified=set(c["identity"]) <= passed, wrong_answers_left=3)
                if tool == "get_account":
                    return 200, dict(ok=True, products=[dict(v, product_id=f"p{i}") for i, v in enumerate(c["products"], 1)])
                if tool == "transfer_to_agent" and fail_transfer:
                    return 500, dict(error="injected")
                return 200, dict(ok=True)
            events = ["n=kstart;src=user;" + e for e in V(c) + [DT(16, 10, "all"), YES, YES, OTHER, OTHER]]
            rep = walk(wf, oas, dict(c["variables"], customer_id="test"), events, bank)
            self.assertEqual(rep["errors"], [])
            self.assertTrue(rep["ended"])
            writes = [(t, b) for t, b in calls if t in ("create_promise", "add_note", "transfer_to_agent")]
            self.assertEqual([t for t, b in writes], ["create_promise", "create_promise"] + ["transfer_to_agent"] * (2 if fail_transfer else 1))
            self.assertFalse(any(b.get("product_id") == "p3" for t, b in writes))
            closes = [b for t, b in calls if t == "close_call"]
            self.assertEqual(closes[-1]["outcome"], "promise" if fail_transfer else "transferred")

    def test_route_only_and_first_product_route(self):
        p, text, cases = load(5)
        rp, report = B.to_reducer(p, OAS, brief_text=text)
        c = copy.deepcopy(cases[0])
        c["products"] = [c["products"][2]]
        ledger, said, st = run_case(rp, c, V(c))
        self.assertEqual(ledger["transfers"], [{"queue": "restructuring"}])
        self.assertEqual(ledger["promises"], [])
        self.assertEqual(ledger["notes"], [])
        self.assertEqual(ledger["outcome"], "transferred")
        c = copy.deepcopy(cases[0])
        c["products"] = [c["products"][2], c["products"][0]]
        ledger, said, st = run_case(rp, c, V(c) + [YES, YES, OTHER])
        self.assertEqual([it["product_id"] for it in ledger["promises"]], ["p2"])
        self.assertEqual(ledger["transfers"], [{"queue": "restructuring"}])


if __name__ == "__main__":
    unittest.main()
