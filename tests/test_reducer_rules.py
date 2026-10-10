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


def to_statement(pol, acc=ACC):
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
    st, a = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
    st, a = tool(pol, st, dict(products=acc))
    check(st["q"] == "pay_today", f"statement: {a}")
    return st, a


def live_fixes(pol, name):
    """fullA2 (PUB-05 967125c1, PUB-04 f3d4c3bc): topic precedence through also=, the open question re-asked without
    the statement, the no-other-terms line once, an answer topic that carries a date still records the date."""
    v = R.V(pol)
    st0, intro = to_statement(pol)
    # PUB-05: 'I lost my job, can I get a discount?' labelled t=terms;also=hardship -> hardship (support offer)
    for body in ("kind=topic;also=hardship;st=complete;prod=;t=terms", "kind=reject;also=hardship;st=complete;prod=;why=flat",
                 "kind=topic;also=terms;st=complete;prod=;t=hardship"):
        st, a = say(pol, R.json.loads(R.json.dumps(st0)), body)
        check(st["q"] == "support_offer", f"{name}: hardship must win over terms/reject ({body}): {a}")
    # stale / unparseable turn: the open question, never the debt intro again
    st, a = R.step(pol, R.json.loads(R.json.dumps(st0)), None, None, NOW, CV)
    st2, a2 = R.step(pol, st, None, None, NOW, CV)
    for x in (a, a2):
        check(x["type"] == "say_exact" and x["text"] != intro["text"] and "past due" not in x["text"], f"{name}: stale re-said the intro: {x}")
    # terms: the line once, never 'I am sorry' from a bridge default, never prefixed again
    st, a = say(pol, R.json.loads(R.json.dumps(st0)), "kind=topic;also=none;st=complete;prod=;t=terms")
    line = a["text"]
    check(not line.startswith("I am sorry") or not R.brief_sentence(pol, "no_other_terms", "") == "", f"{name}: terms line: {line}")
    st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=terms")
    first = line.split(".")[0]
    check(first not in a["text"], f"{name}: terms line said twice: {a}")
    # robot + a date: the date is not lost
    st, a = say(pol, R.json.loads(R.json.dumps(st0)), "kind=topic;also=date;st=complete;prod=;t=robot;rel=;d=16;m=10;wd=;wk=none;vague=no")
    check(st["products"][0]["status"] in ("agreed", "proposed") or st["q"] == "readback", f"{name}: robot+date lost the date: {a}")
    return True


def pub06_and_malformed():
    """retest56 PUB-06: 'You tell me. Can I pay the minimum this Friday?' -> kind=date;also=restructure must take the
    promise path (only hardship and injection win from also=). PUB-05 967125c1: the platform regex threw away
    'n=<5 letters>;...;also=topic;...;t=hardship;also=terms'; the permissive platform pattern lets it through and
    parse_event repairs it (token within one edit, first key wins, a topic in a second also= -> also_t)."""
    from builder.engine import event_field as E
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
    st["tok"] = "kmfqzr"
    raw = "n=kmfqzr;src=user;kind=date;also=restructure;st=complete;prod=;rel=;d=;m=;wd=fri;wk=this;vague=no"
    x, a = R.step(pol, R.json.loads(R.json.dumps(st)), R.parse_event(raw, st, TOPICS), None, c["now"], cv)
    check(a["type"] == "say_exact" and x["q"] == "readback" and "637.50" in a["text"] and "16 October" in a["text"],
          f"PUB-06 'minimum this Friday' must read back 637.50 on 16 October: {a}")
    # malformed strings from the platform
    st0, _ = to_statement(POL["A"])
    tok = st0["tok"] = "kydgdq"
    st0["last_tok"] = "kzzzzz"
    bad = "n=kydgd;src=user;kind=topic;also=topic;st=complete;prod=;t=hardship;also=terms"
    check(R.re.match(E.platform_pattern(), bad), "platform pattern must let the malformed event through")
    e = R.parse_event(bad, st0, TOPICS)
    check(e and e["t"] == "hardship" and e["also_t"] == "terms" and e["n"] == tok, f"repair: {e}")
    x, a = R.step(POL["A"], st0, e, None, NOW, CV)
    check(x["q"] == "support_offer", f"the repaired PUB-05 turn offers support: {a}")
    for raw, ok in (("n=kydgdqx;src=user;kind=yes;also=none;st=complete;prod=", True),    # one inserted letter
                    ("n=kydgzq;src=user;kind=yes;also=none;st=complete;prod=", True),     # one changed letter
                    ("n=kydzzq;src=user;kind=yes;also=none;st=complete;prod=", False),    # two edits
                    ("n=kzzzzz;src=user;kind=yes;also=none;st=complete;prod=", False),    # the last token: stale
                    ("n=kydgdq;src=user;kind=date;also=none;also=amount;st=complete;prod=;wd=fri;wd=mon", True)):
        e = R.parse_event(raw, st0, TOPICS)
        check(bool(e) == ok, f"{raw}: parsed={e}")
        check(bool(R.re.match(E.platform_pattern(), raw)), f"platform pattern rejects {raw}")
    e = R.parse_event("n=kydgdq;src=user;kind=date;also=none;also=amount;st=complete;prod=;wd=fri;wd=mon", st0, TOPICS)
    check(e["also"] == "none" and e["wd"] == "fri", f"first key wins: {e}")
    return True


if __name__ == "__main__":
    print("PUB-06 minimum-this-Friday + malformed events:", pub06_and_malformed())
    for name, pol in POL.items():
        print("live fixes (PUB-05 precedence, stale, terms once, robot+date):", name, live_fixes(pol, name))
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
