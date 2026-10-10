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
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["unclear"]), f"{name}: hard cap -> unclear: {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        for _ in range(2):
            st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=decline")
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["declined"]), f"{name}: two refusals -> declined: {a}")
    return True


if __name__ == "__main__":
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
