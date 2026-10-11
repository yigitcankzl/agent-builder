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


def payload_stays_under_truncation():
    """40 talkative turns, with the live fat vars reappearing each turn (headers, sandbox error text).
    The printed code_exec result stays under ~6,000 characters."""
    pol = POL["A"]
    st = R.init_state(pol, dict(CV, customer_id="c_r"))
    vars_ = dict(st=R._dump(st, (",", ":")), route="stale", route_ok="no", ev_tok="kstart",
                 say_next="", farewell="Thank you. Goodbye.", talk_hint="", close_outcome="", close_reason="",
                 promise_recorded="no", promise_word="promise", now=NOW, customer_id="c_r",
                 first_name="Ann", last_name="Lee", title="Ms")
    worst = 0
    for i in range(40):
        vars_["t_verify_identity_response.header.Report-To"] = "H" * 300
        vars_["t_get_account_response.header.Report-To"] = "H" * 300
        vars_["t_verify_identity_response.header.Nel"] = "N" * 80
        vars_["t_get_account_response.header.Nel"] = "N" * 80
        vars_["hub_response.message"] = "M" * 630
        vars_["hub_reset_response.message"] = "M" * 630
        vars_["hub_response.error"] = "E" * 120
        tok = str(vars_.get("ev_tok") or "kstart")
        vars_["ev"] = "n=%s;src=user;kind=other;also=none;st=none;prod=" % tok
        before = R.returned_len(vars_)
        R.hub_main(vars_, pol)
        after = R.returned_len(vars_)
        worst = max(worst, after)
        check(after <= R.RETURN_BUDGET, "turn %d printed %d (in %d, budget %d)" % (i, after, before, R.RETURN_BUDGET))
        check("hub_response.message" not in vars_ and "t_get_account_response.header.Report-To" not in vars_,
              "turn %d noise still in the result" % i)
        check(vars_.get("route") != "talk_post" or after <= R.RETURN_BUDGET, "route")
    check(worst <= R.RETURN_BUDGET, "worst %d" % worst)
    print("   40-turn printed payload worst %d (budget %d)" % (worst, R.RETURN_BUDGET))
    return worst


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
        caller = R.caller_line(pol)
        check(caller, f"{name}: policy has a caller identity line")
        for raw in (
                "n=kstart;src=user;kind=topic;also=who;st=complete;prod=;t=purpose;who=other;party=relative",
                "n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=other;party=relative;t=purpose"):
            st = R.init_state(pol, cv)
            st["tok"] = "kstart"
            e = R.parse_event(raw, st, TOPICS)
            st, a = R.step(pol, st, e, None, NOW, cv)
            check(a["type"] == "say_exact" and st["phase"] == "third_party" and "when" in a["text"].lower()
                  and a["text"].startswith(caller), f"{name} PUB-02: {a}")
            for w in ("debt", "payment", "overdue", "collections"):
                check(w not in a["text"].lower(), f"{name} PUB-02 disclosed '{w}': {a}")
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=topic;also=identity;st=complete;prod=;t=purpose;field=date_of_birth;ans=1990-01-01")
        check(a["type"] == "call_tool" and a["tool"] == "verify_identity", f"{name}: identity answer under a topic label: {a}")
    return True


def cut_off_chatter():
    """PUB-10 live (e3ffe948): unfinished talkative prose is partial, so it gets an invitation to continue instead of
    interrupting with the open security question. A completed non-answer still uses the existing ID_OTHER_CAP."""
    from builder.engine.event_field import field, CONTRACT_TOPICS
    prompt = field({"topics": CONTRACT_TOPICS, "identity_fields": ["date_of_birth", "phone_last4"]})["extraction_prompt"]
    for fragment in ("I've been so busy getting ready for my cousin'", "I've been so busy with work I haven"):
        check(fragment in prompt and fragment + " -> " in prompt, f"missing partial example: {fragment}")
    for name, pol in POL.items():
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01;y=1990")
        st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
        for _ in range(2):
            st, a = say(pol, st, "kind=other;also=none;st=partial;prod=")
            check(a == {"type": "say_exact", "text": R.sentence(pol, "continue_line", R.D_CONTINUE)},
                  f"{name}: cut-off customer was interrupted: {a}")
        before = st.get("_id_other", 0)
        st, a = say(pol, st, "kind=other;also=none;st=none;prod=")
        check(st.get("_id_other") == before + 1 and "last four" in a["text"], f"{name}: existing other cap changed: {a}")
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


