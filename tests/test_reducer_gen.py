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


# ---------------------------------------------------------------- gap 2: identity formats
def identity_formats():
    from builder.engine import event_field as E
    cases = [("date", "1986-5-17", "1986-05-17"), ("YYYY-MM-DD", "1986/05/17", "1986-05-17"), ("date", "17 May", ""),
             ("digits(3)", "4 6 3", "463"), ("digits(3)", "4631", ""), ("4 digits", "44 01", "4401"),
             ("four digits", "4401", "4401"), ("YYYY", "1986", "1986"), ("YYYY", "86", ""),
             ("name", "  ahmet   YILMAZ ", "Ahmet Yilmaz"), ("name", "O'Brien-smith", "O'Brien-Smith"), ("name", "Şükrü", "Şükrü"),
             ("alnum", "sc-123 456", "SC123456"), ("postcode", "n1  4ab", "N1 4AB"),
             ("uppercase with a single space before the inward code, e.g. N1 4AB", "n14ab", "N1 4AB"),
             ("exactly as the customer said it, letters and digits, no spaces stripped", "n1 4AB", "n1 4AB"),
             ("free", " the  blue house ", "the blue house"), ("", "anything", "anything")]
    for fmt, ans, exp in cases:
        got = R.norm_answer(fmt, ans)
        check(got == exp, f"norm_answer({fmt!r}, {ans!r}) = {got!r}, expected {exp!r}")
    # a name question end to end: passes through (no digit forcing), a bad digits answer is re-asked, not counted
    pol = copy.deepcopy(POL["A"])
    pol["identity"]["questions"] = [dict(field="father_name", ask="What is your father's first name?", format="name"),
                                    dict(field="tckn_last3", ask="What are the last three digits of your ID number?", format="digits(3)")]
    pol["identity"]["order"] = ["father_name", "tckn_last3"]
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    check("father" in a["text"], f"first ask: {a}")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=father_name;ans=ahmet")
    check(a["type"] == "call_tool" and a["args"]["answer"] == "Ahmet", f"name passes through: {a}")
    st, a = tool(pol, st, dict(verified=True, all_verified=False, wrong_answers_left=3))
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=tckn_last3;ans=4631")
    check(a["type"] == "say_exact" and st["identity"]["wrong"] == 0, f"4 digits for digits(3): re-ask, not counted: {a}")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=tckn_last3;ans=4 6 3")
    check(a["type"] == "call_tool" and a["args"]["answer"] == "463", f"digits(3): {a}")
    # the ev prompt follows each question's format; names never 'digits only'
    pr = E.ev_field(pol)["extraction_prompt"]
    check("father_name: the name as said, letters only" in pr and "tckn_last3: digits only, exactly 3" in pr, pr[:200])
    import re
    check(re.match(E.platform_pattern(), "n=kabcde;src=user;kind=identity;also=none;st=complete;prod=;field=father_name;ans=Şükrü O'Brien"),
          "platform pattern must accept names with letters outside ASCII and apostrophes")
    return True


