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
    check("recorded" in greet and greet.count("digital assistant") == 1, f"greet carries the recording clause once: {greet!r}")
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


def gap2_exact():
    q = {"field": "postcode", "format": "postcode", "format_evidence": {"source": src("Send the postcode exactly as said, letters and digits.")}}
    check(B.answer_format(q)[0] == "free", "'exactly as said' wins over the postcode format -> free")


if __name__ == "__main__":
    for g in (gap1, gap2, gap2_exact, gap3, gap4):
        g()
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