def gate_denial_is_callback():
    """PUB-03 live (72f115ae): while identity.gate.ask is open, a denial of authority is the gate's no
    (ask when an authorised person can be reached). no, reject, t=decline, who=other, and a negated statement
    never open a security question. A topic glued to who=self does not either."""
    import copy
    from builder.engine.event_field import field, CONTRACT_TOPICS
    pol = copy.deepcopy(POL["A"])
    pol["identity"]["gate"] = dict(ask="Are you authorised to discuss this account?", on_no="callback",
                                   callback_ask="When can an authorised person be reached?")
    prompt = field({"topics": CONTRACT_TOPICS, "identity_fields": ["date_of_birth"]})["extraction_prompt"]
    check("Sorry, I am not allowed to talk about that account." in prompt, "gate denial example")
    check("I'm actually not authorised to discuss the account details" not in prompt, "example is not the live sentence")
    check("denial of that authority" in prompt and "kind=no" in prompt, "gate denial outranks who=self")

    def at_gate():
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        check(st["q"] == "gate" and "authorised" in a["text"], f"gate asked: {a}")
        return st

    bodies = [
        "kind=no;also=none;st=complete;prod=",
        "kind=reject;also=none;st=complete;prod=;why=flat",
        "kind=topic;also=none;st=complete;prod=;t=decline;who=self;party=",
        "kind=who;also=none;st=complete;prod=;who=other;party=",
        "kind=who;also=none;st=complete;prod=;who=self;party=;ans=I am not allowed to discuss it",
    ]
    for body in bodies:
        st, a = say(pol, at_gate(), body)
        check(st["phase"] == "third_party" and st["q"] == "callback_time" and "birth" not in a["text"].lower()
              and "authorised person" in a["text"], f"{body}: {a} q={st['q']} phase={st['phase']}")
    st, a = say(pol, at_gate(), "kind=other;also=none;st=none;prod=")
    check(st["q"] == "gate" and "authorised" in a["text"], f"other still re-asks the gate: {a}")
    st, a = say(pol, at_gate(), "kind=yes;also=none;st=complete;prod=")
    check(str(st["q"]).startswith("id_"), f"yes still opens the security questions: {a}")
    st, a = say(pol, at_gate(), "kind=topic;also=none;st=complete;prod=;t=purpose;who=self;party=")
    check(not str(st["q"]).startswith("id_") and "birth" not in a["text"].lower(), f"purpose+who=self must not ask a DOB: {a}")
    return True


