"""Unit checks for the phase-1 rules (generic, written from the contract, not from the holdout wording).

    python3 tests/test_reducer_rules.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import POL

NOW = "2026-10-14T11:00"
CV = dict(customer_id="c_r", first_name="Ann", last_name="Lee", title="Ms", now=NOW)
ACC = [dict(product_id="p1", type="personal_loan", past_due=540.0, days_late=5, instalment_amount=180.0)]
n = [0]


def ev(st, body):
    n[0] += 1
    tok = "k" + "abcdefghjk"[n[0] % 10] * 5
    st["tok"] = tok
    e = R.parse_event("n=" + tok + ";src=user;" + body, st, R.CONTRACT_TOPICS)
    return e


def say(pol, st, body):
    e = ev(st, body)
    st2, act = R.step(pol, st, e, None, NOW, CV)
    st2["last_tok"] = st["tok"]
    return st2, act


def tool(pol, st, data, ok=True):
    p = st["pending"]
    te = dict(node=p["node"], success=p["snap_success"] + (1 if ok else 0), failure=p["snap_failure"] + (0 if ok else 1),
              status_code=200 if ok else 500, ok="true" if ok else None, data=data)
    return R.step(pol, st, None, te, NOW, CV)


def to_readback(pol):
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
    st, a = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
    st, a = tool(pol, st, dict(products=ACC))
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    assert st["q"] == "readback", st["q"]
    return st


def check(c, m):
    if not c:
        raise AssertionError(m)


if __name__ == "__main__":
    for name, pol in POL.items():
        v = R.V(pol)
        # 1. an event that does not answer the name question: counted re-ask, never a bare safe_repeat; cap -> unclear
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
        check(a["type"] == "say_exact" and "Lee" in a["text"] and st["counters"]["confirm_name"] == 2 and st["who"] == "unknown",
              f"{name}: identity answer under confirm_name must re-ask the name, counted: {a} {st['counters']}")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == v["unclear"], f"{name}: cap -> unclear close: {a}")
        # 2. purpose in the opening is a counted re-ask
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=purpose")
        check(st["counters"]["confirm_name"] == 2 and st["q"] == "confirm_name", f"{name}: purpose in opening counted")
        # 3. accept == yes under every open q (support_offer -> transfer)
        st = to_readback(pol)
        st, a = say(pol, st, "kind=accept;also=none;st=complete;prod=")
        check(a["type"] == "call_tool" and a["tool"] == "create_promise", f"{name}: accept at read-back confirms: {a}")
        # 4. first dispute at read-back -> what to change; a second one closes as dispute
        st = to_readback(pol)
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=dispute")
        check(st["q"] == "what_to_change" and a["type"] == "say_exact", f"{name}: first dispute at read-back asks what to change: {a}")
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=dispute")
        check(a["type"] == "close" or a["type"] == "call_tool", f"{name}: second dispute closes (or notes first): {a}")
        if a["type"] == "close":
            check((a["outcome"], a["reason"]) == v["dispute"], f"{name}: dispute close values from policy: {a}")
        # 5. other/none under help_first = yes (free talk, no transfer)
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=human")
        check(st["q"] == "help_first", f"{name}: human asks help-first")
        st, a = say(pol, st, "kind=other;also=none;st=none;prod=")
        check(a["type"] == "speak_free", f"{name}: other under help_first continues: {a}")
        # 6. a real dispute in negotiation still closes as dispute
        st = to_readback(pol)
        st["q"], st["phase"] = "pay_today", "negotiation"
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=dispute")
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == v["dispute"], f"{name}: dispute closes outside read-back: {a}")
        print(name, "rules ok; vocab log:", v["log"])
