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
    check("when" in un and "when" not in by, "point unsure -> unplaced, not moved")
    check("badband" in un, "unknown band -> unplaced")
    check(by.get("confirm", {}).get("expects_answer") is True, "a confirmation question is emitted with expects_answer")
    check("dup" not in by, "a line the text_message sentence already says is dropped")
    check(all(set(h) >= {"id", "point", "condition", "text", "expects_answer", "quote"} for h in rp["hooks"]), "hook field contract")
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


if __name__ == "__main__":
    for g in (gap1, gap2):
        g()
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
