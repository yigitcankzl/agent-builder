"""Source-backed per-write notifications, including the actual packed graph. Offline only."""
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
from builder.selftest import run_selftest
from builder.validate_workflow import validate
from tests.test_graph_walk import FIX, bank_for
from tests.test_rehearsal import OTHER, REL, V, YES

OAS = os.path.join(ROOT, "tools/openapi.json")
with open(OAS) as f:
    API = json.load(f)
with open(os.path.join(ROOT, "tests/fixtures/reducer/raw5.extracted.json")) as f:
    RAW = json.load(f)
PUBLIC = next(c for c in FIX["cases"] if c["id"] == "PUB-11")
CASE = dict(variables=PUBLIC["call_variables"], identity=PUBLIC["identity"], products=PUBLIC["account"])
NOTICE = RAW["sentences"]["text_message"]["text"]


class WriteNotificationTests(unittest.TestCase):
    def policy(self, raw=RAW, retries=None):
        policy, report = B.to_reducer(raw, OAS)
        self.assertEqual(report["errors"], [])
        if retries is not None:
            policy["tools"]["create_promise"]["retries"] = retries
        return policy

    def queued(self, policy, count=2):
        cv = dict(CASE["variables"], customer_id="c_write_probe")
        state = R.init_state(policy, cv)
        state["verified"] = "yes"
        rows = [dict(row, product_id="p%d" % (i + 1)) for i, row in enumerate(CASE["products"][:count])]
        R.load_products(policy, state, rows, R._d(cv["now"]))
        for p, pd in zip(state["products"], state["_pd"]):
            p.update(status="confirmed", offer=dict(amount=pd["past_due"], date=pd["deadline"]))
        state["_confirmed_readback"] = [dict(product_id=p["id"], **p["offer"]) for p in state["products"]]
        state["_queue"] = [p["id"] for p in state["products"]]
        action = R.next_write(policy, state, cv)
        return cv, state, action

    def result(self, policy, cv, state, success=True, status=None):
        p = state["pending"]
        event = dict(node=p["node"], success=p["snap_success"] + int(success),
                     failure=p["snap_failure"] + int(not success),
                     status_code=status or (200 if success else 500), ok=str(success).lower(), data=dict(ok=success))
        return R.step(policy, state, None, event, cv["now"], cv)

    def resume(self, policy, cv, state):
        return R.step(policy, state, None, None, cv["now"], cv)

    def test_one_success_one_immediate_notice(self):
        policy = self.policy()
        cv, state, action = self.queued(policy, 1)
        state, action = self.result(policy, cv, state)
        self.assertEqual(action["type"], "say_exact")
        self.assertEqual(action["text"], NOTICE)
        self.assertTrue(action["resume_writes"])
        self.assertIsNone(state["pending"])
        state, action = self.resume(policy, cv, state)
        self.assertNotIn(NOTICE, action.get("text", "") + action.get("farewell", ""))

    def test_two_successes_notify_before_next_write(self):
        policy = self.policy()
        cv, state, action = self.queued(policy)
        for pid in ("p1", "p2"):
            self.assertEqual(action["tool"], "create_promise")
            self.assertEqual(action["args"]["product_id"], pid)
            state, action = self.result(policy, cv, state)
            self.assertEqual(action["text"], NOTICE)
            self.assertTrue(action["resume_writes"])
            state, action = self.resume(policy, cv, state)
        self.assertNotIn(NOTICE, action.get("text", "") + action.get("farewell", ""))

    def test_failed_write_and_retry_do_not_claim_success(self):
        policy = self.policy(retries=1)
        cv, state, action = self.queued(policy, 1)
        args = action["args"]
        state, action = self.result(policy, cv, state, False)
        self.assertEqual(action, dict(type="call_tool", tool="create_promise", args=args))
        state, action = self.result(policy, cv, state, False)
        self.assertFalse(action.get("resume_writes"))
        self.assertNotIn(NOTICE, action.get("text", "") + action.get("farewell", ""))
        self.assertFalse(any(p["status"] == "persisted" for p in state["products"]))

    def test_retry_notifies_only_when_it_succeeds(self):
        policy = self.policy(retries=1)
        cv, state, action = self.queued(policy, 1)
        state, action = self.result(policy, cv, state, False)
        state, action = self.result(policy, cv, state)
        self.assertEqual(action["text"], NOTICE)
        # A spent result without a pending write cannot create another notification.
        spent = dict(node="t_create_promise", success=1, failure=1, status_code=200, ok="true", data=dict(ok=True))
        state, action = R.step(policy, state, None, spent, cv["now"], cv)
        self.assertNotIn(NOTICE, action.get("text", "") + action.get("farewell", ""))

    def test_200_with_ok_false_is_not_a_success(self):
        policy = self.policy(retries=1)
        cv, state, action = self.queued(policy, 1)
        state, action = self.result(policy, cv, state, False, 200)
        self.assertEqual(action["type"], "call_tool")
        self.assertFalse(action.get("resume_writes"))

    def walk_case(self, policy, case=PUBLIC, failures=0):
        wf = G.generate(policy, OAS)
        self.assertEqual(validate(wf, policy, OAS), [])
        c = dict(variables=case["call_variables"], identity=case["identity"], products=case["account"])
        bank0, verified, left = bank_for(case), set(), [failures]
        def bank(tool, body):
            if tool == "verify_identity":
                self.assertEqual(body["answer"], c["identity"][body["field"]])
                verified.add(body["field"])
                return 200, dict(ok=True, verified=True, all_verified=set(c["identity"]) <= verified, wrong_answers_left=3)
            if tool == "create_promise" and left[0]:
                left[0] -= 1
                return 500, dict(error="test failure")
            return bank0(tool, body)
        events = V(c) + [REL("tomorrow", "all"), YES, OTHER, OTHER]
        rep = walk(wf, API, c["variables"], ["n=aaaaaa;src=user;" + e for e in events], bank)
        self.assertEqual(rep["errors"], [])
        self.assertTrue(rep["ended"])
        return rep

    def test_packed_graph_speaks_between_each_success_and_next_tool(self):
        for failures in (0, 1):
            with self.subTest(failures=failures):
                rep = self.walk_case(self.policy(retries=failures), failures=failures)
                writes = [c for c in rep["calls"] if c["tool"] == "create_promise"]
                self.assertEqual(len(writes), 2 + failures)
                self.assertEqual(sum(NOTICE in text for _, text in rep["speech"]), 2)
                entered = rep["entered"]
                positions = [i for i, name in enumerate(entered) if name == "t_create_promise"]
                for i, call in zip(positions, writes):
                    self.assertEqual(entered[i + 1], "hub")
                    self.assertEqual(entered[i + 2], "write_say" if call["status_code"] == 200 else "t_create_promise")
                self.assertEqual([text for node, text in rep["speech"] if node == "write_say"], [NOTICE, NOTICE])

    def test_explicit_combined_notification_stays_after_all_writes(self):
        raw = copy.deepcopy(RAW)
        tm = raw["sentences"]["text_message"]
        tm["source"] = [dict(file="combined.md", quote='After all successful create_promise writes, say once "' + NOTICE + '"')]
        rep = self.walk_case(self.policy(raw))
        self.assertEqual(sum(NOTICE in text for _, text in rep["speech"]), 1)
        self.assertNotIn("write_say", rep["entered"])
        self.assertEqual(sum(c["tool"] == "create_promise" for c in rep["calls"]), 2)

    def test_combined_notice_not_confused_with_a_different_per_write_instruction(self):
        raw = copy.deepcopy(RAW)
        raw["sentences"]["text_message"]["source"] = [dict(file="combined.md", quote=
            'After each successful create_promise, update the ledger. After all promises are recorded, say once "' + NOTICE + '"')]
        policy = self.policy(raw)
        self.assertFalse(policy["sentences"]["text_message"].get("after_each_success"))
        self.assertEqual(sum(NOTICE in text for _, text in self.walk_case(policy)["speech"]), 1)

    def test_generic_quote_wording_not_max_times_controls_scope(self):
        for timing in ("After every successful create_promise", "After each recorded promise", "After every successful write"):
            with self.subTest(timing=timing):
                raw = copy.deepcopy(RAW)
                tm = raw["sentences"]["text_message"]
                tm["max_times"] = 1   # a contradictory extracted cap must not cancel the source's 'every'
                tm["source"] = [dict(file="another-brief.md", quote=timing + ', say "' + NOTICE + '"')]
                rep = self.walk_case(self.policy(raw))
                self.assertEqual(sum(NOTICE in text for _, text in rep["speech"]), 2)

    def test_failed_packed_write_has_no_notification(self):
        rep = self.walk_case(self.policy(), failures=2)   # saved Raw-5 policy permits no retry
        self.assertEqual(sum(c["tool"] == "create_promise" for c in rep["calls"]), 2)
        self.assertFalse(any(NOTICE in text for _, text in rep["speech"]))
        self.assertNotIn("write_say", rep["entered"])

    def test_notification_scope_must_come_from_its_quote_not_cap_or_input_flag(self):
        raw = copy.deepcopy(RAW)
        tm = raw["sentences"]["text_message"]
        tm["after_each_success"] = True
        tm["source"] = [dict(file="combined.md", quote='Say "' + NOTICE + '" after the writes.')]
        policy = self.policy(raw)
        self.assertFalse(policy["sentences"]["text_message"].get("after_each_success"))
        self.assertEqual(sum(NOTICE in text for _, text in self.walk_case(policy)["speech"]), 1)

    def test_public_a_and_ab_keep_combined_notification(self):
        for name, case_id in (("brief-a", "PUB-01"), ("brief-ab", "PUB-11")):
            with self.subTest(name=name):
                with open(os.path.join(ROOT, "tests/e2e-int/submission", name + ".extracted.json")) as f:
                    policy = self.policy(json.load(f))
                notice = policy["sentences"]["text_message"]["text"]
                self.assertFalse(policy["sentences"]["text_message"].get("after_each_success"))
                rep = self.walk_case(policy, next(c for c in FIX["cases"] if c["id"] == case_id))
                self.assertEqual(sum(notice in text for _, text in rep["speech"]), 1)
                self.assertNotIn("write_say", rep["entered"])

    def test_fresh_raw_policy_selftest(self):
        report = run_selftest(self.policy(), OAS)
        self.assertEqual(report["failed"], 0, report["failures"])


if __name__ == "__main__":
    unittest.main()
