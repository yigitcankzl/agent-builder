"""Generalisation gaps (reducer side): hooks, identity formats, floor/acceptance, date refusal. Each check builds its
policy fields on a copy of the bridged Brief A policy (absent fields = the current behaviour, covered by the other suites).

    python3 tests/test_reducer_gen.py
"""
import copy, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import POL, TOPICS

NOW = "2026-10-14T11:00"
CV = dict(customer_id="c_g", first_name="Ann", last_name="Lee", title="Ms", now=NOW)
EARLY = [dict(product_id="p1", type="personal_loan", past_due=540.0, days_late=5, instalment_amount=180.0)]
LATE = [dict(product_id="p1", type="personal_loan", past_due=900.0, days_late=20, instalment_amount=300.0)]
n = [0]


def check(c, m):
    if not c:
        raise AssertionError(m)


def say(pol, st, body):
    n[0] += 1
    st["tok"] = "kg" + "abcdefghjk"[n[0] % 10] * 2 + "abcdefghjk"[(n[0] // 10) % 10] * 2
    e = R.parse_event("n=" + st["tok"] + ";src=user;" + body, st, TOPICS)
    st2, act = R.step(pol, st, e, None, NOW, CV)
    st2["last_tok"] = st["tok"]
    return st2, act


def tool(pol, st, data, ok=True):
    p = st["pending"]
    te = dict(node=p["node"], success=p["snap_success"] + (1 if ok else 0), failure=p["snap_failure"] + (0 if ok else 1),
              status_code=200 if ok else 500, ok="true" if ok else None, data=data)
    return R.step(pol, st, None, te, NOW, CV)


def to_statement(pol, acc):
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
    st, a = tool(pol, st, dict(verified=True, all_verified=True, wrong_answers_left=3))
    st, a = tool(pol, st, dict(products=acc))
    return st, a


def run_to_end(pol, st, a, bodies, tools_ok=True):
    """Feed bodies; answer every pending tool with success; collect every spoken text and the close."""
    out = [a]
    for b in bodies:
        if st["phase"] == "closed":
            break
        st, a = say(pol, st, b)
        out.append(a)
        while st.get("pending"):
            st, a = tool(pol, st, dict(ok=True))
            out.append(a)
    return st, out


def spoken(acts):
    return " | ".join((a.get("text") or a.get("farewell") or a.get("hint") or "") for a in acts)


# ---------------------------------------------------------------- gap 1: hooks
def hooks():
    pol = copy.deepcopy(POL["A"])
    pol["hooks"] = [
        dict(id="h_rec", point="opening", text="This call is recorded."),
        dict(id="h_int", point="after_debt", text="Interest continues to accrue while the payment is late."),
        dict(id="h_legal", point="on_refusal", condition="band=late", text="The account may be referred to legal follow-up."),
        dict(id="h_np", point="on_no_promise", text="We will write to you about the next steps."),
        dict(id="h_bye", point="before_close", text="You can also pay in the mobile app."),
        dict(id="h_ok", point="on_promise_recorded", text="Please keep your receipt."),
        dict(id="h_ask", point="before_close", expects_answer=True, text="Do you confirm that you made no promise?"),
        dict(id="h_lie", point="before_close", condition="outcome=no_promise", text="Your promise has been recorded."),
    ]
    # opening: the greet speaks it; the reducer only marks it said
    st = R.init_state(pol, CV)
    check("h_rec" in st["_hooks_said"] and any(x.startswith("h_ask") for x in st["_hook_skip"]), f"opening/skip: {st}")
    # after_debt: inside the statement, before the closing question, once
    st, a = to_statement(pol, EARLY)
    check("Interest continues" in a["text"] and a["text"].endswith("Can you make this payment today?"), f"after_debt: {a}")
    st2, a2 = say(pol, st, "kind=other;also=none;st=none;prod=")
    st2, a2 = R.step(pol, st2, None, None, NOW, CV)
    check("Interest" not in (a2.get("text") or a2.get("hint") or ""), f"after_debt said twice: {a2}")
    # promise path: on_promise_recorded after the recorded line, before_close in the farewell; no no-promise hook
    st, acts = run_to_end(pol, st, a, ["kind=yes;also=none;st=complete;prod=", "kind=yes;also=none;st=complete;prod=",
                                       "kind=yes;also=none;st=complete;prod="])
    txt = spoken(acts)
    check("Please keep your receipt." in txt and "You can also pay in the mobile app." in acts[-1]["farewell"], f"promise hooks: {txt}")
    check("We will write" not in txt and "Do you confirm that you made no promise" not in txt, f"wrong hooks on promise: {txt}")
    check(txt.count("Interest continues") == 1, f"after_debt once: {txt}")
    # late band, refusals to the end: on_refusal (band=late) once, on_no_promise + before_close in the farewell,
    # the expects_answer hook never spoken, the honesty-violating hook never spoken
    st, a = to_statement(pol, LATE)
    st, acts = run_to_end(pol, st, a, ["kind=no;also=none;st=complete;prod="] + ["kind=reject;also=none;st=complete;prod=;why=flat"] * 4)
    txt = spoken(acts)
    check(acts[-1]["type"] == "close", f"refusal path ends: {acts[-1]}")
    check(txt.count("legal follow-up") == 1, f"on_refusal once: {txt}")
    check("We will write to you" in acts[-1]["farewell"] and "mobile app" in acts[-1]["farewell"], f"no-promise close: {acts[-1]}")
    check("Do you confirm that you made no promise" not in txt and "has been recorded" not in txt, f"skipped hooks spoken: {txt}")
    check(any(x.startswith("h_lie") for x in st["_hook_skip"]), f"honesty skip logged: {st.get('_hook_skip')}")
    # early band: the band=late hook never fires
    st, a = to_statement(pol, EARLY)
    st, acts = run_to_end(pol, st, a, ["kind=no;also=none;st=complete;prod="] + ["kind=reject;also=none;st=complete;prod=;why=flat"] * 4)
    check("legal follow-up" not in spoken(acts), f"band condition ignored: {spoken(acts)}")
    # hub var
    src = R.hub_source(pol)
    v = dict(CV, ev="n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=self;party=")
    exec(compile(src, "hub", "exec"), dict(vars=v))
    check("h_ask:expects_answer" in v.get("hook_skip", ""), f"hub hook_skip: {v.get('hook_skip')}")
    return True


if __name__ == "__main__":
    print("gap 1 hooks:", hooks())
