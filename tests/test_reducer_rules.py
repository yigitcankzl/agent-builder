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


def offer_chatter_live():
    """Brief A PUB-06 live (talkative, call aebcf2a9): the floor offer, then a partial chat, then kind=other.
    Neither turn is free talk, and neither restates 637.50 or 'The rest stays overdue.'"""
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
    check("637.50" in a["text"] and "overdue" in a["text"], f"the floor offer is said once: {a}")
    check(st["q"] == "offer", f"the offer stays open: {st['q']}")
    for i, body in enumerate(("kind=other;also=none;st=partial;prod=", "kind=other;also=none;st=none;prod=")):
        st["tok"] = "kc" + "abcdefghjk"[i] * 4
        st, a = R.step(pol, st, R.parse_event("n=" + st["tok"] + ";src=user;" + body, st, TOPICS), None, c["now"], cv)
        st["last_tok"] = st["tok"]
        said = a.get("text") or a.get("hint") or ""
        check(a["type"] == "say_exact", f"chatter must not go to free talk: {a}")
        check("637.50" not in said and "overdue" not in said.lower() and "Could you pay" not in said,
              f"the offer was stated again after {body}: {said}")
        check(said == R.D_OFFER_NUDGE, f"neutral re-ask: {said}")
        check(st["q"] == "offer", f"the offer stays the open question: {st['q']}")
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


def answer_and_event():
    """PUB-04 live (f65d8706): a date and 'are you a robot?' in one message, in both orders. The robot line is said
    first, the date is processed exactly once (same state as the date alone: attempts, counters, offer)."""
    for name, pol in POL.items():
        robot = (R.event_row(pol, "robot") or {}).get("say") or ""
        check(robot, f"{name}: policy has a robot line")
        for date_body in ("kind=date;%s;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no",
                          "kind=date;%s;st=complete;prod=;rel=;d=6;m=11;wd=;wk=none;vague=no",     # after the deadline
                          "kind=date;%s;st=complete;prod=;rel=;d=17;m=10;wd=;wk=none;vague=no"):   # a Saturday
            st0, _ = to_statement(pol)
            st0, _ = say(pol, st0, "kind=no;also=none;st=complete;prod=")     # an open attempt
            ref_st, ref = say(pol, R.json.loads(R.json.dumps(st0)), date_body % "also=none")
            for body in (date_body % "also=robot", date_body % "also=topic" + ";t=robot",   # the live shape (f65d8706)
                         "kind=topic;also=date;st=complete;prod=;t=robot;" + (date_body % "x").split(";st=complete;prod=;")[1]):
                st, a = say(pol, R.json.loads(R.json.dumps(st0)), body)
                check(a["type"] == ref["type"] == "say_exact" and a["text"] == (robot + " " + ref["text"]),
                      f"{name} {body}: {a} vs {ref}")
                for k in ("products", "counters", "offer", "q", "readback"):
                    check(st[k] == ref_st[k], f"{name} {body}: {k} differs: {st[k]} vs {ref_st[k]}")
        # an identity answer plus the robot question: the line waits for the next spoken line
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=robot;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
        check(a["type"] == "call_tool", f"{name}: identity still verified: {a}")
        st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
        check(a["text"].startswith(robot), f"{name}: robot answer after the tool: {a}")
    return True