# ---------------------------------------------------------------- gap 3: floor and acceptance
def floor_acceptance():
    pol = copy.deepcopy(POL["A"])
    row = lambda pd: dict(product_id="p1", type="personal_loan", past_due=pd, days_late=5, instalment_amount=180.0)
    fl = lambda spec, pd: R._floor(dict(pol, products=dict(pol["products"], floor_by_type=dict(personal_loan=spec))), row(pd))
    for spec, pd, exp in ((dict(kind="account_field", field="instalment_amount"), 540.0, 180.0),
                          (dict(kind="percent_of_past_due", percent=30, round="up"), 540.0, 162.0),
                          (dict(kind="percent", percent=30, round="up"), 333.33, 100.0),
                          (dict(kind="percent", percent=30, round="down"), 333.33, 99.99),
                          (dict(kind="percent", percent=25, round="up", to="unit"), 333.0, 84.0),
                          (dict(kind="fixed", amount=50), 300.0, 50.0),
                          (dict(kind="fixed", amount=500), 300.0, 300.0),         # never above full
                          (dict(kind="max_fixed_percent", amount=50, percent=10), 300.0, 50.0),
                          (dict(kind="max_fixed_percent", amount=50, percent=10), 900.0, 90.0),
                          (dict(kind="unknown"), 300.0, 300.0)):
        got = fl(spec, pd)
        check(abs(got - exp) < 0.005, f"floor {spec} on {pd}: {got} != {exp}")
    # mut-03 percent floor end to end: "too much" offers 30% rounded up, not the full amount
    import json
    m3 = json.load(open(os.path.join(ROOT, "tests/generated/mut-03.reducer_policy.json")))
    st, a = to_statement(m3, EARLY)
    st, a = say(m3, st, "kind=reject;also=none;st=complete;prod=;why=too_much")
    check("162.00" in a["text"], f"mut-03 floor 30% of 540 = 162.00: {a}")

    def amount_after_statement(p, amt, acc=EARLY):
        st, a = to_statement(p, acc)
        st, a = say(p, st, "kind=no;also=none;st=complete;prod=")
        return say(p, st, "kind=amount;also=none;st=complete;prod=;amt=" + str(amt))
    # default: above full is never clamped silently
    st, a = amount_after_statement(pol, 600)
    check("The amount due is 540.00." in a["text"] and st["offer"]["amount"] == 540.0, f"above full, default: {a}")
    allow = copy.deepcopy(pol); allow["amounts"] = dict(acceptance="above_full_allowed")
    st, a = amount_after_statement(allow, 600)
    check(st["offer"]["amount"] == 600.0 and "amount due" not in a["text"], f"above_full_allowed: {a}")
    full = copy.deepcopy(pol); full["amounts"] = dict(acceptance="full_only")
    st, a = amount_after_statement(full, 300)
    check("I cannot record 300.00." in a["text"] and st["offer"]["amount"] == 180.0, f"full_only: a volunteered part is refused, the floor offered once: {a}")
    st, a = to_statement(full, EARLY)
    st, a = say(full, st, "kind=reject;also=none;st=complete;prod=;why=too_much")
    check("180.00" in a["text"] and st["products"][0]["floor_offered"], f"full_only: 'too much' still offers the floor: {a}")
    mx = copy.deepcopy(pol); mx["amounts"] = dict(acceptance=dict(kind="min_x", min=100))
    st, a = amount_after_statement(mx, 120)
    check(st["offer"]["amount"] == 120.0 and "cannot" not in a["text"], f"min_x accepts 120 >= 100: {a}")
    st, a = amount_after_statement(mx, 80)
    check("I cannot record 80.00." in a["text"] and st["offer"]["amount"] == 180.0, f"min_x below: {a}")
    # date + amount: the amount goes through the same rule, the date is kept
    st, a = to_statement(pol, EARLY)
    st, a = say(pol, st, "kind=date_amount;also=none;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no;amt=100")
    check("I cannot record 100.00." in a["text"] and "16 October" in a["text"], f"date_amount below floor: {a}")
    st, a = to_statement(pol, EARLY)
    st, a = say(pol, st, "kind=date_amount;also=none;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no;amt=900")
    check("The amount due is 540.00." in a["text"], f"date_amount above full: {a}")
    return True


