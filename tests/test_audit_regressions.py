"""Audit counterexamples, with real generated requests and saved extractors. No model/network calls."""
import copy
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import build as B, generator as G, policy_bridge as P
from builder.degrade import degrade
from builder.engine import reducer as R
from builder.graph_walk import oas_schema, validate as validate_body, walk
from builder.validate_workflow import validate
from tests.test_graph_walk import FIX, bank_for, compare

OAS = os.path.join(ROOT, "tools/openapi.json")
with open(OAS) as f:
    API = json.load(f)
with open(os.path.join(ROOT, "tests/e2e-int/submission/brief-a.extracted.json")) as f:
    RAW = json.load(f)
with open(os.path.join(ROOT, "tests/generated/brief-a.reducer_policy.json")) as f:
    POL = json.load(f)


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def api(self, *, renamed=False, required=False, paid_reason=False, broken=None):
        api = copy.deepcopy(API)
        for path, ops in api["paths"].items():
            tool = path.rsplit("/", 1)[-1]
            for op in ops.values():
                schema = op["requestBody"]["content"]["application/json"]["schema"]
                if tool == "close_call":
                    props = schema["properties"]
                    props["reason"]["enum"] = sorted({r["reason"] for r in RAW["closing"]["table"] if r.get("reason")})
                    if paid_reason:
                        props["reason"]["enum"] += ["already_settled", "arrangement_saved"]
                    if required:
                        schema["required"] = list(set(schema.get("required", []) + ["reason"]))
                    if renamed:
                        props["cause"] = props.pop("reason")
                        props["cause"]["description"] = "Source closing reason"
                        schema["required"] = ["cause" if f == "reason" else f for f in schema["required"]]
                    schema["additionalProperties"] = False
                if tool == broken:
                    schema["properties"]["channel"] = {"type": "string"}
                    schema["required"] += ["channel"]
        path = os.path.join(self.tmp.name, "api.json")
        with open(path, "w") as f:
            json.dump(api, f)
        return path, api

    def close_walk(self, raw, path, api, family, reason):
        rp, report = P.to_reducer(raw, path)
        self.assertFalse(report["errors"], report["errors"])
        wf = G.generate(rp, path)
        wf["initial_node"] = "t_close_call"
        wf["test_variables"].update(customer_id="audit-customer", close_outcome=family, close_reason=reason or "")

        def bank(tool, body):
            self.assertEqual(tool, "close_call")
            url = G.oas_tools(path)["close_call"]["url"]
            self.assertEqual(validate_body(api, oas_schema(api, url), body), [], body)
            return 200, {"ok": True}

        rep = walk(wf, api, {}, [], bank)
        self.assertEqual(rep["errors"], [], rep["errors"])
        self.assertTrue(rep["ended"])
        self.assertEqual([c["node"] for c in rep["calls"]], ["t_close_call", "lifecycle:close_call"])
        return rp, rep["calls"]

    def test_renamed_optional_close_body_both_paths(self):
        path, api = self.api(renamed=True)
        for family, reason in (("promise", None), ("paid", None), ("no_promise", "refused")):
            with self.subTest(family=family):
                _, calls = self.close_walk(RAW, path, api, family, reason)
                for c in calls:
                    self.assertNotIn("reason", c["body"])
                    if reason:
                        self.assertEqual(c["body"]["cause"], reason)
                    else:
                        self.assertNotIn("cause", c["body"])
        cfg = {"body": {"outcome": "paid", "cause": "{{close_reason}}"}}
        exec(G.close_preprocess(G.oas_tools(path)["close_call"]), {"config": cfg})
        self.assertNotIn("cause", cfg["body"])
        for value in (0, False, "literal {brace}"):
            cfg = {"body": {"cause": value}}
            exec(G.close_preprocess(G.oas_tools(path)["close_call"]), {"config": cfg})
            self.assertEqual(cfg["body"]["cause"], value)

    def test_paid_and_promise_required_source_reason_preserved(self):
        path, api = self.api(renamed=True, required=True, paid_reason=True)
        raw = copy.deepcopy(RAW)
        reasons = {"paid": "already_settled", "promise": "arrangement_saved"}
        for row in raw["closing"]["table"]:
            if row["outcome"] in reasons:
                row["reason"] = reasons[row["outcome"]]
        for row in raw["events"]:
            if row.get("outcome") == "paid":
                row["reason"] = reasons["paid"]
        raw["topic_checklist"]["paid"]["reason"] = reasons["paid"]
        for row in raw["closing"]["table"]:
            with self.subTest(row=row):
                rp, calls = self.close_walk(raw, path, api, row["outcome"], row["reason"])
                for c in calls:
                    self.assertEqual(c["body"]["cause"], row["reason"])
                if row["outcome"] in reasons:
                    self.assertEqual(R.vocab(rp)[row["outcome"]], (row["outcome"], row["reason"]))
        rp, _ = P.to_reducer(raw, path)
        for row in raw["closing"]["table"]:
            self.assertEqual(R.close_retry(rp, {"outcome": row["outcome"], "reason": row["reason"]}, "HTTP 500"),
                             (row["outcome"], row["reason"]))

    def test_strict_actual_close_schema(self):
        path, api = self.api(renamed=True, required=True)
        schema = oas_schema(api, G.oas_tools(path)["close_call"]["url"])
        for body in ({"customer_id": "x", "outcome": "no_promise"},
                     {"customer_id": "x", "outcome": "no_promise", "cause": "invalid"},
                     {"customer_id": "x", "outcome": "no_promise", "cause": 42}):
            self.assertTrue(validate_body(api, schema, body), body)
        cfg = {"body": {"cause": ""}}
        exec(G.close_preprocess(G.oas_tools(path)["close_call"]), {"config": cfg})
        self.assertIn("cause", cfg["body"], "required fields cannot be silently dropped")
        rp, _ = P.to_reducer(RAW, path)
        self.assertTrue(any("close_call.cause required" in e for e in validate(G.generate(rp, path), rp, path)))

    def identity_failure_raw(self, reason=None):
        # Raw-5's sourced failure pair; the remaining, unrelated policy is the saved Brief A extraction.
        raw = copy.deepcopy(RAW)
        source = [{"file": "brief.md", "quote": "Three wrong answers end it."},
                  {"file": "brief.md", "quote": "The office word is failed_id, and we do not state the account."}]
        raw["identity"]["source"] = source
        raw["identity"]["on_fail"] = {"outcome": "not_verified", "reason": reason}
        for row in raw["closing"]["table"]:
            if row.get("reason") == "failed":
                row.update(outcome="not_verified", reason=reason, when="three wrong identity answers", source=source)
        return raw

    def identity_failure_walk(self, raw, path, api, reason):
        rp, report = P.to_reducer(raw, path)
        self.assertFalse(report["errors"], report["errors"])
        self.assertEqual(rp["closing"]["slots"]["id_failed"], {"outcome": "not_verified", "reason": reason})
        case = next(c for c in FIX["cases"] if c["id"] == "PUB-03")
        events = [s["event"] for s in case["steps"] if s["source"] == "user"]
        rep = walk(G.generate(rp, path), api, case["call_variables"], events, bank_for(case))
        self.assertEqual(rep["errors"], [], rep["errors"])
        self.assertTrue(rep["ended"])
        self.assertEqual(sum(c["tool"] == "verify_identity" for c in rep["calls"]), 3)
        self.assertFalse(any(c["tool"] == "get_account" for c in rep["calls"]))
        calls = [c for c in rep["calls"] if c["tool"] == "close_call"]
        self.assertEqual([c["node"] for c in calls], ["t_close_call", "lifecycle:close_call"])
        expected = {"customer_id": case["call_variables"]["customer_id"], "outcome": "not_verified"}
        field = "cause" if "cause" in G.oas_tools(path)["close_call"]["props"] else "reason"
        if reason is not None:
            expected[field] = reason
        schema = oas_schema(api, G.oas_tools(path)["close_call"]["url"])
        for call in calls:
            self.assertEqual(call["body"], expected)
            self.assertEqual(validate_body(api, schema, call["body"]), [])
        return rep

    def test_raw5_identity_failure_without_optional_reason(self):
        for renamed in (False, True):
            with self.subTest(renamed=renamed):
                path, api = self.api(renamed=renamed)
                self.identity_failure_walk(self.identity_failure_raw(), path, api, None)

    def test_identity_failure_required_sourced_alias_pair(self):
        path, api = self.api(renamed=True, required=True)
        api["paths"]["/close_call"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["cause"]["enum"].append("bad_identity")
        with open(path, "w") as f:
            json.dump(api, f)
        raw = self.identity_failure_raw("wrong_answers")
        raw["identity"]["on_fail"]["outcome"] = "failed_id"
        raw["aliases"] += [
            {"field": "close_call.outcome", "brief_value": "failed_id", "api_value": "not_verified",
             "source": [{"file": "codes.csv", "quote": "failed_id,not_verified"}]},
            {"field": "close_call.reason", "brief_value": "wrong_answers", "api_value": "bad_identity",
             "source": [{"file": "codes.csv", "quote": "wrong_answers,bad_identity"}]}]
        raw["identity"]["source"].append({"file": "brief.md", "quote": "Close failed_id with reason wrong_answers."})
        self.identity_failure_walk(raw, path, api, "bad_identity")

    def test_identity_failure_sourced_only_in_closing_table(self):
        path, api = self.api(renamed=True)
        raw = self.identity_failure_raw()
        raw["identity"].pop("on_fail")
        self.identity_failure_walk(raw, path, api, None)
        path, api = self.api(renamed=True, required=True)
        raw = self.identity_failure_raw("failed")
        raw["identity"]["on_fail"]["reason"] = None
        self.identity_failure_walk(raw, path, api, "failed")

    def test_identity_failure_unbindable_pair_requires_safe_degrade(self):
        for reason, outcome, required, renamed in ((None, "not_verified", True, False),
                                                   (None, "not_verified", True, True),
                                                   ("unmapped_failure", "not_verified", False, True),
                                                   (None, "unmapped_identity_failure", False, True)):
            with self.subTest(reason=reason, outcome=outcome, required=required, renamed=renamed):
                path, _ = self.api(renamed=renamed, required=required)
                raw = self.identity_failure_raw(reason)
                raw["identity"]["on_fail"]["outcome"] = outcome
                rp, report = P.to_reducer(raw, path)
                self.assertTrue(any(m["action"] == "block" and m["policy_path"].startswith("identity.on_fail")
                                    for m in report["api_mismatch"]), report)
                errors = validate(G.generate(rp, path), rp, path)
                self.assertTrue(any(e.startswith("24:") and "identity.on_fail" in e for e in errors), errors)
                self.assertIsNone(degrade(rp, errors)[0])
                # Even a matching OAS enum value elsewhere is not a source for a missing failure reason.
                if required:
                    self.assertIsNone(rp["closing"]["slots"]["id_failed"]["reason"])
                    with patch.object(B, "reextract_fields", return_value={}), \
                         patch("builder.binding_assist.assist", side_effect=AssertionError("unexpected model call")):
                        rep = {k: [] for k in ("quotes_rejected", "quotes_repaired", "quotes_unverified", "errors", "oas_warnings", "core_missing")}
                        result = B.build([os.path.join(ROOT, "briefs/brief-a.md")], path, "id-failed", None,
                                         os.path.join(self.tmp.name, "sub"), os.path.join(self.tmp.name, "trace"),
                                         1, 1500, lambda *a: (copy.deepcopy(raw), dict(rep, seconds=0)),
                                         fallback=None, examiner=None)
                    self.assertEqual(result["exit_code"], 2, result)
                    self.assertTrue(result["fallback_required"])
                    self.assertEqual(result["next"], "L3")
                    self.assertNotIn("export", result)
                    self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "sub")))

    def test_public_pub03_identity_close_unchanged(self):
        path, api = self.api()
        rep = self.identity_failure_walk(RAW, path, api, "failed")
        from builder.graph_walk import hub_actions
        case = next(c for c in FIX["cases"] if c["id"] == "PUB-03")
        self.assertEqual(compare([s["action"] for s in case["steps"]], hub_actions(rep)), [])

    def test_renamed_enum_checked_by_bridge_and_validator(self):
        path, _ = self.api(renamed=True)
        raw = copy.deepcopy(RAW)
        raw["closing"]["table"][2]["reason"] = "not_allowed"
        rp, report = P.to_reducer(raw, path)
        self.assertTrue(rp["closing"]["table"][2]["blocked"])
        self.assertTrue(any(m["value"] == "not_allowed" for m in report["api_mismatch"]))
        rp, _ = P.to_reducer(RAW, path)
        rp["closing"]["slots"]["id_failed"]["reason"] = "not_allowed"
        self.assertTrue(any(e.startswith("14:") for e in validate(G.generate(rp, path), rp, path)))

    def test_resolved_notes_policy_wins_in_both_file_orders(self):
        old_ban = "Old: Do not use add_note."
        new_permit = "Approved memo: Write a note for every refusal."
        old_permit = "Old: Write a note for every refusal."
        new_ban = "Approved memo: Do not use add_note."
        for enabled, old, new in ((True, old_ban, new_permit), (False, old_permit, new_ban)):
            raw = copy.deepcopy(RAW)
            raw["writes"]["notes"] = {"enabled": enabled, "when": "every refusal" if enabled else "never"}
            raw["writes"]["source"] = [{"file": "memo.md", "quote": new}]
            policies = []
            for text in (old + "\n" + new, new + "\n" + old):
                rp, _ = P.to_reducer(raw, OAS, brief_text=text)
                self.assertIs(rp["writes"]["notes"]["enabled"], enabled)
                self.assertEqual("t_add_note" in G.generate(rp, OAS)["nodes"], enabled)
                policies.append(rp)
            self.assertEqual(policies[0], policies[1])
        # A sourced `when` also wins when the extractor omitted the redundant boolean.
        for when, enabled in (("every refusal", True), ("never", False)):
            raw["writes"]["notes"] = {"when": when}
            rp, _ = P.to_reducer(raw, OAS, brief_text=old_ban + "\n" + old_permit)
            self.assertIs(rp["writes"]["notes"]["enabled"], enabled)
        raw["writes"]["notes"] = {}
        rp, report = P.to_reducer(raw, OAS, brief_text=new_permit)
        self.assertTrue(rp["writes"]["notes"]["enabled"])
        self.assertTrue(any("ASSUMPTION writes.notes.enabled" in n for n in report["notes"]))

    def test_sourced_queue_reason_and_disclosure_not_overridden(self):
        raw = copy.deepcopy(RAW)
        raw["writes"]["transfer"]["queue_map"] = {"hardship": "support"}
        raw["writes"]["notes"]["reasons"] = {"refused": "dispute"}
        raw["meta"]["assistant_disclosure_forbidden"] = False
        raw["identity"]["gate"] = {"ask": "Can you talk?", "on_no": "callback", "callback_ask": "What time?"}
        text = "Hardship: transfer to human.\nnote_reason,refused,old,refused\nDo not say you are a robot."
        rp, _ = P.to_reducer(raw, OAS, brief_text=text)
        self.assertEqual(rp["transfer"]["queue_map"]["hardship"], "support")
        self.assertEqual(rp["writes"]["notes"]["reasons"]["refused"], "dispute")
        self.assertIs(rp["meta"]["assistant_disclosure_forbidden"], False)
        self.assertEqual(rp["identity"]["gate"], raw["identity"]["gate"])

    def test_callback_days_and_inclusive_hours(self):
        pol = copy.deepcopy(POL)
        today = dt.date(2031, 1, 10)
        nb = R.add_business_days(today, 1, pol)
        cb = pol["writes"]["callback"]
        cb.update(days="next_business_day_only", start="10:00", end="18:00", inclusive=True, after_now=True)
        self.assertFalse(R._callback_ok(pol, {}, today, "12:00", today, "09:00"))
        self.assertTrue(R._callback_ok(pol, {}, nb, "10:00", today, "09:00"))
        self.assertTrue(R._callback_ok(pol, {}, nb, "18:00", today, "09:00"))
        cb["inclusive"] = False
        for tm in ("09:59", "10:00", "18:00", "18:01"):
            self.assertFalse(R._callback_ok(pol, {}, nb, tm, today, "09:00"), tm)
        self.assertTrue(R._callback_ok(pol, {}, nb, "10:01", today, "09:00"))
        cb.update(days="today_only", inclusive=True)
        self.assertFalse(R._callback_ok(pol, {}, nb, "12:00", today, "09:00"))
        self.assertTrue(R._callback_ok(pol, {}, today, "12:00", today, "09:00"))
        cb["days"] = "today_or_next_business_day"
        self.assertFalse(R._callback_ok(pol, {}, today, "12:00", today, "12:00"))
        for tm in ("25:00", "12:60", "1x:00"):
            self.assertFalse(R._callback_ok(pol, {}, nb, tm, today, "09:00"), tm)

    def test_unsupported_source_rules_loudly_require_l3(self):
        variants = [("date_rule", "customer_named"), ("amount_rule", "same_as_previous"),
                    ("days", "every_day"), ("start", "25:00"), ("inclusive", "false")]
        for key, value in variants:
            with self.subTest(key=key):
                raw = copy.deepcopy(RAW)
                if key.endswith("_rule"):
                    raw["attempts"]["plan"]["early"][0][key] = value
                else:
                    raw["writes"]["callback"][key] = value
                rp, report = P.to_reducer(raw, OAS)
                self.assertTrue(any("ASSUMPTION unsupported source rule" in n for n in report["notes"]))
                errors = validate(G.generate(rp, OAS), rp, OAS)
                self.assertTrue(any(e.startswith("24:") for e in errors), errors)
                self.assertIsNone(degrade(rp, errors)[0])

    def test_mandatory_tools_and_speech_never_stripped(self):
        for tool in ("add_note", "schedule_callback", "transfer_to_agent"):
            rp = copy.deepcopy(POL)
            rp["writes"]["notes"]["enabled"] = True
            self.assertIsNone(degrade(rp, [f"12: {tool} required field missing"])[0], tool)
        for rp, err in (({"hooks": [{"text": "Required.", "source": ["Say Required."]}]}, "17: hook point invalid"),
                        ({"events": [{"say": "Required.", "source": ["Say Required."]}]}, "15: events say invalid")):
            self.assertIsNone(degrade(rp, [err])[0])
        blocked = {"transfer": {"queue_map": {}, "source": ["Required transfer."]},
                   "writes": {"transfer": {"queue_map": {"human": "missing_queue"}}}}
        self.assertIsNone(degrade(blocked, ["12: transfer_to_agent field not bound"])[0])
        gate = {"identity": {"gate": {"on_no": "callback"}}}
        self.assertIsNone(degrade(gate, ["12: schedule_callback field not bound"])[0])

    def build_case(self, raw, oas, fallback=None):
        report = {"seconds": 0, "quotes_rejected": [], "quotes_repaired": [], "quotes_unverified": [],
                  "errors": [], "oas_warnings": [], "core_missing": []}
        ex = lambda *args: (copy.deepcopy(raw), report)
        with patch("builder.build.reextract_fields", return_value={}), patch("builder.build.reextract_core", return_value={}):
            return B.build([os.path.join(ROOT, "briefs/brief-a.md")], oas, "audit", B.MockFreya(),
                           os.path.join(self.tmp.name, "submission"), os.path.join(self.tmp.name, "traces"),
                           1, 1500, ex, fallback=fallback)

    def fallback(self, good=True):
        class Candidate:
            def start(self):
                return self
            def cancel(self):
                pass
            def wait(self, seconds):
                return {"workflow": {"initial_node": "full", "nodes": {"full": {"node_type": "end_call"}}} if good else None,
                        "errors": [] if good else ["full candidate failed"], "seconds": 0}
        return lambda *args: Candidate()

    def test_mandatory_failure_selects_full_l3(self):
        path, _ = self.api(broken="schedule_callback")
        result = self.build_case(RAW, path, self.fallback())
        self.assertEqual(result["fallback_used"], "L3", result)
        self.assertNotIn("partial", result)
        self.assertNotIn("degraded", result)

    def test_unsupported_rule_reaches_l3_in_real_build(self):
        raw = copy.deepcopy(RAW)
        raw["attempts"]["plan"]["early"][0]["date_rule"] = "customer_named"
        result = self.build_case(raw, OAS, self.fallback())
        self.assertEqual(result["fallback_used"], "L3", result)
        self.assertEqual(result["main_signal"], "S5")

    def test_optional_failure_prefers_full_l3_over_partial(self):
        path, _ = self.api(broken="schedule_callback")
        raw = copy.deepcopy(RAW)
        raw["writes"].pop("callback")
        raw["events"], raw["opening_situations"] = [], {}
        result = self.build_case(raw, path, self.fallback())
        self.assertEqual(result["fallback_used"], "L3", result)
        self.assertNotIn("partial", result)

    def test_partial_only_after_failed_full_candidate_and_traced(self):
        path, _ = self.api(broken="schedule_callback")
        raw = copy.deepcopy(RAW)
        raw["writes"].pop("callback")
        raw["events"], raw["opening_situations"] = [], {}
        result = self.build_case(raw, path, self.fallback(False))
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue(result["partial"])
        with open(result["trace"]) as f:
            events = [json.loads(line) for line in f]
        partial = next(e for e in events if e["event"] == "partial_agent")
        self.assertTrue(partial["last_resort"])
        self.assertEqual(partial["l3_errors"], ["full candidate failed"])
        self.assertTrue(next(e for e in events if e["event"] == "assumptions")["partial_agent"])


if __name__ == "__main__":
    unittest.main()