def pub02_live():
    """PUB-02 live (07083f88): 'No, this is her husband. What is this call...' labelled t=purpose;also=who;who=other;
    party=relative twice. The speaker ranks first in the opening: the callback question, no close, nothing disclosed.
    Also: an identity answer labelled as a topic in the security questions is still the answer."""
    for name, pol in POL.items():
        cv = dict(customer_id="c_p2", first_name="Ana", last_name="Costa", title="Ms", now=NOW)
        st = R.init_state(pol, cv)
        st["tok"] = "kstart"
        e = R.parse_event("n=kstart;src=user;kind=topic;also=who;st=complete;prod=;t=purpose;who=other;party=relative", st, TOPICS)
        st, a = R.step(pol, st, e, None, NOW, cv)
        check(a["type"] == "say_exact" and st["phase"] == "third_party" and "when" in a["text"].lower(), f"{name} PUB-02: {a}")
        for w in ("debt", "payment", "overdue", "collections"):
            check(w not in a["text"].lower(), f"{name} PUB-02 disclosed '{w}': {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=topic;also=identity;st=complete;prod=;t=purpose;field=date_of_birth;ans=1990-01-01")
        check(a["type"] == "call_tool" and a["tool"] == "verify_identity", f"{name}: identity answer under a topic label: {a}")
    return True


def pub03_live():
    """PUB-03 live (48a9827a): DOB 1991-07-12 (wrong), 1992-08-21 (wrong), then 'It is the twenty-first of July' (cut
    off) labelled ans=1992-07-21: the year was taken from the previous answer and matched the bank's real DOB. With the
    y= label a year not said in these words is never sent; the customer goes on and the said year is checked:
    1990-07-21 -> the third wrong answer -> not_verified/failed. Identity answers never inherit parts of earlier turns."""
    for name, pol in POL.items():
        v = R.V(pol)
        cv = dict(customer_id="c_p3", first_name="Owen", last_name="Park", title="Mr", now=NOW)
        st = R.init_state(pol, cv)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        sent = []
        for left, body in ((2, "ans=1991-07-12;y=1991"), (1, "ans=1992-08-21;y=1992")):
            st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;" + body)
            sent.append(a["args"]["answer"])
            st, a = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=left))
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1992-07-21;y=")
        check(a["type"] == "say_exact" and a["text"] == R.D_ASK_YEAR and st["identity"]["wrong"] == 2,
              f"{name}: a year not said must not be sent (the year is asked): {a}")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=1990")
        check(a["type"] == "call_tool" and a["args"]["answer"] == "1990-07-21", f"{name}: the said year completes 21 July: {a}")
        st, a = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=0))
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["id_failed"]), f"{name}: third wrong -> failed: {a}")
        # a y= that disagrees with ans is not sent either; an event without y= (older prompt) keeps the old behaviour
        st = R.init_state(pol, cv)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1992-07-21;y=1990")
        check(a["type"] == "call_tool" and a["args"]["answer"] == "1990-07-21", f"{name}: only the year said is used: {a}")
        st, a = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=2))
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1992-07-21")
        check(a["type"] == "call_tool", f"{name}: no y= key: unchanged: {a}")
    return True


def pub06_rep3():
    """PUB-06 live (90c8e096, intA3 rep 3): after the floor offer, 'I can't do that, what is the minimum payment' came as
    reject;why=too_much; attempt 1 (the floor again, plan) was spoken as 'Could you make that payment ... The rest stays
    overdue.' and the judge counted a second floor offer. Now: only the new day, after 'That was the lowest amount I can
    offer.'; no amount, no overdue clause, no 'that payment'; the read-back names 637.50."""
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
    check("637.50" in a["text"] and "overdue" in a["text"], f"the floor offer: {a}")
    for body, pre in (("kind=reject;also=none;st=complete;prod=;why=too_much", "That was the lowest amount I can offer. "),
                      ("kind=no;also=none;st=complete;prod=", "")):
        x = R.json.loads(R.json.dumps(st))
        x, a = say(pol, x, body)
        check(a["text"] == pre + "Could you pay on Friday 16 October instead?", f"{body}: {a}")
        for w in ("637", "overdue", "that payment"):
            check(w not in a["text"], f"{body}: '{w}' restated: {a}")
        x, a = say(pol, x, "kind=date;also=accept;st=complete;prod=1;rel=;d=;m=;wd=fri;wk=this;vague=no")
        check(x["q"] == "readback" and "637.50" in a["text"] and "16 October" in a["text"], f"read-back: {a}")
    return True