# ---------------------------------------------------------------- gap 4: date refusal
def date_refusal():
    def at(pol, d, m, rel=""):
        st, a = to_statement(pol, EARLY)
        st, a = say(pol, st, "kind=no;also=none;st=complete;prod=")
        return say(pol, st, f"kind=date;also=none;st=complete;prod=;rel={rel};d={d};m={m};wd=;wk=none;vague=no")
    base = {k: v for k, v in POL["A"].items() if k != "date_rules"}   # the legacy sections decide (a bridged A may carry date_rules)
    st, a = at(base, 17, 10)          # legacy default: weekend -> the next business day
    check("Monday 19 October" in a["text"] and st["offer"]["date"] == "2026-10-19", f"legacy shift: {a}")
    pol = copy.deepcopy(base)
    pol["date_rules"] = dict(weekend=dict(action="refuse", say="We do not accept weekend dates."))
    st, a = at(pol, 17, 10)
    check(a["text"] == "We do not accept weekend dates. Which other date would work?" and st["offer"] is None
          and st["q"] == "exact_day", f"weekend refuse, brief sentence: {a}")
    st, a = say(pol, st, "kind=date;also=none;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no")
    check(st["q"] == "readback" and "16 October" in a["text"], f"another date after a refusal: {a}")
    pol["date_rules"] = dict(weekend=dict(action="refuse"))
    st, a = at(pol, 17, 10)
    check(a["text"] == "Saturday 17 October is not a business day, so I cannot record it. Which other date would work?", f"weekend default: {a}")
    pol["date_rules"] = dict(holiday=dict(action="refuse"), weekend=dict(action="shift_next_business_day"))
    st, a = at(pol, 26, 10)            # Monday 26 October is a holiday in brief A
    check("cannot record" in a["text"] and st["offer"] is None, f"holiday refuse: {a}")
    st, a = at(pol, 24, 10)            # Saturday -> Monday 26 (holiday) -> Tuesday 27
    check("Tuesday 27 October" in a["text"], f"weekend shift over a holiday: {a}")
    pol["date_rules"] = dict(after_deadline=dict(action="refuse"))
    st, a = at(pol, 1, 12)
    check(a["text"].startswith("I cannot record a date after ") and "passed" not in a["text"] and st["offer"] is None, f"after deadline refuse: {a}")
    legacy = copy.deepcopy(base)
    legacy["on_after_deadline"] = dict(action="reject", say="The latest date I can record is <DEADLINE>. Could you pay on <DEADLINE>?")
    st, a = at(legacy, 1, 12)
    check("passed" not in a["text"] and "cannot record a date after" in a["text"], f"legacy reject after deadline: {a}")
    legacy = copy.deepcopy(base)
    legacy["on_non_business_day"] = dict(action="reject")
    st, a = at(legacy, 17, 10)
    check("is not a business day, so I cannot record it" in a["text"], f"legacy reject weekend: {a}")
    legacy = copy.deepcopy(base)
    legacy["earliest"] = dict(allow_today=False)
    st, a = at(legacy, "", "", rel="today")
    check(a["text"] == "I cannot record a payment for today. Which other date would work?", f"today not allowed: {a}")
    st, a = at(base, 10, 10)
    check(a["text"].startswith("That date has passed."), f"a past date: {a}")
    # never 'That date has passed' for a future date, under any action
    for rules in (dict(), dict(weekend=dict(action="refuse"), holiday=dict(action="refuse"), after_deadline=dict(action="refuse")),
                  dict(weekend=dict(action="offer_deadline"), after_deadline=dict(action="offer_deadline"))):
        pol = copy.deepcopy(base); pol["date_rules"] = rules
        for d, m in [(x, 10) for x in range(15, 32)] + [(x, 11) for x in range(1, 31)]:
            st, a = at(pol, d, m)
            check("passed" not in a.get("text", ""), f"future {d}/{m} said passed under {rules}: {a}")
    return True


