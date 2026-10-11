"""Identity questions are interruptions, not refusals or wrong security answers."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import event_field as E, reducer as R
from builder import generator as G
from tests.test_partial_questions import say
from tests.test_reducer_rules import CV, tool
from tests.test_reducer_sequences import POL


def start(pol):
    return say(pol, R.init_state(pol, CV), "kind=who;also=none;st=complete;prod=;who=self;party=")[0]


class IdentityQuestionTests(unittest.TestCase):
    def question(self, pol, st, body, answer=None):
        before = copy.deepcopy(st)
        st, act = say(pol, st, body)
        ask = pol["identity"]["questions"][before["identity"]["idx"]]["ask"]
        self.assertEqual(act, dict(type="say_exact", text=(answer or R.caller_line(pol)) + " " + ask))
        for key in ("identity", "q", "phase", "counters", "pending", "_last_ask", "_id_other", "_idp", "products"):
            self.assertEqual(st.get(key), before.get(key), key)
        self.assertNotIn("_info_next", st)
        self.assertEqual(st["verified"], "no")
        return st

    def test_live_two_questions_across_identity_fields(self):
        for name, pol in POL.items():
            with self.subTest(policy=name):
                st = start(pol)
                st = self.question(pol, st, "kind=topic;also=none;st=complete;prod=;t=purpose")
                st, act = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
                self.assertEqual(act["tool"], "verify_identity")
                st, _ = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
                self.assertEqual(st["q"], "id_phone_last4")
                st = self.question(pol, st, "kind=topic;also=none;st=complete;prod=;t=purpose")
                st, act = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
                self.assertEqual(act["tool"], "verify_identity")
                st, act = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
                self.assertEqual((st["verified"], act["tool"]), ("yes", "get_account"))
                self.assertEqual(st["identity"]["refusals"], 0)
                self.assertEqual(st["identity"]["wrong"], 0)

    def test_primary_secondary_and_repeated_questions(self):
        shapes = (
            "kind=topic;also=none;st=complete;prod=;t=purpose",
            "kind=other;also=topic;st=complete;prod=;t=purpose",
            "kind=no;also=purpose;st=complete;prod=",
            "kind=topic;also=no;st=complete;prod=;t=purpose",
            "kind=reject;also=topic;st=complete;prod=;t=purpose;why=flat",
            "kind=identity;also=purpose;st=complete;prod=;field=date_of_birth;ans=",
            "kind=topic;also=purpose;st=complete;prod=;t=other",
        )
        for name, pol in POL.items():
            for body in shapes:
                with self.subTest(policy=name, body=body):
                    st = start(pol)
                    for _ in range(R.ID_OTHER_CAP + 2):
                        st = self.question(pol, st, body)

    def test_policy_answer_and_exact_pending_question(self):
        pol = copy.deepcopy(POL["A+B"])
        row = R.event_row(pol, "purpose")
        row["say"] = "We verify identity to protect your privacy."
        row["source"] = [dict(file="test-brief.md", quote=row["say"])]
        pol["identity"]["questions"][0]["ask"] = "Please provide the configured security answer?"
        st = self.question(pol, start(pol), "kind=topic;also=none;st=complete;prod=;t=purpose", row["say"])
        self.assertEqual(st["q"], "id_date_of_birth")

    def test_no_pre_verification_account_or_debt_disclosure(self):
        for name, pol in POL.items():
            with self.subTest(policy=name):
                st = self.question(pol, start(pol), "kind=topic;also=none;st=complete;prod=all;t=purpose;amt=987654")
                self.assertIsNone(st["pending"])
                self.assertEqual(st["products"], [])
                st = self.question(pol, st, "kind=topic;also=none;st=complete;prod=all;t=terms;amt=987654")
                self.assertEqual(st["products"], [])

    def test_question_with_actual_answer_still_verifies(self):
        for name, pol in POL.items():
            with self.subTest(policy=name):
                st, act = say(pol, start(pol), "kind=topic;also=identity;st=complete;prod=;t=purpose;field=date_of_birth;ans=1990-01-01")
                self.assertEqual(act["tool"], "verify_identity")
                self.assertEqual(st["identity"]["refusals"], 0)
                st, act = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
                self.assertEqual(act["text"], R.caller_line(pol) + " " + pol["identity"]["questions"][1]["ask"])

    def test_explicit_refusal_unchanged(self):
        for name, pol in POL.items():
            for body in ("kind=topic;also=none;st=complete;prod=;t=decline", "kind=no;also=none;st=complete;prod=",
                         "kind=topic;also=purpose;st=complete;prod=;t=decline"):
                with self.subTest(policy=name, body=body):
                    st, act = say(pol, start(pol), body)
                    self.assertEqual((st["phase"], st["identity"]["refusals"]), ("identity", 1))
                    st, act = say(pol, st, body)
                    self.assertEqual((act["type"], act["outcome"], act["reason"]), ("close", *R.slot(pol, "declined")))
                    self.assertEqual(st["identity"]["wrong"], 0)

    def test_actual_wrong_answers_count_at_configured_limit(self):
        for name, original in POL.items():
            for limit in (2, 3):
                with self.subTest(policy=name, limit=limit):
                    pol = copy.deepcopy(original)
                    pol["identity"]["max_wrong"] = limit
                    st = start(pol)
                    for n in range(1, limit + 1):
                        st, act = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1980-01-01")
                        self.assertEqual(act["tool"], "verify_identity")
                        st, act = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=limit - n))
                        self.assertEqual(st["identity"]["wrong"], n)
                        if n < limit:
                            st = self.question(pol, st, "kind=topic;also=none;st=complete;prod=;t=purpose")
                    self.assertEqual((act["type"], act["outcome"], act["reason"]), ("close", *R.slot(pol, "id_failed")))

    def test_packed_hub_reasks_without_consuming_identity_attempts(self):
        pol = POL["A+B"]
        code = G.pack_hub(R.hub_source(pol))
        st = start(pol)
        for idx in range(2):
            vars_ = dict(CV, st=json.dumps(st), ev_tok="kabcde", ev="n=kabcde;src=user;kind=topic;also=none;st=complete;prod=;t=purpose")
            exec(compile(code, "identity-question-hub", "exec"), {"vars": vars_})
            self.assertFalse(vars_.get("hub_error"), vars_.get("hub_error"))
            self.assertEqual(vars_["route"], "say")
            self.assertEqual(vars_["say_next"], R.caller_line(pol) + " " + pol["identity"]["questions"][idx]["ask"])
            st = json.loads(vars_["st"])
            self.assertEqual(st["identity"]["refusals"], 0)
            self.assertEqual(st["identity"]["wrong"], 0)
            if idx == 0:
                st, _ = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
                st, _ = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))

    def test_extraction_contract_distinguishes_question_from_refusal(self):
        prompt = E.field(dict(topics=R.CONTRACT_TOPICS, identity_fields=["security_field"]))["extraction_prompt"]
        self.assertIn("A customer question during identity verification is not a refusal", prompt)
        self.assertIn("explicit refusal", prompt)


if __name__ == "__main__":
    unittest.main()
