"""A complete question in an unfinished utterance must be answered without consuming its pending value."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import generator as G
from builder.engine import reducer as R
from tests.test_reducer_sequences import POL, FIX
from tests.test_reducer_rules import CV, NOW, tool, to_statement, to_readback

PARTIAL_ROBOT = "kind=topic;also=none;st=partial;prod=;t=robot"
CASE = next(c for c in FIX["cases"] if c["id"] == "PUB-04")
ACCOUNT = next(s["tool_event"]["data"]["products"] for s in CASE["steps"]
               if s["source"] == "tool" and s["tool_event"]["node"] == "t_get_account")
PENDING = ("phase", "q", "identity", "products", "_pd", "offer", "readback", "cur", "counters", "pending", "_queue", "_last_ask", "_idp")
TOKENS = iter(range(1, 10000))


def say(pol, st, body):
    st = copy.deepcopy(st)
    tok = "kp%04x" % next(TOKENS)
    st["tok"] = tok
    ev = R.parse_event("n=" + tok + ";src=user;" + body, st, R.CONTRACT_TOPICS)
    assert ev is not None, "test event must not be stale"
    actual, act = R.step(pol, st, ev, None, NOW, CV)
    actual["last_tok"] = tok
    return actual, act


def answer(pol, topic, st=None):
    if topic == "purpose" and st is not None and st.get("verified") != "yes" and R.caller_line(pol) \
            and not (R.event_row(pol, "purpose") or {}).get("say"):
        return R.caller_line(pol)    # before verification 'what is this about?' is answered with who is calling (951431e)
    if topic == "terms":
        return R.brief_sentence(pol, "no_other_terms", R.D_NO_TERMS)
    return (R.event_row(pol, topic) or {}).get("say") or (R.D_PROTECT if topic == "purpose" else "")


def stages(pol):
    opening = R.init_state(pol, CV)
    identity, _ = say(pol, opening, "kind=who;also=none;st=complete;prod=;who=self;party=")
    third = dict(copy.deepcopy(opening), phase="third_party", who="other", q="callback_time")
    offer, _ = to_statement(pol)
    offer, _ = say(pol, offer, "kind=no;also=none;st=complete;prod=")
    readback = to_readback(pol)
    wrapup = dict(copy.deepcopy(readback), phase="wrapup", q="none")
    return [opening, identity, third, offer, readback, wrapup]


class PartialQuestionTests(unittest.TestCase):
    def test_live_pub04_question_then_date_and_promise(self):
        pol = POL["A"]
        st, _ = to_statement(pol, ACCOUNT)
        st, _ = say(pol, st, "kind=date;also=none;st=complete;prod=;d=6;m=11;wk=none;vague=no")
        before = copy.deepcopy(st)
        st, act = say(pol, st, PARTIAL_ROBOT)
        self.assertEqual(act, dict(type="say_exact", text=answer(pol, "robot") + " " + R.D_CONTINUE))
        self.assertTrue(all(st.get(k) == before.get(k) for k in PENDING))
        st, act = say(pol, st, "kind=date;also=none;st=complete;prod=;d=23;wk=none;vague=no")
        self.assertEqual(st["q"], "readback")
        self.assertIn("23 October", act["text"])
        st, act = say(pol, st, "kind=yes;also=none;st=complete;prod=")
        self.assertEqual(act["tool"], "create_promise")
        self.assertEqual({k: act["args"][k] for k in ("product_id", "amount", "date")}, CASE["ledger"]["promises"][0])
        st, _ = tool(pol, st, dict(ok=True))
        st, act = say(pol, st, "kind=other;also=none;st=none;prod=")
        self.assertEqual((act["type"], act["outcome"]), ("close", "promise"))

    def test_primary_and_secondary_questions_in_every_phase(self):
        for name, pol in POL.items():
            for st in stages(pol):
                st["_idp"] = {"phone_last4": {"digits": "44"}}
                for topic in ("robot", "scam", "purpose", "unknown_info", "terms"):
                    for body in (f"kind=topic;also=date;st=partial;prod=;t={topic};d=2",
                                 f"kind=date;also={topic};st=partial;prod=;d=2",
                                 f"kind=amount;also=topic;st=partial;prod=;t={topic};amt=50",
                                 f"kind=other;also={topic};st=partial;prod="):
                        with self.subTest(policy=name, phase=st["phase"], body=body):
                            before = copy.deepcopy(st)
                            actual, act = say(pol, copy.deepcopy(st), body)
                            self.assertEqual(act, dict(type="say_exact", text=(answer(pol, topic, st) + " " + R.D_CONTINUE).strip()))
                            for k in PENDING:
                                self.assertEqual(actual.get(k), before.get(k), k)
                            self.assertNotIn("_info_next", actual)

    def test_identity_piece_is_still_accumulated_with_secondary_question(self):
        pol = POL["A"]
        st = R.init_state(pol, CV)
        st, _ = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, act = say(pol, st, "kind=identity;also=robot;st=partial;prod=;field=date_of_birth;ans=;d=14;m=3")
        self.assertEqual(st["_idp"]["date_of_birth"], {"d": 14, "m": 3})
        self.assertEqual(act["text"], answer(pol, "robot") + " " + R.D_CONTINUE)
        self.assertIsNone(st["pending"])

    def test_answer_and_continue_come_from_the_policy(self):
        pol = copy.deepcopy(POL["A"])
        pol["sentences"]["continue_line"]["text"] = "Please finish your thought."
        for topic in ("robot", "purpose", "scam"):
            row = next(r for r in pol["events"] if r["topic"] == topic)
            row["say"] = "The configured answer for " + topic + "."
            for st in stages(pol):
                _, act = say(pol, st, f"kind=topic;also=none;st=partial;prod=;t={topic}")
                self.assertEqual(act["text"], row["say"] + " Please finish your thought.")

    def test_repeated_partial_questions_do_not_exhaust_the_pending_flow(self):
        pol = POL["A"]
        for st in stages(pol):
            before = copy.deepcopy(st)
            for _ in range(R.RESAY_CAP + 3):
                st, act = say(pol, st, PARTIAL_ROBOT)
                self.assertEqual(act["text"], answer(pol, "robot") + " " + R.D_CONTINUE)
                for k in PENDING:
                    self.assertEqual(st.get(k), before.get(k), k)

    def test_plain_partial_is_unchanged_and_action_topics_do_not_execute(self):
        pol = POL["A"]
        st, _ = to_statement(pol)
        for body in ("kind=date;also=none;st=partial;prod=;d=2",
                     "kind=topic;also=none;st=partial;prod=;t=human",
                     "kind=topic;also=none;st=partial;prod=;t=hardship"):
            actual, act = say(pol, copy.deepcopy(st), body)
            # no question in it: the continue line, or the plan guard's clarify at the open ask (24ec05a invariant)
            self.assertEqual(act["type"], "say_exact")
            self.assertIn(act["text"], (R.D_CONTINUE, R.D_OFFER_NUDGE))
            self.assertEqual(actual["counters"], st["counters"])
            self.assertIsNone(actual["pending"])

    def test_packed_code_answers_in_same_run_and_retains_state(self):
        pol = POL["A"]
        st, _ = to_statement(pol, ACCOUNT)
        st, _ = say(pol, st, "kind=date;also=none;st=complete;prod=;d=6;m=11;wk=none;vague=no")
        code = G.pack_hub(R.hub_source(pol))
        self.assertLess(len(code.encode()), 60000)
        self.assertNotIn("{{", code)
        vars_ = dict(CV, st=json.dumps(st), ev_tok="kabcde", ev="n=kabcde;src=user;" + PARTIAL_ROBOT)
        exec(compile(code, "partial-question-hub", "exec"), {"vars": vars_})
        self.assertFalse(vars_.get("hub_error"), vars_.get("hub_error"))
        self.assertEqual(vars_["route"], "say")
        self.assertEqual(vars_["say_next"], answer(pol, "robot") + " " + R.D_CONTINUE)
        actual = json.loads(vars_["st"])
        for k in PENDING:
            self.assertEqual(actual.get(k), st.get(k), k)
        self.assertLess(len(json.dumps(vars_).encode()), 10000)


if __name__ == "__main__":
    unittest.main()