def clean1_pub07():
    """Rehearsal clean-1 (Northline, rh-clean-1, call c1297bc6). 'I cannot pay that today.' was extracted as
    why=too_much (the prompt now says flat); with flat, attempt 1 is the full 540 on the deadline, Thursday 22 October.
    With the mis-extraction replayed: the brief's 'too much' floor offer goes on the deadline (rule 15), and an attempt
    equal to the offer just refused (the floor on the same day) is used up, never proposed again."""
    import json
    pol = json.load(open(os.path.join(ROOT, "tests/generated/rehearsal/rh-clean-1.reducer_policy.json")))
    cv = dict(customer_id="c_c107", first_name="Samuel", last_name="Ortiz", title="Mr", now=NOW)
    acc = [dict(product_id="p1", type="personal_loan", past_due=540.0, days_late=5, instalment_amount=180.0)]

    def statement():
        st = R.init_state(pol, cv)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1975-12-05;y=1975")
        st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=7093")
        st, a = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
        st, a = tool(pol, st, dict(products=acc))
        check("full balance today" in a["text"], f"clean-1 first ask: {a}")
        return st
    st = statement()
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=flat")
    check("540.00" in a["text"] and "22 October" in a["text"] and "overdue" not in a["text"], f"flat -> attempt 1 full on the deadline: {a}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(st["q"] == "readback" and "540.00" in a["text"] and "22 October" in a["text"], f"read-back: {a}")
    st = statement()
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=too_much")
    check("216.00" in a["text"] and "22 October" in a["text"] and st["products"][0]["attempts"] == 0, f"too much -> floor on the deadline, no attempt: {a}")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=1;why=flat")
    check(a["type"] == "close" or "216" not in a.get("text", ""), f"the refused floor on the same day is not offered again: {a}")
    return True


def split_answers():
    """clean-1 surface PUB-06 live (e6d1cc28): 'May seventeenth.' -> d=17;m=5, then 'nineteen eighty six.' -> y=1986:
    merged and verified once. Also: a cut-off part kept, a correction replaces a piece, last4 in two digit groups,
    pieces never count as refusals and never outlive a sent answer."""
    for name, pol in POL.items():
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=;d=17;m=5")
        check(a["text"] == R.D_ASK_YEAR and st["identity"]["refusals"] == 0, f"{name}: the year asked: {a}")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=1986")
        check(a["type"] == "call_tool" and a["args"]["answer"] == "1986-05-17", f"{name}: merged: {a}")
        st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
        st, a = say(pol, st, "kind=identity;also=none;st=partial;prod=;field=phone_last4;ans=44")
        check(a["text"] == R.sentence(pol, "continue_line", R.D_CONTINUE), f"{name}: cut-off digits: {a}")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=01")
        check(a["type"] == "call_tool" and a["args"]["answer"] == "4401", f"{name}: last4 in two groups: {a}")
        # a correction replaces the day; the pieces go once an answer is sent
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=;d=17;m=5")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=;d=18;m=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=1986")
        check(a["args"]["answer"] == "1986-05-18", f"{name}: correction: {a}")
        st, a = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=2))
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=;d=17;m=5")
        check(a["text"] == R.D_ASK_YEAR, f"{name}: no year inherited after a sent answer: {a}")
    return True