# ---------------------------------------------------------------- nested response paths (policy.tool_results)
def nested_paths():
    """verify_identity / get_account results read through policy.tool_results paths when the bank nests them; the
    same call through step() and through the hub string (flattened t_<tool>_response.data.* vars)."""
    pol = copy.deepcopy(POL["A"])
    pol["tool_results"] = dict(
        verify_identity=dict(ok="data.status.ok", verified_this="data.result.verified", verified_all="data.result.all",
                             wrong_left="data.result.left", hint="data.result.hint"),
        get_account=dict(ok="data.status.ok", products="data.account.items", id="item.ids.product", type="item.kind",
                         past_due="item.balance.past_due", days_late="item.balance.days_late",
                         **{"floor.personal_loan": "item.balance.instalment"}),
        create_promise=dict(ok="data.status.ok"))
    ver = lambda v, a, left: dict(status=dict(ok=True), result=dict(verified=v, all=a, left=left))
    acct = dict(status=dict(ok=True), account=dict(items=[dict(ids=dict(product="p9"), kind="personal_loan",
                                                              balance=dict(past_due=540.0, days_late=5, instalment=180.0))]))
    # step(): the te carries the nested data and no flat ok
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    turns = [("kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01", ver(False, False, 2)),
             ("kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-02", ver(True, False, 2)),
             ("kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234", ver(True, True, 2))]
    for body, data in turns:
        st, a = say(pol, st, body)
        p = st["pending"]
        st, a = R.step(pol, st, None, dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"],
                                           status_code=200, ok=None, data=data), NOW, CV)
    check(st["identity"]["wrong"] == 1 and a["type"] == "call_tool" and a["tool"] == "get_account", f"nested verify: {a} {st['identity']}")
    p = st["pending"]
    st, a = R.step(pol, st, None, dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"],
                                       status_code=200, ok=None, data=acct), NOW, CV)
    check("540.00" in a["text"] and "5 days" in a["text"] and st["products"][0]["id"] == "p9" and st["_pd"][0]["floor"] == 180.0,
          f"nested account: {a} {st['_pd']}")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=too_much")
    check("180.00" in a["text"], f"nested floor field: {a}")
    # the hub string, with Freya's flattened response vars
    def flat(prefix, obj, out):
        if isinstance(obj, dict):
            for k, v in obj.items():
                flat(prefix + "." + k, v, out)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                flat(prefix + "." + str(i), v, out)
        else:
            out[prefix] = obj
        return out
    code = compile(R.hub_source(pol), "hub", "exec")
    v = dict(CV, ev="n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=self;party=")
    exec(code, dict(vars=v))
    counts = dict()
    for body, data in turns + [(None, acct)]:
        if body:
            v["ev"] = "n=" + v["ev_tok"] + ";src=user;" + body
            exec(code, dict(vars=v))
        node = v["route"]
        check(node.startswith("t_"), f"hub route: {node} {v.get('say_next')}")
        counts[node] = counts.get(node, 0) + 1
        v[node + "_success_count"] = counts[node]
        v[node + "_failure_count"] = 0
        v[node + "_response.status_code"] = 200
        for k in [k for k in v if k.startswith(node + "_response.data.")]:
            del v[k]
        v.update(flat(node + "_response.data", data, dict()))
        exec(code, dict(vars=v))
    check(v["route"] == "say" and "540.00" in v["say_next"] and "5 days" in v["say_next"] and not v.get("hub_error"),
          f"hub nested: {v.get('route')} {v.get('say_next')} {v.get('hub_error')}")
    return True


