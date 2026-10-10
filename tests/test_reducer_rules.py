"""Unit checks for the phase-1 rules (generic, written from the contract, not from the holdout wording).

    python3 tests/test_reducer_rules.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import POL, FIX, TOPICS

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


def floor_once():
    """Invariant 14 on PUB-06: after the floor offer (637.50), whatever the customer says, no later offer line restates
    the amount (re-asks, next attempts, date shifts, terms, free-talk hints); the read-back still names it."""
    c = [c for c in FIX["cases"] if c["id"] == "PUB-06"][0]
    pol, cv = POL[c["policy"]], c["call_variables"]
    st = R.init_state(pol, cv)
    for s in c["steps"][:7]:
        if s["source"] == "user":
            st["tok"] = s["event_fields"]["n"]
            st, a = R.step(pol, st, R.parse_event(s["event"], st, TOPICS), None, c["now"], cv)
            st["last_tok"] = st["tok"]
        else:
            st, a = R.step(pol, st, None, s["tool_event"], c["now"], cv)
    check("637.50" in a["text"], "PUB-06 step 7 offers the floor")
    replies = ["kind=other;also=none;st=none;prod=", "kind=no;also=none;st=complete;prod=",
               "kind=reject;also=none;st=complete;prod=;why=too_much", "kind=reject;also=none;st=complete;prod=;why=flat",
               "kind=amount;also=none;st=complete;prod=;amt=637.5", "kind=topic;also=none;st=complete;prod=;t=terms",
               "kind=date;also=none;st=complete;prod=;rel=;d=;m=;wd=sat;wk=this;vague=no", "kind=topic;also=none;st=complete;prod=;t=robot", ""]
    for first in replies:
        for second in replies:
            x = R.json.loads(R.json.dumps(st))
            for k, body in enumerate((first, second)):
                if x["phase"] == "closed" or x.get("pending"):
                    break
                x["tok"] = "kf" + "abcdefghjk"[k] * 4
                ev = R.parse_event("n=" + x["tok"] + ";src=user;" + body, x, TOPICS) if body else None
                x, a = R.step(pol, x, ev, None, c["now"], cv)
                if ev:
                    x["last_tok"] = x["tok"]
                said = a.get("text") if a["type"] == "say_exact" else a.get("hint") if a["type"] == "speak_free" else ""
                if x["q"] != "readback":
                    check("637.50" not in (said or ""), f"floor restated after {first!r} / {body!r}: {said}")
    return True


def blocked_identity():
    """mut-04 (policy-extract f8a2aca, copied read-only): identity.blocked -> after the name is confirmed, close on the
    blocked/on_fail slot; no blocked question is ever asked, no account fact, no get_account."""
    import json
    pol = json.load(open(os.path.join(ROOT, "tests/generated/mut-04.reducer_policy.json")))
    idp = pol["identity"]
    asks = [q["ask"] for q in idp["questions"] if q.get("blocked") or q["field"] in idp["blocked"]["fields"]]
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    check(a["type"] == "close", f"blocked identity must close at once: {a}")
    check((a["outcome"], a["reason"]) == (idp["blocked"]["close"]["outcome"], idp["blocked"]["close"]["reason"]), f"blocked slot: {a}")
    check(not any(q in a.get("farewell", "") for q in asks), f"a blocked question was asked: {a}")
    return True


if __name__ == "__main__":
    print("blocked identity (mut-04):", blocked_identity())
    print("floor once (PUB-06):", floor_once())
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