def identity_chatter():
    """clean-1 surface PUB-07 live (d34d93ed): four kind=other turns after the phone question re-said one line to the
    loop cap and closed not_verified/declined. Chatter is never a refusal: the question is worded two ways in turn,
    the answer still goes through, a hard cap closes on the unclear slot; two explicit refusals still decline."""
    for name, pol in POL.items():
        v = R.V(pol)
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01;y=1990")
        st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
        texts = []
        for _ in range(4):
            st, a = say(pol, st, "kind=other;also=none;st=none;prod=")
            texts.append(a["text"])
        check(st["phase"] == "identity" and st["identity"]["refusals"] == 0 and all("last four" in t for t in texts)
              and texts[0] != texts[1], f"{name}: chatter re-asks, two wordings: {texts}")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
        check(a["type"] == "call_tool" and a["args"]["answer"] == "1234", f"{name}: the answer after chatter: {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        for _ in range(R.ID_OTHER_CAP + 1):
            st, a = say(pol, st, "kind=other;also=none;st=none;prod=")
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(R.id_unfinished(pol)), f"{name}: hard cap -> not verified (unfinished): {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        for _ in range(2):
            st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=decline")
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["declined"]), f"{name}: two refusals -> declined: {a}")
    return True


def opening_self_topics():
    """nightmare-1 PUB-09 live (55e7838b): 'Yes, this is Victor Ionescu. I want to make a complaint.' came as t=dispute
    with the who lost; the name was re-asked to the cap. An account topic in the opening implies the customer: the
    security questions follow, nothing is disclosed. A who=self kept in the payload with a callback books it (PUB-07)."""
    for name, pol in POL.items():
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=dispute")
        check(st["phase"] == "identity" and st["q"].startswith("id_") and "540" not in a["text"], f"{name}: dispute in the opening -> identity: {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=robot")
        check(st["phase"] == "opening", f"{name}: a question topic does not imply the customer: {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=15:00;who=self;party=")
        check(a["type"] == "call_tool" and a["tool"] == "schedule_callback", f"{name}: callback with who=self: {a}")
    return True