# ---------------------------------------------------------------- verified_value and amount_scale (tool_results)
def status_and_scale():
    """verify_identity reporting a string status (verified_value) and get_account amounts in cents (amount_scale)."""
    pol = copy.deepcopy(POL["A"])
    pol["tool_results"] = dict(pol.get("tool_results") or {})
    pol["tool_results"]["verify_identity"] = dict(verified_this="data.status", verified_all="data.overall",
                                                   wrong_left="data.left", verified_value="verified")
    pol["tool_results"]["get_account"] = dict((pol["tool_results"].get("get_account") or {}), amount_scale=0.01)
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(status="failed", overall="failed", left=2))
    check(st["identity"]["wrong"] == 1 and a["type"] == "say_exact", f"'failed' is not verified: {a}")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-02")
    st, a = tool(pol, st, dict(status="verified", overall="pending", left=2))
    check(a["type"] == "say_exact" and st["identity"]["idx"] == 1, f"'verified' moves to question 2: {a}")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
    st, a = tool(pol, st, dict(status="verified", overall="verified", left=2))
    check(a["type"] == "call_tool" and a["tool"] == "get_account", f"all verified: {a}")
    st, a = tool(pol, st, dict(products=[dict(product_id="p1", type="personal_loan", past_due=54000, days_late=5,
                                              instalment_amount=18000)]))
    check("540.00 past due" in a["text"] and st["_pd"][0]["floor"] == 180.0, f"cents to major units: {a} {st['_pd']}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check("540.00" in a["text"], f"read-back in major units: {a}")
    st, a = say(pol, st, "kind=yes;also=none;st=complete;prod=")
    check(a["type"] == "call_tool" and a["args"]["amount"] == 54000 and isinstance(a["args"]["amount"], int), f"promise in cents: {a}")
    # policy amounts are major units and are not scaled: min_x 40 accepts 50.00 on a cents account
    mx = copy.deepcopy(POL["A"]); mx["amounts"] = dict(acceptance=dict(kind="min_x", min=40))
    mx["tool_results"] = dict(mx.get("tool_results") or {})
    mx["tool_results"]["get_account"] = dict((mx["tool_results"].get("get_account") or {}), amount_scale=0.01)
    st, a = to_statement(mx, [dict(product_id="p1", type="personal_loan", past_due=54000, days_late=5, instalment_amount=18000)])
    st, a = say(mx, st, "kind=no;also=none;st=complete;prod=")
    st, a = say(mx, st, "kind=amount;also=none;st=complete;prod=;amt=50")
    check(st["offer"]["amount"] == 50.0 and "cannot" not in a["text"], f"min_x 40 (major) on a cents account: {a}")
    # absent fields: unchanged
    check(R.amount_scale(POL["A"]) == 1.0 and R.api_amount(POL["A"], 540.0) == 540.0, "absent scale")
    return True


# ---------------------------------------------------------------- mixed verified shapes, composed request fields
def mixed_verified_and_composed():
    # verified_this = a string status, verified_all = a boolean: both count
    pol = copy.deepcopy(POL["A"])
    pol["tool_results"] = dict(pol.get("tool_results") or {})
    pol["tool_results"]["verify_identity"] = dict(verified_this="data.status", verified_all="data.all_verified",
                                                   wrong_left="data.wrong_answers_left", verified_value="verified")
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(status="verified", all_verified=True, wrong_answers_left=3))
    check(a["type"] == "call_tool" and a["tool"] == "get_account", f"string verified + boolean all_verified: {a}")
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(status="failed", all_verified=False, wrong_answers_left=2))
    check(st["identity"]["wrong"] == 1, f"'failed' + false: wrong: {a}")
    # composed request field: schedule_callback.when = date + time, one var, PUB-02 flow
    pol = copy.deepcopy(POL["A"])
    pol["tool_args"] = dict(pol.get("tool_args") or {}, schedule_callback=dict(date="when", time="when"))
    pol["composed_fields"] = {"schedule_callback.when": dict(format="date-time", roles=["date", "time"])}
    cv = dict(customer_id="c_p2", first_name="Ana", last_name="Costa", title="Ms", now=NOW)
    st = R.init_state(pol, cv)
    st["tok"] = "kstart"
    e = R.parse_event("n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=other;party=relative", st, TOPICS)
    st, a = R.step(pol, st, e, None, NOW, cv)
    st["last_tok"] = "kstart"
    st["tok"] = "kcbzzz"
    e = R.parse_event("n=kcbzzz;src=user;kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=11:00", st, TOPICS)
    st, a = R.step(pol, st, e, None, NOW, cv)
    check(a["type"] == "call_tool" and a["tool"] == "schedule_callback" and a["args"].get("when") == "2026-10-15T11:00:00"
          and "date" not in a["args"] and "time" not in a["args"], f"composed when: {a}")
    v = dict(cv, ev="n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=other;party=relative")
    code = compile(R.hub_source(pol), "hub", "exec")
    exec(code, dict(vars=v))
    v["ev"] = "n=" + v["ev_tok"] + ";src=user;kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=11:00"
    exec(code, dict(vars=v))
    check(v.get("w_schedule_callback_when") == "2026-10-15T11:00:00" and "w_schedule_callback_date" not in v, f"hub vars: {v}")
    # absent: unchanged
    st = R.init_state(POL["A"], cv)
    st["tok"] = "kstart"
    st, a = R.step(POL["A"], st, R.parse_event("n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=other;party=relative", st, TOPICS), None, NOW, cv)
    st["last_tok"], st["tok"] = "kstart", "kcbyyy"
    st, a = R.step(POL["A"], st, R.parse_event("n=kcbyyy;src=user;kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=11:00", st, TOPICS), None, NOW, cv)
    check(a["args"].get("date") == "2026-10-15" and a["args"].get("time") == "11:00", f"absent composed: {a}")
    return True