def named_day_on_moved_date():
    """PUB-07 live (894a5c50): the after-deadline line names the day the customer proposed and the deadline.
    A non-business day names that day too. The brief's own sentence is kept when it already names the day;
    a sentence that omits it still does. Single product and every product."""
    import json, copy
    pol = json.load(open(os.path.join(ROOT, "tests/generated/rehearsal/biz-1.reducer_policy.json")))
    cv = dict(customer_id="c_b1", first_name="Owen", last_name="Park", title="Mr", now=NOW)

    def ready(policy, nprod):
        st = R.init_state(policy, cv)
        rows = [dict(id="p%d" % (i + 1), type="personal_loan", past_due=400.0 + 20 * i, days_late=5) for i in range(nprod)]
        R.load_products(policy, st, rows, R._d(NOW))
        st["phase"], st["q"], st["who"], st["verified"] = "negotiation", "exact_day", "self", "yes"
        check(st["_pd"][0]["deadline"] == "2026-10-20", f"early deadline is Tuesday 20 October: {st['_pd'][0]['deadline']}")
        return st

    def speak(policy, nprod, body):
        st = ready(policy, nprod)
        st["tok"] = "kdate1"
        e = R.parse_event("n=kdate1;src=user;" + body, st, R.CONTRACT_TOPICS)
        return R.step(policy, st, e, None, NOW, cv)

    late = "kind=date;also=none;st=complete;prod=;rel=;d=26;m=10;wd=mon;wk=none;vague=no"
    closed = "kind=date;also=none;st=complete;prod=;rel=;d=16;m=10;wd=fri;wk=none;vague=no"
    st, a = speak(pol, 1, late)
    check("Monday 26 October is after the latest date I can record, which is Tuesday 20 October." in a["text"]
          and "Could you pay on Tuesday 20 October?" in a["text"], f"single after deadline: {a}")
    st, a = speak(pol, 1, closed)
    check("Friday 16 October is not a business day" in a["text"] and "Monday 19 October" in a["text"], f"single closed day: {a}")
    st, a = speak(pol, 2, late.replace("prod=;", "prod=all;"))
    check("Monday 26 October is after the latest date" in a["text"] and "Tuesday 20 October" in a["text"], f"multi after deadline: {a}")
    st, a = speak(pol, 2, closed.replace("prod=;", "prod=all;"))
    check("Friday 16 October is not a business day" in a["text"], f"multi closed day: {a}")
    own = copy.deepcopy(pol)
    own["date_rules"]["after_deadline"]["say"] = "You asked for <NAMED>. The latest I can record is <DEADLINE>."
    st, a = speak(own, 1, late)
    check("You asked for Monday 26 October." in a["text"] and "Tuesday 20 October" in a["text"], f"brief sentence kept: {a}")
    bare = copy.deepcopy(pol)
    bare["date_rules"]["after_deadline"]["say"] = "We stop at <DEADLINE>."
    st, a = speak(bare, 1, late)
    check("Monday 26 October" in a["text"] and "We stop at Tuesday 20 October." in a["text"], f"brief sentence without the day: {a}")
    shift = copy.deepcopy(pol)
    shift["date_rules"]["holiday"]["say"] = "That day is closed. The next business day is <DATE>."
    st, a = speak(shift, 1, closed)
    check("Friday 16 October is not a business day" in a["text"] and "That day is closed." in a["text"], f"closed-day sentence without the day: {a}")
    return True