def ev_bank_shapes():
    """Fork 5's real-extractor bank (fallback c1123cd): date+amount always comes as kind=date;also=amount;amt=n (same
    result as date_amount); 'no' to the pay-today ask and to an offer is a flat refusal; a day with a time in the
    opening is a callback; t=paid with a quoted amt is not a proposal."""
    for name, pol in POL.items():
        st0 = to_readback(pol) if False else None
        st0 = R.init_state(pol, CV)
        for b in ("kind=who;also=none;st=complete;prod=;who=self;party=",):
            st0, a = say(pol, st0, b)
        st0, a = say(pol, st0, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
        st0, a = tool(pol, st0, dict(verified=True, all_verified=False, wrong_answers_left=3))
        st0, a = say(pol, st0, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
        st0, a = tool(pol, st0, dict(verified=True, all_verified=True, wrong_answers_left=3))
        st0, a = tool(pol, st0, dict(products=ACC))
        cp = lambda: R.json.loads(R.json.dumps(st0))
        x1, a1 = say(pol, cp(), "kind=date_amount;also=none;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no;amt=300")
        x2, a2 = say(pol, cp(), "kind=date;also=amount;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no;amt=300")
        check(a1 == a2 and x1["products"] == x2["products"] and x1["q"] == x2["q"] == "readback", f"{name}: date;also=amount == date_amount: {a1} / {a2}")
        x, a = say(pol, cp(), "kind=no;also=none;st=complete;prod=")
        check(x["products"][0]["attempts"] == 1 and x["q"] == "offer", f"{name}: no to pay today -> attempt 1: {a}")
        x, a = say(pol, x, "kind=no;also=none;st=complete;prod=")
        check(x["products"][0]["attempts"] >= 1 and (x["phase"] == "closed" or x["products"][0]["status"] in ("refused", "proposed")), f"{name}: no to an offer is a flat refusal: {a}")
        x, a = say(pol, cp(), "kind=topic;also=amount;st=complete;prod=;t=paid;amt=420")
        check(a["type"] in ("close", "call_tool") and (x.get("offer") or {}).get("amount") != 420.0, f"{name}: paid with a quoted amount: {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=date;also=none;st=complete;prod=;rel=today;d=;m=;wd=;wk=none;vague=no;tm=16:30")
        check(a["type"] == "call_tool" and a["tool"] == "schedule_callback" and a["args"]["time"] == "16:30", f"{name}: a time in the opening is a callback: {a}")
    return True


def close_rejected():
    """Live nightmare-1 PUB-09: the mock rejected close_call ('this outcome needs one of these reasons: ...') and the
    ledger was left empty. A rejected close is retried once with an allowed reason (contract-closest by family), then
    the call ends; an accepted close ends at once; never a loop. Through the hub string."""
    pol = POL["A"]
    st = to_readback(pol)
    st["q"], st["phase"] = "pay_today", "negotiation"
    st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=stop")
    st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=stop")
    while a["type"] == "call_tool":
        st, a = tool(pol, st, dict(ok=True))
    check(a["type"] == "close", f"a close to reject: {a}")
    code = compile(R.hub_source(pol), "hub", "exec")
    base = dict(CV, st=R._dump(dict(st, _close_snap=[0, 0])))
    v = dict(base, t_close_call_success_count=1, t_close_call_failure_count=0,
             close_call_data=R.json.dumps(dict(ok=False, error="this outcome needs one of these reasons: dispute, hardship, service_error")))
    exec(code, dict(vars=v))
    check(v["route"] == "close_retry" and v["close_outcome"] == a["outcome"] and v["close_reason"] in ("dispute", "hardship", "service_error"),
          f"one retry with an allowed reason: {v.get('route')} {v.get('close_outcome')} {v.get('close_reason')}")
    v2 = dict(v, t_close_call_success_count=2)
    exec(code, dict(vars=v2))
    check(v2["route"] == "end", f"rejected again -> end, no loop: {v2.get('route')}")
    v3 = dict(base, t_close_call_success_count=1, t_close_call_failure_count=0, close_call_data=R.json.dumps(dict(ok=True)))
    exec(code, dict(vars=v3))
    check(v3["route"] == "end", f"accepted -> end: {v3.get('route')}")
    v4 = dict(base, t_close_call_success_count=0, t_close_call_failure_count=1, close_call_data="")
    exec(code, dict(vars=v4))
    check(v4["route"] == "close_retry" and v4["close_outcome"] == a["outcome"], f"an HTTP failure: one retry: {v4.get('route')}")
    return True


def hedged_denial():
    """Fork 5 retest: 'I don't think so' to the name question came as wrong_number. The prompt now reserves
    party=wrong_number for a clear statement; a hedged denial is who=unclear: the name is re-asked once, worded
    differently, and the call is not closed."""
    for name, pol in POL.items():
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=unclear;party=")
        check(a["type"] == "say_exact" and a["text"].startswith(R.D_JUST_CHECK) and st["phase"] == "opening", f"{name}: hedged -> re-ask: {a}")
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=other;party=wrong_number")
        check(a["type"] == "close", f"{name}: a clear wrong number closes: {a}")
    return True


def offer_echo_accepts():
    """biz-1 live PUB-07 (a6c54fef): offered 540 on Tuesday 20 October, 'Yes, I can pay the full 540' came as
    kind=amount;amt=540 and the offer was re-proposed. The open offer's own amount, date, or date and amount is an
    acceptance -> read-back. A different amount is still a proposal."""
    for name, pol in POL.items():
        st0 = to_readback(pol)
        st0["q"], st0["phase"] = "pay_today", "negotiation"
        st0["products"][0]["status"], st0["products"][0]["offer"] = "open", None
        st0, a = say(pol, st0, "kind=no;also=none;st=complete;prod=")
        o = st0["offer"]
        check(st0["q"] == "offer" and o, f"{name}: an open offer: {a}")
        y, m, d = o["date"].split("-")
        for body in ("kind=amount;also=none;st=complete;prod=;amt=%s" % o["amount"],
                     "kind=date;also=accept;st=complete;prod=;rel=;d=%d;m=%d;wd=;wk=none;vague=no" % (int(d), int(m)),
                     "kind=date;also=amount;st=complete;prod=;rel=;d=%d;m=%d;wd=;wk=none;vague=no;amt=%s" % (int(d), int(m), o["amount"])):
            x, a = say(pol, R.json.loads(R.json.dumps(st0)), body)
            check(x["q"] == "readback" and "Do you confirm" in a["text"], f"{name}: {body} accepts: {a}")
        x, a = say(pol, R.json.loads(R.json.dumps(st0)), "kind=amount;also=none;st=complete;prod=;amt=%s" % (float(o["amount"]) - 10))
        check(x["q"] != "readback", f"{name}: a different amount is a proposal: {a}")
    return True


def multi_date_rules():
    """raw-2 live: (surface PUB-11 6d842b96) one summed amt (935) for three products went to every product -> each
    product keeps its own amount, a product refused on our offers revives on the customer's all-products date, names
    are distinct; (PUB-11) a holiday named for all products is said before the read-back. A write answered 200 with
    ok:false is a failure, never 'recorded'."""
    import json
    pol = json.load(open(os.path.join(ROOT, "tests/generated/rehearsal/raw-2.reducer_policy.json")))
    cv = dict(customer_id="c_r11", first_name="Sofia", last_name="Almeida", title="Ms", now=NOW)
    acc = [dict(product_id="p1", type="credit_card", past_due=220.0, days_late=9, minimum_payment=66.0),
           dict(product_id="p2", type="personal_loan", past_due=640.0, days_late=9, instalment_amount=213.0),
           dict(product_id="p3", type="car_loan", past_due=75.0, days_late=3, instalment_amount=25.0)]
    st = R.init_state(pol, cv)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1987-06-03;y=1987")
    st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=2288")
    st, a = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
    st, a = tool(pol, st, dict(products=acc))
    names = [pd["name"] for pd in st["_pd"]]
    check(len(set(names)) == 3, f"distinct product names: {names}")
    s0 = R.json.loads(R.json.dumps(st))
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=all;why=flat")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=flat;rel=;d=;m=;wd=wed;wk=none;vague=no")
    st, a = say(pol, st, "kind=date;also=amount;st=complete;prod=all;rel=;d=20;m=10;wd=tue;wk=none;vague=no;amt=935;y=2026")
    check(st["q"] == "readback" and all(x in a["text"] for x in ("220.00", "640.00", "75.00")) and "935" not in a["text"], f"own amounts: {a}")
    st, a = say(pol, s0, "kind=date;also=reject;st=complete;prod=all;rel=;d=19;m=10;wd=mon;wk=none;vague=no")
    check(st["q"] == "readback" and "not a business day" in a["text"] and "20 October" in a["text"], f"the holiday said before the read-back: {a}")
    # a write answered 200 with ok:false is a failure: retried, never 'recorded'
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(a["type"] == "call_tool" and a["tool"] == "create_promise", f"the first write: {a}")
    p = st["pending"]
    st, a = R.step(pol, st, None, dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"], status_code=200,
                                       ok="false", data=dict(ok=False, error="rejected")), NOW, cv)
    check(a["type"] == "call_tool" and a["tool"] == "create_promise" and "recorded" not in json.dumps(a), f"ok:false -> retry: {a}")
    return True