# ---------------------------------------------------------------- per-answer flag only: all verified after the last question
def per_answer_only():
    pol = copy.deepcopy(POL["A"])
    pol["tool_results"] = dict(pol.get("tool_results") or {})
    pol["tool_results"]["verify_identity"] = dict(verified_this="data.answer_ok", wrong_left="data.left")
    for extra in (dict(), dict(all_verified=True)):      # an unbound all-field in the response is ignored
        st = R.init_state(pol, CV)
        st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
        st, a = tool(pol, st, dict(answer_ok=True, left=3, **extra))
        check(a["type"] == "say_exact" and st["identity"]["idx"] == 1 and st["verified"] != "yes",
              f"first right answer is not all-verified ({extra}): {a}")
        st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=1234")
        st, a = tool(pol, st, dict(answer_ok=True, left=3, **extra))
        check(a["type"] == "call_tool" and a["tool"] == "get_account" and st["verified"] == "yes", f"after the 2nd: {a}")
    # a bound all-field is still honoured
    pol["tool_results"]["verify_identity"]["verified_all"] = "data.done"
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1990-01-01")
    st, a = tool(pol, st, dict(answer_ok=True, done=True, left=3))
    check(a["type"] == "call_tool" and a["tool"] == "get_account", f"bound all-field true on question 1: {a}")
    return True


# ---------------------------------------------------------------- flat renamed item paths (binding assist, cc4542b)
def flat_item_paths():
    """get_account rows whose fields carry other names, bound by flat item paths (item.age, item.outstanding): days_late,
    past_due, the floor, type and id all come through the paths, so the band, deadline and attempt cap are right."""
    pol = copy.deepcopy(POL["A"])
    pol["tool_results"] = dict(pol.get("tool_results") or {})
    pol["tool_results"]["get_account"] = dict(ok="data.ok", products="data.products", id="item.pid", type="item.kind",
                                              past_due="item.outstanding", days_late="item.age",
                                              **{"floor.personal_loan": "item.inst"})
    row = dict(pid="p1", kind="personal_loan", outstanding=900.0, age=20, inst=300.0)   # only the renamed fields
    st, a = to_statement(pol, [row])
    pd = st["_pd"][0]
    ref = R.init_state(POL["A"], CV)
    R.load_products(POL["A"], ref, [dict(product_id="p1", type="personal_loan", past_due=900.0, days_late=20, instalment_amount=300.0)], R._d(NOW))
    want = ref["_pd"][0]
    for k in ("days_late", "band", "deadline", "past_due", "floor", "plan", "name"):
        check(pd[k] == want[k], f"flat item path: {k} {pd[k]!r} != {want[k]!r}")
    check(st["products"][0]["id"] == "p1" and "20 days late" in a["text"] and "900.00" in a["text"], f"statement: {a}")
    return True


