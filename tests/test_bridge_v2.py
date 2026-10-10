"""Bridge v2 (generalisation gaps), offline: no model calls, no Freya.

    python3 tests/test_bridge_v2.py
Gap 1 hooks: the rewrite of say/tell/warn rules, points kept or unplaced (never moved), closed-set conditions, the
duplicate drop, the recording clause in the greet. Gap 2 identity formats. Gap 3 floor/acceptance. Gap 4 date refusal.
The quotes below are generic test wording written for this file, not taken from any brief.
"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import policy_bridge as B
from builder.generator import generate
from builder.validate_workflow import validate

OAS = os.path.join(ROOT, "tools", "openapi.json")
BASE = json.load(open(os.path.join(ROOT, "tests", "policy_eval", "v3", "run5", "brief-a.json")))
fails = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def bridged(**extra):
    p = copy.deepcopy(BASE)
    p.update(extra)
    rp, rep = B.to_reducer(p, OAS, [])
    return rp, rep


def src(q):
    return [{"file": "t.md", "quote": q}]


def gap1():
    print("== gap 1: hooks")
    L = B.hook_lines
    check(L("Say that interest continues to accrue until the balance is paid.") == "Interest continues to accrue until the balance is paid.",
          "say that X -> X")
    check(L('After the debt, say this sentence: "Late fees may apply to this account."') == "Late fees may apply to this account.",
          "a quoted sentence is kept verbatim")
    check(L("First sentence: say you are a digital assistant calling from Acme Bank, and that the call is recorded.")
          == "I am a digital assistant calling from Acme Bank. The call is recorded.", "'say A, and that B' -> two lines, first person")
    check(L("Warn them that the account may be passed to the legal team.") == "The account may be passed to the legal team.",
          "warn them that X")
    check(L("State the past-due amount and the days late.") == "", "an action ('state the amount') is not a line")
    hooks = [{"id": "fee", "point": "after_debt", "condition": None, "expects_answer": False,
              "source": src("Say that interest continues to accrue until the balance is paid.")},
             {"id": "legal", "point": "on_refusal", "condition": "band=late", "expects_answer": False,
              "source": src("Warn them that the account may be passed to the legal team.")},
             {"id": "when", "point": "unsure", "condition": None, "expects_answer": False,
              "source": src("Remind them that the mobile app shows every payment.")},
             {"id": "whenq", "point": "unsure", "condition": None, "expects_answer": False,
              "source": src('Ask "Would you like a reminder by text message?"')},
             {"id": "whencond", "point": "unsure", "condition": "band=late", "expects_answer": False,
              "source": src("Tell them that the late band has a shorter deadline.")},
             {"id": "badband", "point": "on_refusal", "condition": "band=ultra", "expects_answer": False,
              "source": src("Warn them that the card may be blocked.")},
             {"id": "confirm", "point": "on_no_promise", "condition": None, "expects_answer": True,
              "source": src('Before closing without a promise, ask "Do you confirm that you are not making a promise today?"')},
             {"id": "dup", "point": "on_promise_recorded", "condition": None, "expects_answer": False,
              "source": src('After a recorded promise, say this sentence: "You will receive a text message confirming this promise."')}]
    rp, rep = bridged(hooks=hooks)
    by = {h["id"]: h for h in rp["hooks"]}
    un = {u["id"]: u for u in rp["unplaced_hooks"]}
    check(by.get("fee", {}).get("point") == "after_debt" and by["fee"]["text"].startswith("Interest"), "after_debt hook kept at its point")
    check(by.get("legal", {}).get("condition") == "band=late", "condition kept as band=late")
    check(by.get("when", {}).get("point") == "before_close" and by["when"].get("placed") == "no moment given",
          "a timeless plain statement with no moment -> before_close, marked placed")
    check("whenq" in un and "whencond" in un, "an unsure question or conditional line stays unplaced (never bolted on)")
    check("badband" in un, "unknown band -> unplaced")
    check(by.get("confirm", {}).get("expects_answer") is True, "a confirmation question is emitted with expects_answer")
    check("dup" not in by, "a line the text_message sentence already says is dropped")
    check(all(set(h) >= {"id", "point", "condition", "text", "expects_answer", "quote"} for h in rp["hooks"]), "hook field contract")
    # the e2e8 rebuild bolted situation lines onto the goodbye: an unsure line tied to a situation stays unplaced
    sit = [{"id": f"s{i}", "point": "unsure", "condition": None, "expects_answer": False, "source": src(q)} for i, q in enumerate((
        'If the person says the customer has died, say "I am sorry for your loss.", ask nothing else.',
        "If it fails again, say you could not record it and close as `no_promise` / `service_error`.",
        "Below the floor, say it cannot be recorded and offer the floor once.",
        "One date for every product: record that product on its own deadline and say so in the read-back."))]
    sit.append({"id": "overdue", "point": "unsure", "condition": None, "expects_answer": False,
                "source": src("Say that the rest stays overdue.")})
    rp_s, _ = bridged(hooks=sit)
    check(not [h for h in rp_s["hooks"] if h["id"].startswith("s")], "situation lines are never placed at before_close")
    check(not [h for h in rp_s["hooks"] if h["id"] == "overdue"], "a line the reducer already says (the rest stays overdue) is dropped")
    check(B.hook_lines("Tell the person to use the mobile app or write to us.") == "Please use the mobile app or write to us.",
          "tell the person to X -> Please X.")
    wf = generate(rp, OAS)
    greet = wf["nodes"]["greet"]["on_enter"]["text"]
    check("keep a recording" in greet and "recorded" not in greet and greet.count("digital assistant") == 1, f"greet carries the recording clause once: {greet!r}")
    check(not [e for e in validate(wf, rp, OAS) if e.startswith("17")], "validator 17 passes")
    bad = copy.deepcopy(rp)
    bad["hooks"].append({"id": "x", "point": "somewhere", "condition": "colour=red", "text": "Then offer the desk.", "quote": "q"})
    errs = [e for e in validate(generate(bad, OAS), bad, OAS) if e.startswith("17")]
    check(len(errs) >= 3, f"validator 17 catches a bad point, condition and instruction text ({len(errs)})")
    rp2 = copy.deepcopy(rp)
    rp2["hooks"] = [h for h in rp2["hooks"] if h["point"] != "opening"]
    wf2 = generate(rp, OAS)
    wf2["nodes"]["greet"]["on_enter"]["text"] = "Hello."
    check(any(e.startswith("17") and "greet" in e for e in validate(wf2, rp, OAS)), "validator 17 catches a greet without the opening hook")


def gap2():
    print("== gap 2: identity formats")
    F = lambda **q: B.answer_format(q)[0]
    check(F(field="date_of_birth", format="YYYY-MM-DD") == "date", "YYYY-MM-DD -> date")
    check(F(field="phone_last4", format="last four digits") == "digits(4)", "last four digits -> digits(4)")
    check(F(field="tckn_last3", brief_name="last 3 digits of the national ID") == "digits(3)", "last 3 digits -> digits(3)")
    check(F(field="year_of_birth", format="YYYY") == "digits(4)", "YYYY -> digits(4)")
    check(F(field="postcode", format="as said, letters and digits") == "postcode", "postcode -> postcode")
    check(F(field="fathers_name", brief_name="father's first name") == "name", "father's name -> name")
    check(F(field="policy_ref", brief_name="last four characters of the policy number") == "alnum", "characters -> alnum")
    check(F(field="secret", format="digits(6)") == "digits(6)", "an extractor token is kept")
    check(F(field="hobby", brief_name="favourite colour") == "free", "nothing known -> free")
    rp, _ = bridged()
    check([q["format"] for q in rp["identity"]["questions"]] == ["date", "digits(4)"], "brief A run5 -> date, digits(4)")
    bad = copy.deepcopy(rp)
    bad["identity"]["questions"][0]["format"] = "YYYY-MM-DD"
    check(any(e.startswith("18") for e in validate(generate(bad, OAS), bad, OAS)), "validator 18 catches a free-text format")


def gap3():
    print("== gap 3: floor and acceptance")
    S = lambda v, f=("minimum_payment",): B.floor_spec(v, list(f))
    check(S({"kind": "account_field", "field": "minimum_payment"})[0] == {"kind": "field", "field": "minimum_payment", "source": B.DEFAULT},
          "old account_field -> {kind: field, field}")
    r = S({"kind": "percent_of_past_due", "percent": 30, "round": "up"})[0]
    check(r and r["kind"] == "percent" and r["percent"] == 30 and r["round"] == "up", "old percent_of_past_due -> {kind: percent, percent, round}")
    r = S({"kind": "max_fixed_percent", "amount": 50, "percent": 10, "round": "nearest", "to": "unit"})[0]
    check(r and (r["amount"], r["percent"], r["to"]) == (50, 10, "unit"), "max_fixed_percent keeps amount, percent, round, to")
    check(S({"kind": "fixed", "amount": 25})[0]["amount"] == 25, "fixed amount")
    check(S({"kind": "field", "field": "not_in_oas"})[0] is None, "a floor field not in the OAS response is refused")
    check(S({"kind": "percent", "percent": 140})[0] is None, "percent outside (0, 100] is refused")
    A = B.acceptance_rule
    check(A(None)[0] == "floor_to_full" and A("full_only")[0] == "full_only", "acceptance default and full_only")
    check(A({"kind": "min_x", "min": 50})[0] == {"kind": "min_x", "min": 50}, "min_x keeps its min")
    check(A({"kind": "min_x"})[0] is None and A("half")[0] is None, "min_x without min / unknown kind refused")
    p = {"products": {"floor_by_type": {"*": {"kind": "percent", "percent": 30, "round": "nearest", "to": "cent"}}},
         "amounts": {"acceptance": {"kind": "min_x", "min": 40}}}
    rp, rep = bridged(**p)
    check(rp["products"]["floor_by_type"].get("*", {}).get("percent") == 30, "'*' is kept as the any-type key")
    check(rp["amounts"]["acceptance"] == {"kind": "min_x", "min": 40}, "acceptance emitted as {kind: min_x, min}")
    check(not [e for e in validate(generate(rp, OAS), rp, OAS) if e.startswith("19")], "validator 19 passes")
    bad = copy.deepcopy(rp)
    bad["products"]["floor_by_type"]["*"] = {"kind": "percent"}
    bad["amounts"]["acceptance"] = "half"
    check(len([e for e in validate(generate(bad, OAS), bad, OAS) if e.startswith("19")]) == 2, "validator 19 catches a bad floor and acceptance")
    rp, rep = bridged(products=dict(BASE["products"], floor_by_type={"credit_card": {"kind": "field", "field": "no_such_field"}}))
    check(not rp["products"]["floor_by_type"] and any("floor_by_type" in m["policy_path"] for m in rep["api_mismatch"]),
          "an unbindable floor field -> api_mismatch, never a guessed field")


def gap4():
    print("== gap 4: date rules")
    rp, rep = bridged()
    dr = rp["date_rules"]
    check(dr["weekend"]["action"] == dr["holiday"]["action"] == "shift_next_business_day", "brief A legacy: weekend/holiday shift")
    check(dr["after_deadline"]["action"] == "offer_deadline" and dr["past"]["action"] == "refuse", "after_deadline offer, past refuse")
    p = {"date_rules": {"weekend": {"action": "refuse", "say": "We cannot take a payment date on a weekend. Which weekday suits you?",
                                    "source": src("Weekend dates are refused: say \"We cannot take a payment date on a weekend. Which weekday suits you?\"")},
                        "holiday": {"action": "shift_next_business_day", "say": "Then you should pick another day, please.",
                                    "source": src("A holiday moves to the next business day.")},
                        "today_not_allowed": {"action": "refuse", "say": "", "source": src("A promise for today is not accepted.")}}}
    rp, rep = bridged(**p)
    dr = rp["date_rules"]
    check(dr["weekend"] == dict(dr["weekend"], action="refuse", say="We cannot take a payment date on a weekend. Which weekday suits you?"),
          "a brief-worded refusal sentence is kept with action refuse")
    check(dr["holiday"]["action"] == "shift_next_business_day" and "say" not in dr["holiday"], "an invented say is omitted (reducer default)")
    check(dr["today_not_allowed"]["action"] == "refuse", "today_not_allowed refuse")
    check(not [e for e in validate(generate(rp, OAS), rp, OAS) if e.startswith("19")], "validator 19 passes on date_rules")
    bad = copy.deepcopy(rp)
    bad["date_rules"]["weekend"]["action"] = "ignore"
    check(any(e.startswith("19") for e in validate(generate(bad, OAS), bad, OAS)), "validator 19 catches an unknown action")


def regressions():
    print("== regressions from the ae1890b rebuild")
    # raw-b: the relative row came back with reason None (the extractor quoted another rule) -> rb-third closed with no reason
    p = copy.deepcopy(BASE)
    p["opening_situations"] = dict(p.get("opening_situations") or {}, wrong_person={
        "present": True, "effect": "close", "outcome": "not_reached", "reason": "", "say": "",
        "source": src("A relative may not answer security questions and may not be told the balance.")})
    rp, rep = B.to_reducer(p, OAS, [])
    rel = [w for w in rp["who_rules"] if w.get("party") == "relative"]
    check(rel and rel[0]["effect_kind"] == "callback" and rel[0]["reason"], f"relative row books a callback with its reason: {rel}")
    check(all(w.get("reason") for w in rp["who_rules"] if w.get("effect_kind") == "callback"), "every callback who-row carries its reason")
    for name in ("brief-a", "brief-ab", "ins-clean", "raw-b", "mut-03"):
        f = os.path.join(ROOT, "tests", "e2e8", "submission", name + ".extracted.json")
        if os.path.exists(f):
            oas = os.path.join(ROOT, "tests", "fixtures", "general", "ins-clean", "openapi.json") if name == "ins-clean" else OAS
            r2, _ = B.to_reducer(json.load(open(f)), oas, [])
            bad = [w for w in r2["who_rules"] if w.get("effect_kind") == "callback" and not w.get("reason")]
            check(not bad, f"{name}: every callback who-row carries its reason")
    # raw-b dates: 'must be a business day' is not a refusal -> shift (legacy); refuse only when the material says so
    q = src("A promise date must be today or later, a business day, and not after that product's deadline.")
    rp, _ = bridged(date_rules={"weekend": {"action": "refuse", "say": "", "source": q}, "holiday": {"action": "refuse", "say": "", "source": q}},
                    on_non_business_day=dict(BASE["on_non_business_day"], action="reject", source=q))
    check(rp["date_rules"]["weekend"]["action"] == "shift_next_business_day" == rp["date_rules"]["holiday"]["action"],
          "refuse without an explicit refusal -> shift_next_business_day")
    check(rp["on_non_business_day"]["action"] == "next_business_day", "legacy section made consistent with the weekend rule")
    q2 = src("Weekend dates are refused: ask for a weekday.")
    rp, _ = bridged(date_rules={"weekend": {"action": "refuse", "say": "<NAMED> is not a business day. The next business day is <DATE>.", "source": q2}})
    check(rp["date_rules"]["weekend"]["action"] == "refuse" and "say" not in rp["date_rules"]["weekend"],
          "an explicit refusal stays refuse, and a shift line is never paired with it")


def derive_fixes():
    print("== integration: sentence derive")
    p = copy.deepcopy(BASE)
    p["sentences"] = dict(p.get("sentences") or {}, debt_intro={"text": "", "source": []})
    for k in ("unmapped",):
        p.pop(k, None)
    text = "17. Say that you are calling from the collections team about a late payment. State the amount."
    rp, _ = B.to_reducer(p, OAS, [], text)
    check(rp["sentences"]["debt_intro"]["text"] == "I am calling from the collections team about a late payment.",
          "an empty extractor debt_intro is derived from the brief's own line (the run had no quote for it)")
    p2 = copy.deepcopy(BASE)
    p2["hooks"] = [{"id": "f", "point": "unsure", "condition": None, "expects_answer": False,
                    "source": src("Tell the person to use the mobile app or write to the bank.")}]
    rp2, _ = B.to_reducer(p2, OAS, [], "Tell the person to use the mobile app or write to the bank.")
    check(rp2["sentences"]["id_fail"]["text"] == "Please use the mobile app or write to the bank.", "id_fail from 'tell the person to X'")
    check(not [h for h in rp2["hooks"] if h["id"] == "f"], "the id_fail line is not also placed as a hook")


def integration_fixes():
    print("== integration: call roles, hardship decline")
    p = copy.deepcopy(BASE)
    p["meta"] = dict(p.get("meta") or {}, call_vars={"customer": "customer_id", "title": "title"})
    rp, _ = B.to_reducer(p, OAS, [])
    cv = rp["meta"]["call_vars"]
    check(all(cv.get(r) == r for r in B.CALL_ROLES), f"every reducer call role is mapped ({cv})")
    p = copy.deepcopy(BASE)
    tc = dict(p.get("topic_checklist") or {})
    tc["hardship"] = {"present": True, "say": "", "effect": "offer support", "outcome": "transferred", "reason": "support",
                      "note_reason": "", "source": src("If they accept, transfer to support.")}
    p["topic_checklist"] = tc
    p["closing"] = dict(p["closing"], table=[r for r in p["closing"]["table"]] +
                        [{"outcome": "no_promise", "reason": "hardship", "when": "hardship, declined the support transfer"}])
    rp, _ = B.to_reducer(p, OAS, [])
    rows = [(e.get("outcome"), e.get("reason")) for e in rp["events"] if e["topic"] == "hardship"]
    check(("no_promise", "hardship") in rows and ("transferred", "support") in rows, f"hardship accept + decline rows: {rows}")
    rp, _ = B.to_reducer(p, OAS, [], "31. If the person mentions job loss, offer to connect them with the wellbeing team.")
    check({e.get("desk") for e in rp["events"] if e["topic"] == "hardship"} == {"wellbeing team"}, "hardship desk name from the brief's words")


def honesty():
    print("== honesty: no 'recorded' before a tool result (PUB-10 judge, call 6818f744)")
    H = B.honest_line
    check(H("The call is recorded.")[0] == "Please note that we keep a recording of this call.", "recording notice rewritten")
    check(H("This call is recorded for training.")[0] == "Please note that we keep a recording of this call for training.",
          "purpose kept in the rewrite")
    check(H("Your callback is booked.")[0] is None, "another honesty word -> not spoken")
    hooks = [{"id": "rec", "point": "opening", "condition": None, "expects_answer": False,
              "source": src("First sentence: say you are the assistant of the bank, and that the call is recorded.")},
             {"id": "sav", "point": "after_debt", "condition": None, "expects_answer": False,
              "source": src("Tell them that their details are saved.")},
             {"id": "ok", "point": "on_promise_recorded", "condition": None, "expects_answer": False,
              "source": src('After a recorded promise, say "Your arrangement is saved in our system."')}]
    rp, _ = bridged(hooks=hooks)
    by = {h["id"]: h for h in rp["hooks"]}
    check("recorded" not in by["rec"]["text"] and "keep a recording" in by["rec"]["text"], f"opening hook rewritten: {by['rec']['text']!r}")
    check("sav" not in by and any(u["id"] == "sav" for u in rp["unplaced_hooks"]), "a pre-result 'saved' line is unplaced")
    check("saved" in by.get("ok", {}).get("text", ""), "on_promise_recorded keeps its honesty word")
    wf = generate(rp, OAS)
    g = wf["nodes"]["greet"]["on_enter"]["text"]
    check("recorded" not in g.lower() and "keep a recording" in g, f"greet: {g!r}")
    check(not [e for e in validate(wf, rp, OAS) if e.startswith("20")], "validator 20 passes")
    wf["nodes"]["greet"]["on_enter"]["text"] = "Hello. The call is recorded."
    check(any(e.startswith("20") for e in validate(wf, rp, OAS)), "validator 20 catches 'recorded' in the greet")


def bank_names():
    print("== composed self-descriptions name the bank once")
    from builder.generator import self_description
    check(self_description({"agent_self_description": "digital assistant calling from Freya Bank", "bank_name": "Freya Bank"})
          == "the digital assistant calling from Freya Bank", "a description that names the bank is kept")
    check(self_description({"agent_self_description": "digital assistant", "bank_name": "Freya Bank"}) == "the digital assistant of Freya Bank",
          "a description without the bank gets 'of <bank>'")
    p = copy.deepcopy(BASE)
    p["meta"] = dict(p.get("meta") or {}, agent_self_description="digital assistant calling from Freya Bank", bank_name="Freya Bank", language="en")
    rp, _ = B.to_reducer(p, OAS, [])
    wf = generate(rp, OAS)
    check(wf["system_prompt"].count("Freya Bank") == 1 and "Speak English" in wf["system_prompt"], f"system prompt: {wf['system_prompt'][:90]!r}")
    check(not [e for e in validate(wf, rp, OAS) if e.startswith("21")], "validator 21 passes")
    wf["system_prompt"] = "You are the digital assistant calling from Freya Bank of Freya Bank."
    check(any(e.startswith("21") for e in validate(wf, rp, OAS)), "validator 21 catches the doubled bank name")


def placeholders():
    print("== unknown placeholders are never spoken (F9)")
    from builder.selftest import walk_smoke
    p = copy.deepcopy(BASE)
    p["meta"] = dict(p.get("meta") or {}, call_vars=dict((p.get("meta") or {}).get("call_vars") or {}, company_name="company_name"))
    p["sentences"] = dict(p.get("sentences") or {}, confirm_who={"text": "Am I speaking with the accounts contact of {company_name}?",
                                                                 "verbatim": True, "source": src("x")})
    rp, rep = B.to_reducer(p, OAS, [])
    wf = generate(rp, OAS)
    g = wf["nodes"]["greet"]["on_enter"]["text"]
    check("{{company_name}}" in g and not [e for e in validate(wf, rp, OAS) if e.startswith("22")], f"a declared {{company_name}} stays: {g!r}")
    check(not walk_smoke(rp, wf, OAS)["errors"], "the walker resolves it")
    p2 = copy.deepcopy(BASE)
    p2["sentences"] = dict(p2.get("sentences") or {}, confirm_who={"text": "Am I speaking with {title} {last_name}, of {account_manager}?",
                                                                   "verbatim": True, "source": src("x")})
    p2["hooks"] = [{"id": "ref", "point": "after_debt", "condition": None, "expects_answer": False,
                    "source": src('After the debt, say "Your case number is {case_no}."')}]
    rp2, rep2 = B.to_reducer(p2, OAS, [])
    wf2 = generate(rp2, OAS)
    g2 = wf2["nodes"]["greet"]["on_enter"]["text"]
    check("account_manager" not in g2 and "{{title}}" in g2, f"an undeclared placeholder's clause is dropped from the greet: {g2!r}")
    check(not [h for h in rp2["hooks"] if "case_no" in h.get("text", "")] and any("case_no" in n for n in rep2["notes"]),
          "a hook with an undeclared placeholder is not spoken, and noted")
    check(not [e for e in validate(wf2, rp2, OAS) if e.startswith("22")], "validator 22 passes")
    wf2["nodes"]["greet"]["on_enter"]["text"] += " {{account_manager}}"
    check(any(e.startswith("22") for e in validate(wf2, rp2, OAS)), "validator 22 catches an undeclared spoken placeholder")


def too_much():
    print("== amounts.too_much_date (PUB-07 / clean-1)")
    T = B.too_much_date
    check(T({"too_much": "offer the floor once and say that the rest stays overdue"})[0] == "offer", "brief A: no day named -> offer")
    check(T({"too_much": "offer the floor once, on the deadline; this offer uses no attempt"})[0] == "deadline", "clean-1 rule 15 -> deadline")
    check(T({"too_much": "say you cannot record it today"})[0] == "offer", "'not today' is not a day for the floor offer")
    check(T({"too_much_date": "today", "too_much_date_evidence": {"source": src("Offer the floor for today.")}})[0] == "today",
          "a quoted extractor value wins")
    check(T({"too_much_date": "deadline"})[0] == "offer", "an unquoted extractor value is not taken")
    rp, _ = bridged()
    check(rp["amounts"]["too_much_date"] == "offer", "brief A bridged -> offer (PUB-06 stays on the offer's day)")


def rehearsal():
    print("== rehearsal misreads (nightmare-1, raw-2, biz-1)")
    p = copy.deepcopy(BASE)
    p["sentences"] = dict(p.get("sentences") or {}, opening={"text": "This is the bank. This call is recorded.", "source": src("x")})
    p["sentences"].pop("recorded", None)
    rp, _ = B.to_reducer(p, OAS, [])
    check("call" not in rp["sentences"]["recorded"]["text"], f"the call-recording opening is not the 'recorded' line: {rp['sentences']['recorded']['text']!r}")
    import re as _re
    pat, fn = B.DERIVE["debt_intro"]
    m = _re.search(pat, "First sentence: say you are calling from Sable Mutual, and that the call is recorded.", _re.I)
    check(not m or not fn(m), f"the opening rule is not a debt intro: {fn(m) if m else None!r}")
    m = _re.search(pat, "Say that you are calling from the collections team about a late payment.", _re.I)
    check(m and fn(m).rstrip(".") == "I am calling from the collections team about a late payment", "a real debt intro still derives")
    check(B.full_or_floor({"accept_range": "only the full balance or exactly the floor"}) and
          B.full_or_floor({"accept_range": "the full past-due amount, or exactly 50 percent of past_due; any other amount below the full balance is refused"}),
          "'only full or exactly the floor / N percent' -> full_or_floor")
    check(not B.full_or_floor({"accept_range": "from the floor up to the full past-due amount, both included"}), "a range stays floor_to_full")
    p = copy.deepcopy(BASE)
    p["events"] = list(p.get("events") or []) + [{"topic": "complaint", "outcome": "no_promise", "reason": "dispute", "effect": "stop and close",
                                                  "source": src("If the customer wants to make a complaint, stop.")}]
    rp, _ = B.to_reducer(p, OAS, [])
    check([x["id"] for x in rp["extra_topics"]] == ["complaint"] and rp["extra_topics"][0]["outcome"] == "no_promise",
          f"an extra situation with a bound immediate close -> extra_topics: {rp['extra_topics']}")
    p["events"][-1]["effect"] = "explain once; a second time closes"
    rp, _ = B.to_reducer(p, OAS, [])
    check(not rp["extra_topics"], "a close only on a second time is not an immediate extra-topic close")
    p = copy.deepcopy(BASE)
    p["opening_checks"] = [{"ask": "Are you authorised to discuss this account?", "on_no": "third_party",
                            "source": src('When they say they are that person, ask "Are you authorised to discuss this account?"')},
                           {"ask": "Is now a good time?", "on_no": "close", "source": src("Something else entirely.")}]
    rp, _ = B.to_reducer(p, OAS, [])
    check([c["ask"] for c in rp["opening_checks"]] == ["Are you authorised to discuss this account?"], "opening checks: only the brief's own words")
    p = copy.deepcopy(BASE)
    p["opening_situations"] = dict(p.get("opening_situations") or {}, wrong_person={"present": True, "effect": "callback", "outcome": "not_reached",
                                   "reason": "callback", "say": "", "source": src("A colleague answers.")})
    rp, _ = B.to_reducer(p, OAS, [], "4. A colleague: do not take security answers. Ask when an authorised person can be reached.")
    rel = [w for w in rp["who_rules"] if w.get("party") == "relative"]
    check(rel and rel[0]["say"] == "When can an authorised person be reached?", f"third-party ask from the brief: {rel and rel[0].get('say')}")


def assistant_disclosure():
    print("== the greet says the agent is an assistant unless the brief forbids it")
    p = copy.deepcopy(BASE)
    p["sentences"] = dict(p.get("sentences") or {}, opening={"text": "This is Oak Bank. This call is recorded.", "source": src("x")})
    p["meta"] = dict(p.get("meta") or {}, bank_name="Oak Bank", agent_self_description="Oak Bank")
    rp, _ = B.to_reducer(p, OAS, [])
    g = generate(rp, OAS)["nodes"]["greet"]["on_enter"]["text"]
    check(g.startswith("This is Oak Bank.") and "I am a digital assistant." in g, f"disclosure added after the brief's opening: {g!r}")
    rp, _ = B.to_reducer(p, OAS, [], '1. First sentence: "This is Oak Bank." Do not say that you are an AI or an assistant.')
    g = generate(rp, OAS)["nodes"]["greet"]["on_enter"]["text"]
    check("assistant" not in g, f"a brief that forbids it gets no disclosure: {g!r}")
    rp, _ = bridged()
    g = generate(rp, OAS)["nodes"]["greet"]["on_enter"]["text"]
    check(g.count("assistant") == 1, f"an opening that already says it is not changed: {g!r}")


def synthetic_fixes():
    print("== queues, notes and asks as the brief states them (synthetic briefs)")
    t = ("Restructuring transfers to general and closes transferred / restructuring. Ask an insistent human requester once "
         "whether you can help, then transfer to restructuring and close transferred / human.")
    check(B.explicit_queues(t, {"restructure", "human", "hardship"}, ["general", "restructuring", "support"])
          == {"restructure": "general", "human": "restructuring"}, "queue_map follows the brief's literal transfer targets")
    check(not B.notes_asked('Before ending a call without a promise, ask "Can I note that you are not making a payment promise today?"'),
          "a 'Can I note ...?' question does not enable notes")
    check(not B.notes_asked("Do not use add_note. Any transfer suppresses all notes."), "'Do not use add_note' disables notes")
    check(B.notes_asked("For paid or dispute on one product, add the matching note and continue."), "'add the matching note' enables notes")
    check(B.note_reasons(["refused", "dispute_x"], "note_reason,dispute,DISPUTE_NOTE,dispute_x\n") == {"refused": "refused", "dispute": "dispute_x"},
          "note reasons: the same OAS value or the codes row, else left out")
    check(B.default_ask({"field": "phone_last4"}) == "Could you confirm the last four digits of your phone number, please?",
          "an empty ask gets the contract default")
    Q = [{"file": "b.md", "quote": "The floor is 33.33% of past_due, rounded nearest to 0.05."}]
    check(B.floor_spec({"kind": "percent", "percent": 33.33, "round": "nearest", "to": "0.05"}, [], Q)[0].get("to") == 0.05,
          "floor rounding increment 0.05 kept (quote on the products block)")
    check(B.floor_spec({"kind": "percent", "percent": 33.33, "round": "nearest"}, [], Q)[0].get("to") == 0.05,
          "a missing increment is read from the floor quote")
    check("to" not in B.floor_spec({"kind": "percent", "percent": 33.33, "round": "nearest", "to": 0.25}, [], Q)[0],
          "an increment no quote states is dropped")
    check(B.round_step(None, [{"quote": "rounded up to the nearest 5 cents"}]) == 0.05, "'nearest 5 cents' -> 0.05")
    p = copy.deepcopy(BASE)
    p["identity"]["questions"][0]["ask"] = ""
    rp, _ = B.to_reducer(p, OAS, [])
    check(all(q["ask"].strip() for q in rp["identity"]["questions"]), "no empty identity ask leaves the bridge")
    rp["identity"]["questions"][0]["ask"] = ""
    check(any("empty ask" in e for e in validate(generate(rp, OAS), rp, OAS)), "validator 3 catches an empty identity ask")


def gap2_exact():
    q = {"field": "postcode", "format": "postcode", "format_evidence": {"source": src("Send the postcode exactly as said, letters and digits.")}}
    check(B.answer_format(q)[0] == "free", "'exactly as said' wins over the postcode format -> free")


if __name__ == "__main__":
    for g in (gap1, gap2, gap2_exact, gap3, gap4, regressions, derive_fixes, integration_fixes, honesty, bank_names, placeholders, too_much, rehearsal, assistant_disclosure, synthetic_fixes):
        g()
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