def date_reject_cues():
    """raw-3-single live (3e3e65e0): 'No, I cannot pay that on the twenty-second' (kind=date;also=reject;d=22, the day we
    offered) was read back as a promise on the 22nd; at what_to_change 'Tuesday works for all three' (prod=all) was
    ignored. A reject-cued date equal to the offer (or a refused day) is a refusal; a prod=all day at the read-back
    moves every product (refused ones revived). 'Not Friday, Tuesday works' still proposes Tuesday."""
    import json
    pol = json.load(open(os.path.join(ROOT, "tests/generated/rehearsal/raw-2.reducer_policy.json")))
    cv = dict(customer_id="c_r3", first_name="Sofia", last_name="Almeida", title="Ms", now=NOW)
    acc = [dict(product_id="p1", type="credit_card", past_due=220.0, days_late=9, minimum_payment=66.0),
           dict(product_id="p2", type="personal_loan", past_due=640.0, days_late=9, instalment_amount=213.0),
           dict(product_id="p3", type="car_loan", past_due=75.0, days_late=3, instalment_amount=25.0)]
    st = R.init_state(pol, cv)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1987-06-03;y=1987")
    st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=2288")
    st, a = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
    st, a = tool(pol, st, dict(products=acc))
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=all;why=flat")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=flat")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=flat")
    o = st["offer"]
    check(o and st["cur"] == 2, f"the car loan offer: {a}")
    y, m, d = o["date"].split("-")
    s_car = R.json.loads(R.json.dumps(st))
    x, a = say(pol, R.json.loads(R.json.dumps(st)), "kind=date;also=reject;st=complete;prod=3;rel=;d=%d;m=%d;wd=;wk=none;vague=no" % (int(d), int(m)))
    check(x["q"] != "readback" and x["products"][2]["status"] != "agreed", f"a refused offered day is no promise: {a}")
    # 'not Friday, Tuesday works': a different day with a reject cue proposes it
    x, a = say(pol, R.json.loads(R.json.dumps(s_car)), "kind=date;also=reject;st=complete;prod=3;rel=;d=20;m=10;wd=tue;wk=none;vague=no")
    check(x["q"] == "readback" and "20 October" in a["text"], f"another day proposes: {a}")
    # at what_to_change, a prod=all day moves every product, refused ones revived
    x, a = say(pol, x, "kind=no;also=none;st=complete;prod=")
    check(x["q"] == "what_to_change", f"what to change: {a}")
    x, a = say(pol, x, "kind=date;also=none;st=complete;prod=all;rel=;d=;m=;wd=tue;wk=none;vague=no")
    check(x["q"] == "readback" and all(v_ in a["text"] for v_ in ("220.00", "640.00", "75.00")), f"all three moved: {a}")
    return True