# ---------------------------------------------------------------- rehearsal rule types (nightmare-1, biz-1)
def rehearsal_rules():
    v = R.V(POL["A"])
    # the no-promise question (hooks on_no_promise expects_answer): asked once before a verified no_promise close
    pol = copy.deepcopy(POL["A"])
    pol["hooks"] = [dict(id="np", point="on_no_promise", expects_answer=True, text="Can I note that you are not making a promise today?")]
    st, a = to_statement(pol, EARLY)
    st, a = say(pol, st, "kind=no;also=none;st=complete;prod=")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=flat")
    check(a.get("text") == "Can I note that you are not making a promise today?" and st["q"] == "confirm_np", f"np question: {a}")
    yes_st, yes_a = say(pol, R.json.loads(R.json.dumps(st)), "kind=yes;also=none;st=complete;prod=")
    check(yes_a["type"] == "close" and (yes_a["outcome"], yes_a["reason"]) == tuple(v["refused"]), f"yes closes refused: {yes_a}")
    st, a = say(pol, st, "kind=date_amount;also=none;st=complete;prod=;rel=;d=16;m=10;wd=;wk=none;vague=no;amt=540")
    check(st["q"] == "readback" and "540.00" in a["text"] and "16 October" in a["text"], f"a date instead: read-back: {a}")
    st, a = say(pol, st, "kind=reject;also=none;st=complete;prod=;why=flat")
    check(a["type"] != "say_exact" or "not making a promise" not in a["text"], f"asked once: {a}")
    # never before a service_error close or after a promise
    st, a = to_statement(pol, EARLY)
    for b in ("kind=yes;also=none;st=complete;prod=", "kind=yes;also=none;st=complete;prod="):
        st, a = say(pol, st, b)
    for _ in range(2):
        st, a = tool(pol, st, dict(), ok=False)
    check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["write_failed"]), f"service_error: no question: {a}")
    # the customer asks for a callback before identity: no verification, the callback flow
    cv = dict(CV)
    st = R.init_state(POL["A"], cv)
    st, a = say(POL["A"], st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(POL["A"], st, "kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=15:00")
    check(a["type"] == "call_tool" and a["tool"] == "schedule_callback" and a["args"]["time"] == "15:00" and st["verified"] != "yes", f"self callback: {a}")
    # a time outside the window, then no other time: no_callback
    st = R.init_state(POL["A"], cv)
    st, a = say(POL["A"], st, "kind=who;also=none;st=complete;prod=;who=other;party=relative")
    st, a = say(POL["A"], st, "kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=22:00")
    check(a["type"] == "say_exact" and st["q"] == "callback_time", f"outside the window: ask once: {a}")
    st, a = say(POL["A"], st, "kind=no;also=none;st=complete;prod=")
    check(a["type"] == "close" and (a["outcome"], a["reason"]) == tuple(v["callback_failed"]), f"no other time: {a}")
    # an extra topic closes with its own outcome/reason, before identity, nothing disclosed
    pol = copy.deepcopy(POL["A"])
    pol["extra_topics"] = [dict(id="complaint", trigger="wants to make a complaint", effect="close", outcome="no_promise", reason="complaint")]
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=complaint")
    check(a["type"] == "close" and (a["outcome"], a["reason"]) == ("no_promise", "complaint"), f"complaint: {a}")
    # full_or_floor: only the full balance or exactly the floor
    pol = copy.deepcopy(POL["A"]); pol["amounts"] = dict(acceptance="full_or_floor")
    st, a = to_statement(pol, EARLY)
    st, a = say(pol, st, "kind=no;also=none;st=complete;prod=")
    for amt, ok in ((180, True), (300, False)):
        x, a = say(pol, R.json.loads(R.json.dumps(st)), "kind=amount;also=none;st=complete;prod=;amt=%s" % amt)
        check(((x["offer"] or {}).get("amount") == float(amt)) == ok and (("cannot record" in a["text"]) != ok), f"full_or_floor {amt}: {a}")
    x, a = say(pol, R.json.loads(R.json.dumps(st)), "kind=amount;also=none;st=complete;prod=;amt=540")
    check(x["q"] == "readback" and "540.00" in a["text"], f"full_or_floor 540 (the open offer's amount) accepts: {a}")
    return True


# ---------------------------------------------------------------- identity gate (biz-1 rules 3-4)
def identity_gate():
    pol = copy.deepcopy(POL["A"])
    pol["identity"]["gate"] = dict(ask="Are you authorised to discuss this account?", on_no="callback")
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    check(a["text"] == "Are you authorised to discuss this account?" and st["q"] == "gate", f"gate first: {a}")
    st2, a2 = say(pol, R.json.loads(R.json.dumps(st)), "kind=other;also=none;st=none;prod=")
    check(a2["type"] == "say_exact" and "authorised" in a2["text"] and st2["q"] == "gate", f"gate re-asked: {a2}")
    y, a = say(pol, R.json.loads(R.json.dumps(st)), "kind=yes;also=none;st=complete;prod=")
    check(y["q"].startswith("id_") and "birth" in a["text"], f"yes -> the first security question: {a}")
    n_, a = say(pol, R.json.loads(R.json.dumps(st)), "kind=no;also=none;st=complete;prod=")
    check(n_["phase"] == "third_party" and "authorised person" in a["text"] and "540" not in a["text"], f"no -> when can an authorised person be reached: {a}")
    n_, a = say(pol, n_, "kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=12:00")
    check(a["type"] == "call_tool" and a["tool"] == "schedule_callback" and a["args"]["time"] == "12:00", f"callback booked: {a}")
    pol["identity"]["gate"]["on_no"] = dict(close=dict(outcome="not_verified", reason="declined"))
    st = R.init_state(pol, CV)
    st, a = say(pol, st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    st, a = say(pol, st, "kind=no;also=none;st=complete;prod=")
    check(a["type"] == "close" and (a["outcome"], a["reason"]) == ("not_verified", "declined"), f"on_no close: {a}")
    st = R.init_state(POL["A"], CV)        # absent: unchanged
    st, a = say(POL["A"], st, "kind=who;also=none;st=complete;prod=;who=self;party=")
    check(st["q"].startswith("id_"), f"no gate: unchanged: {a}")
    return True


# ---------------------------------------------------------------- sample2: no transfer tool, renamed hardship codes, a 0.05 step
def sample2_rules():
    import json
    # no transfer tool: restructure / human close with their own codes, nothing transferred
    pol = copy.deepcopy(POL["A"])
    pol["tool_status"] = dict(transfer_to_agent=dict(status="absent", why="not in the OAS"))
    for e in pol["events"]:
        if e["topic"] in ("restructure", "human"):
            e["outcome"], e["reason"] = "no_promise", e["topic"] if e["topic"] == "human" else "restructuring"
    R._VC.clear() if hasattr(R, "_VC") else None
    st, a = to_statement(pol, EARLY)
    st, a = say(pol, st, "kind=topic;also=none;st=complete;prod=;t=restructure")
    check(a["type"] == "close" and (a["outcome"], a["reason"]) == ("no_promise", "restructuring"), f"no transfer tool: {a}")
    # renamed hardship codes (gen-007): the accept row is the transfer outcome, the decline is found by its 'when'
    g7 = json.load(open(os.path.join(ROOT, "tests/generated/synthetic/gen-007.reducer_policy.json"))) \
        if os.path.exists(os.path.join(ROOT, "tests/generated/synthetic/gen-007.reducer_policy.json")) else None
    if g7:
        v = R.vocab(g7)
        check(v["xfer"]["hardship"][0] == "specialist_handoff" and v["hardship"][0] == "no_arrangement", f"gen-007 hardship: {v['xfer']['hardship']} {v['hardship']}")
    # a numeric rounding step
    check(R._round(416.6250, "nearest", 0.05) == 416.65 and R._round(416.6, "nearest", 0.05) == 416.6, "0.05 step")
    return True


if __name__ == "__main__":
    print("sample2 rules (no transfer tool, renamed hardship, 0.05 step):", sample2_rules())
    print("identity gate:", identity_gate())
    print("rehearsal rule types:", rehearsal_rules())
    print("flat renamed item paths:", flat_item_paths())
    print("per-answer flag only:", per_answer_only())
    print("mixed verified + composed fields:", mixed_verified_and_composed())
    print("verified_value + amount_scale:", status_and_scale())
    print("nested response paths:", nested_paths())
    print("gap 4 date refusal:", date_refusal())
    print("gap 3 floor and acceptance:", floor_acceptance())
    print("gap 2 identity formats:", identity_formats())
    print("gap 1 hooks:", hooks())