def per_item_terms():
    """raw-2 Phase 2 PUB-12 (700e9c78): 'five hundred and ten for the card on Thursday 15 October, three hundred and
    ninety-six for the loan on Friday 16 October, not the car loan' came as prod=all with no amount and no per-product
    day, and one all-products date was read back again and again. PER_ITEM (generator flag, default off): items= and
    refused= go product by product through the single-product rules, then one read-back. Off: unchanged."""
    import json, copy
    from builder.engine.event_field import field, CONTRACT_TOPICS
    base = json.load(open(os.path.join(ROOT, "tests/generated/rehearsal/raw-2.reducer_policy.json")))
    pol = dict(copy.deepcopy(base), per_item=True)
    cv = dict(customer_id="c_r12", first_name="Marcus", last_name="Bell", title="Mr", now=NOW)
    accs = dict(acc=[dict(product_id="p1", type="credit_card", card_last4="9015", past_due=510.0, days_late=16, minimum_payment=153.0),
                     dict(product_id="p2", type="personal_loan", past_due=1320.0, days_late=16, instalment_amount=440.0),
                     dict(product_id="p3", type="car_loan", past_due=140.0, days_late=7, instalment_amount=46.0)])

    def verified(p):
        st = R.init_state(p, cv)
        st, a = say(p, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(p, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1983-10-19;y=1983")
        st, a = tool(p, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
        st, a = say(p, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=4410")
        st, a = tool(p, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
        st, a = tool(p, st, dict(products=accs["acc"]))
        return st
    live = "kind=date;also=reject;st=complete;prod=all;rel=;d=15;m=10;wd=thu;wk=none;vague=no"
    items = ";items=1:510:2026-10-15|2:396:2026-10-16;refused=3"
    st, a = say(pol, verified(pol), live + items)
    check(st["q"] == "readback" and "510.00 on Thursday 15 October" in a["text"] and "396.00 on Friday 16 October" in a["text"]
          and "140" not in a["text"] and a["text"].count("Do you confirm") == 1, f"one read-back, own amounts and days: {a}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    calls = []
    while a["type"] == "call_tool":
        calls.append((a["tool"], a.get("args")))
        st, a = tool(pol, st, dict(ok=True, promise_id="x", note_id="y"))
    prom = sorted((c[1]["product_id"], float(c[1]["amount"]), c[1]["date"]) for c in calls if c[0] == "create_promise")
    check(prom == [("p1", 510.0, "2026-10-15"), ("p2", 396.0, "2026-10-16")], f"two promises: {calls}")
    notes = [c[1] for c in calls if c[0] == "add_note"]
    check(len(notes) == 1 and notes[0]["product_id"] == "p3" and notes[0]["reason"] == "refused", f"the car loan note: {calls}")
    # an item the product cannot take: said for that product, its valid option offered, the rest agreed
    st, a = say(pol, verified(pol), live + ";items=1:510:2026-10-15|2:100:2026-10-16;refused=3")
    check(st["q"] == "offer" and "100.00" in a["text"] and "396.00" in a["text"] and st["products"][0]["status"] == "agreed", f"below the floor: {a}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(st["q"] == "readback" and "510.00" in a["text"] and "396.00" in a["text"], f"then one read-back: {a}")
    # a day past one product's deadline: that product moves to its deadline, said (the read-back marks it)
    st, a = say(pol, verified(pol), live + ";items=1:510:2026-10-15|2:396:17/10")
    check(a["text"].startswith("Saturday 17 October is after the latest date") and st["products"][1]["offer"]["date"] == "2026-10-16",
          f"the deadline said: {a}")
    # unparsable items / an amount cue with no amount: our own offers product by product, never a silent full balance
    st, a = say(pol, verified(pol), live + ";items=card:510")
    check(st["q"] == "offer" and st["cur"] == 0, f"unparsable -> our offer on the first product: {a}")
    st, a = say(pol, verified(pol), "kind=date;also=amount;st=complete;prod=all;rel=;d=15;m=10;wd=thu;wk=none;vague=no;amt=")
    check(st["q"] == "offer" and st["cur"] == 0, f"amounts said, none labelled -> our offer: {a}")
    # at the read-back, items replace the agreed terms
    st, a = say(pol, verified(pol), "kind=date;also=none;st=complete;prod=all;rel=;d=15;m=10;wd=thu;wk=none;vague=no")
    check(st["q"] == "readback" and "1320.00" in a["text"], f"one day for all: {a}")
    st, a = say(pol, st, "kind=no;also=amount;st=complete;prod=all" + items)
    check(st["q"] == "readback" and "396.00 on Friday 16 October" in a["text"] and "1320" not in a["text"], f"items at the read-back: {a}")
    # the 220/640/75 summed-amount case still keeps each product's own amount with the flag on
    acc0 = accs["acc"]
    accs["acc"] = [dict(product_id="p1", type="credit_card", past_due=220.0, days_late=9, minimum_payment=66.0),
                   dict(product_id="p2", type="personal_loan", past_due=640.0, days_late=9, instalment_amount=213.0),
                   dict(product_id="p3", type="car_loan", past_due=75.0, days_late=3, instalment_amount=25.0)]
    st, a = say(pol, verified(pol), "kind=date;also=amount;st=complete;prod=all;rel=;d=20;m=10;wd=tue;wk=none;vague=no;amt=935")
    check(st["q"] == "readback" and all(x in a["text"] for x in ("220.00", "640.00", "75.00")) and "935" not in a["text"], f"own amounts: {a}")
    accs["acc"] = acc0
    # flag off: items and refused are ignored (the same action as without them)
    s1, a1 = say(base, verified(base), live + items)
    s2, a2 = say(base, verified(base), live)
    check(a1 == a2, f"flag off unchanged: {a1} / {a2}")
    # the flag reaches the prompt and the hub only when PER_ITEM=1
    voc = {"topics": CONTRACT_TOPICS, "identity_fields": ["date_of_birth"]}
    old = os.environ.pop("PER_ITEM", None)
    try:
        check("items=" not in field(voc)["extraction_prompt"] and '"per_item"' not in R.hub_source(base), "off by default")
        os.environ["PER_ITEM"] = "1"
        pr = field(voc)["extraction_prompt"]
        check("items=" in pr and "refused=" in pr and '"per_item":true' in R.hub_source(base).replace(" ", ""), "on with PER_ITEM=1")
        check("five hundred and ten" not in pr and "car loan" not in pr, "the example is not the live sentence")
    finally:
        os.environ.pop("PER_ITEM", None)
        if old is not None:
            os.environ["PER_ITEM"] = old
    return True


def ledger_invariants_live():
    """The three live ledger failures: restore an earlier read-back, question echoes only clarify, and a selected
    product after a rejected multi-product read-back must itself be read back and confirmed before the write."""
    import copy, json
    from builder.engine.event_field import field, CONTRACT_TOPICS
    pol = POL["A"]

    # bb748cf5: Monday -> Tuesday -> "forget it, keep it as it was" restores Monday and reads it back again.
    st = to_readback(pol)
    p = st["products"][0]
    p["offer"]["date"] = "2026-10-19"
    st["readback"]["items"][0]["date"] = "2026-10-19"
    st["_last_ask"] = R.readback_line(pol, st, st["readback"]["items"], [])
    st, a = say(pol, st, "kind=date;also=none;st=complete;prod=1;rel=;d=20;m=10;wd=tue;wk=none;vague=no")
    check(st["q"] == "readback" and "Tuesday 20 October" in a["text"], f"changed read-back: {a}")
    st, a = say(pol, st, "kind=no;also=none;st=partial;prod=")
    check(a["type"] == "say_exact" and "yes or no" in a["text"].lower() and not st.get("pending"), f"partial no only clarifies: {a}")
    st, a = say(pol, st, "kind=accept;also=none;st=complete;prod=1;why=restore")
    check(st["q"] == "readback" and "Monday 19 October" in a["text"] and "Tuesday 20 October" not in a["text"],
          f"restored read-back: {a}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(a["type"] == "call_tool" and a["args"]["date"] == "2026-10-19", f"only restored terms written: {a}")

    # A yes after an uncertainty clarification is still not a yes directly to the full read-back: re-read, then ask again.
    st = to_readback(pol)
    st, a = say(pol, st, "kind=date;also=none;st=ambiguous;prod=1;rel=;d=14;m=10;wd=wed;wk=none;vague=no")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(st["q"] == "readback" and a["type"] == "say_exact" and not st.get("pending") and "Do you confirm" in a["text"],
          f"yes to a clarification must cause a full re-read: {a}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(a["type"] == "call_tool" and a["tool"] == "create_promise", f"yes directly after the re-read writes: {a}")

    st = to_readback(pol)
    st["products"][0]["offer"]["amount"] -= 1
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(st["q"] == "readback" and a["type"] == "say_exact" and not st.get("pending"),
          f"a stale read-back cannot authorise changed terms: {a}")
    st = to_readback(pol)
    st, a = say(pol, st, "kind=yes;also=amount;st=complete;prod=;amt=540")
    check(a["type"] == "say_exact" and not st.get("pending"), f"yes plus terms is a plan update, not confirmation: {a}")

    # c65734a0 / 8f7e05cb: exact values repeated as questions are uncertainty, never proposals.
    prompt = field({"topics": CONTRACT_TOPICS, "identity_fields": ["date_of_birth"]})["extraction_prompt"]
    for text in ("Thursday 15 October? This week?", "Two thousand one hundred? That much?", "Monday 19 October? That late?"):
        check(text in prompt, f"live uncertainty example missing: {text}")
    for body in ("kind=other;also=none;st=ambiguous;prod=",
                 "kind=date;also=none;st=ambiguous;prod=1;rel=;d=15;m=10;wd=thu;wk=this;vague=no"):
        before = to_statement(pol)[0]
        products, offer = copy.deepcopy(before["products"]), copy.deepcopy(before["offer"])
        after, a = say(pol, before, body)
        check(a["type"] == "say_exact" and "manage that" in a["text"].lower(), f"uncertainty asks yes/no: {a}")
        check(after["products"] == products and after["offer"] == offer and not after.get("pending"),
              f"uncertainty changed the plan: {after['products']} / {a}")

    # 8f7e05cb: after a cut-off no, accepting only product 1 causes a new one-product read-back, not three writes.
    multi = json.load(open(os.path.join(ROOT, "tests/generated/rehearsal/raw-2.reducer_policy.json")))
    acc = [dict(product_id="p1", type="credit_card", past_due=510.0, days_late=16, minimum_payment=153.0),
           dict(product_id="p2", type="personal_loan", past_due=1320.0, days_late=16, instalment_amount=440.0),
           dict(product_id="p3", type="car_loan", past_due=140.0, days_late=7, instalment_amount=46.0)]
    st = R.init_state(multi, CV)
    st["verified"], st["phase"], st["q"] = "yes", "readback", "readback"
    R.load_products(multi, st, acc, R._d(NOW))
    terms = [(510.0, "2026-10-19"), (528.0, "2026-10-19"), (140.0, "2026-10-22")]
    for p, (amount, date) in zip(st["products"], terms):
        p["status"], p["offer"] = "agreed", dict(amount=amount, date=date)
    st["readback"] = dict(items=[dict(product_id=p["id"], amount=p["offer"]["amount"], date=p["offer"]["date"])
                                     for p in st["products"]], asked=1)
    st["_readback_valid"] = True
    st["_last_ask"] = R.readback_line(multi, st, st["readback"]["items"], [])
    st, a = say(multi, st, "kind=no;also=none;st=partial;prod=")
    check(not st.get("pending"), f"cut-off no cannot write: {a}")
    st, a = say(multi, st, "kind=accept;also=none;st=complete;prod=1")
    check(st["q"] == "readback" and "510.00" in a["text"] and "528.00" not in a["text"] and "140.00" not in a["text"] and
          not st.get("pending"), f"selection needs its own read-back: {a}")
    st, a = say(multi, st, "kind=yes;also=none;st=complete;prod=")
    check(a["type"] == "call_tool" and a["tool"] == "create_promise" and a["args"]["product_id"] == "p1",
          f"only explicitly re-confirmed product writes: {a}")
    return True


def raw4_pub03_live():
    """ours 4074f8f live shapes. raw-4 PUB-03 (8e37adfd): 'Yes, that's me, and about the...' (who=self, partial) then
    'balance on my account.' (kind=other) closed not_reached: the partial yes is kept -> the security questions; with
    confirm_who max_times 1 from 'ask, in these words' one non-answer never closes. A PUB-03 (e155 0726b8ca): a whole
    third date in a cut-off turn is checked at once -> failed; (f4eb 9bfcde5c) two wrong dates, then only chatter to
    the cap -> failed, not declined. raw-4 PUB-01 (340a8e32): a listed holiday is called a holiday."""
    import json
    from builder import policy_bridge as B
    d = os.path.join(ROOT, "tests", "fixtures", "brief_reading", "raw-4-single")
    raw4, _ = B.to_reducer(json.load(open(os.path.join(d, "extracted.json"))), os.path.join(ROOT, "tools", "openapi.json"),
                           brief_text=open(os.path.join(d, "brief.md")).read())
    check(raw4["sentences"]["confirm_who"]["max_times"] == 1, "raw-4 still bridges max_times 1 (else drop this case)")
    cv = dict(customer_id="c_p3", first_name="Owen", last_name="Park", title="Mr", now=NOW)
    for name, pol in dict(POL, raw4=raw4).items():
        v = R.V(pol)
        st = R.init_state(pol, cv)
        st, a = say(pol, st, "kind=who;also=none;st=partial;prod=;who=self;party=")
        check(a["type"] == "say_exact" and st["phase"] == "opening", f"{name}: partial -> continue: {a}")
        st, a = say(pol, st, "kind=other;also=none;st=complete;prod=")
        check(st["phase"] == "identity" and a["type"] == "say_exact" and st["q"].startswith("id_"), f"{name}: partial yes kept: {a}")
        st = R.init_state(pol, cv)
        st, a = say(pol, st, "kind=other;also=none;st=complete;prod=")
        check(a["type"] == "say_exact" and st["phase"] == "opening", f"{name}: one non-answer re-asks the name: {a}")
        # e155: third date whole in a cut-off turn
        st = R.init_state(pol, cv)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        for left, body in ((2, "ans=1991-07-12;d=12;m=7;y=1991"), (1, "ans=1992-08-21;d=21;m=8;y=1992")):
            st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;" + body)
            st, a = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=left))
        st2 = json.loads(json.dumps(st))
        st, a = say(pol, st, "kind=identity;also=none;st=partial;prod=;field=date_of_birth;ans=;d=21;m=7;y=1990")
        check(a["type"] == "call_tool" and a["args"]["answer"] == "1990-07-21", f"{name}: whole partial date checked: {a}")
        st, a = tool(pol, st, dict(verified=False, all_verified=False, wrong_answers_left=0))
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["id_failed"]), f"{name}: third wrong -> failed: {a}")
        # f4eb: no third date, chatter to the cap
        st = st2
        for _ in range(R.ID_OTHER_CAP + 1):
            st, a = say(pol, st, "kind=other;also=none;st=complete;prod=")
        check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["id_failed"]), f"{name}: wrong then cap -> failed: {a}")
    pd = dict(deadline="2026-10-21")
    today = R._d("2026-10-14")
    hol = R.date_verdict(raw4, today, pd, R._d("2026-10-16"))
    line = R.fill_date(hol["say"], hol)
    check(hol["reason"] == "non_business_day" and line.startswith("Friday 16 October is a holiday.") and "19 October" in line,
          f"holiday named: {line}")
    wk = R.date_verdict(raw4, today, pd, R._d("2026-10-17"))
    check("is not a business day" in R.fill_date(wk["say"], wk), f"weekend line kept: {wk}")
    return True


if __name__ == "__main__":
    print("raw-4 PUB-03/PUB-01 and A PUB-03 live shapes (4074f8f):", raw4_pub03_live())
    print("ledger confirmation and uncertainty live shapes:", ledger_invariants_live())
    print("per-product terms in one turn (raw-2 PUB-12 live, PER_ITEM):", per_item_terms())
    print("gate denial is the callback (PUB-03 live):", gate_denial_is_callback())
    print("a moved day names the day the customer proposed (PUB-07 live):", named_day_on_moved_date())
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
    print("PUB-10 live: cut-off chatter is partial:", cut_off_chatter())
    print("answer topic + event, both orders (PUB-04):", answer_and_event())
    print("PUB-06 minimum-this-Friday + malformed events:", pub06_and_malformed())
    for name, pol in POL.items():
        print("live fixes (PUB-05 precedence, stale, terms once, robot+date):", name, live_fixes(pol, name))
    print("blocked identity (mut-04):", blocked_identity())
    print("floor once (PUB-06):", floor_once())
    print("offer chatter does not restate the floor (PUB-06 live):", offer_chatter_live())
    print("payload stays under the sandbox cut:", payload_stays_under_truncation() <= R.RETURN_BUDGET)
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
        # 3. accept at a read-back is a plan selection, never the explicit yes that authorises a write
        st = to_readback(pol)
        st, a = say(pol, st, "kind=accept;also=none;st=complete;prod=")
        check(st["q"] == "readback" and a["type"] == "say_exact" and not st.get("pending"),
              f"{name}: accept at read-back must be re-read: {a}")
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