if __name__ == "__main__":
    print("reject-cued dates and the all-products change (raw-3 live):", date_reject_cues())
    print("multi-product dates: own amounts, revive, holiday said, ok:false fails (raw-2 live):", multi_date_rules())
    print("the open offer's own amount/date accepts (biz-1 PUB-07):", offer_echo_accepts())
    print("hedged denial re-asks the name:", hedged_denial())
    print("close_call rejected -> one retry:", close_rejected())
    print("ev bank shapes (date+amount, no, call time, quoted amount):", ev_bank_shapes())
    print("opening: account topics imply the customer (nightmare PUB-09 live):", opening_self_topics())
    print("identity chatter is not a refusal (clean-1 surface PUB-07):", identity_chatter())
    print("split identity answers (clean-1 surface PUB-06):", split_answers())
    print("rehearsal clean-1 PUB-07:", clean1_pub07())
    print("PUB-06 rep 3: no second floor offer:", pub06_rep3())
    print("PUB-03 live: no inherited year:", pub03_live())
    print("PUB-02 live: speaker first in the opening:", pub02_live())
    print("answer topic + event, both orders (PUB-04):", answer_and_event())
    print("PUB-06 minimum-this-Friday + malformed events:", pub06_and_malformed())
    for name, pol in POL.items():
        print("live fixes (PUB-05 precedence, stale, terms once, robot+date):", name, live_fixes(pol, name))
    print("blocked identity (mut-04):", blocked_identity())
    print("floor once (PUB-06):", floor_once())
    print("offer chatter does not restate the floor (PUB-06 live):", offer_chatter_live())
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
        while a["type"] == "call_tool" and a["tool"] == "add_note":        # notes enabled (A+B): the note, then the close
            st, a = tool(pol, st, dict(ok=True))
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == v["dispute"], f"{name}: dispute closes outside read-back: {a}")
        print(name, "rules ok; vocab log:", v["log"])
