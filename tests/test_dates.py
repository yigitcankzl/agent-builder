"""Local test runner for the date engine. It execs THE SAME code string that goes into the Freya code node
(builder.engine.codegen.code_source) with a vars dict. No second implementation: expectations are hand-written
cases from the fixture policy, plus metamorphic tests (change a holiday or a deadline, the result must change).

    python3 tests/test_dates.py
Public brief values (dates, amounts, names) appear only in tests/fixtures and in this file, never in builder/.
"""
import copy, datetime, json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine.codegen import code_source
from builder.engine.date_policy import validate

FIX = json.load(open(os.path.join(ROOT, "tests", "fixtures", "brief_a_date_policy.json")))
NOW = "2026-10-14T11:00"  # a Wednesday
EARLY = [{"product_id": "p1", "days_late": 5}]   # deadline 12 business days -> 2026-11-02 (holiday 10-26 skipped)
LATE = [{"product_id": "p1", "days_late": 14}]   # deadline 7 business days  -> 2026-10-23
_CODE = {}


def run(policy, vars_):
    """Exec the emitted code-node string, exactly as Freya would, on vars_ (mutated and returned)."""
    key = json.dumps(policy, sort_keys=True)
    if key not in _CODE:
        _CODE[key] = compile(code_source(policy), "date_resolve", "exec")
    exec(_CODE[key], {"vars": vars_})
    return vars_


def turn(said, products=EARLY, now=NOW, policy=FIX, state=None, current="p1"):
    v = dict(state or {})
    v.update(now=now, products=json.dumps(products), current_product_id=current, date_said=said)
    return run(policy, v)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def expect(v, reason, accepted, route, say_has=()):
    got = (v.get("date_reason"), v.get("accepted_date"), v.get("route_date"))
    check(got == (reason, accepted, route), f"got {got}, expected {(reason, accepted, route)} | {v.get('say_next')!r} {v.get('date_error', '')}")
    for s in say_has:
        check(s in v["say_next"], f"say_next {v['say_next']!r} lacks {s!r}")


def test_policy_valid_and_quoted():
    check(validate(FIX, open(os.path.join(ROOT, "briefs", "brief-a.md")).read()) == [], "fixture policy invalid")
    bad = copy.deepcopy(FIX); bad["deadline"]["source"] = ["a sentence that is not in the brief"]
    check(any("not found in the brief" in e for e in validate(bad, open(os.path.join(ROOT, "briefs", "brief-a.md")).read())), "fake quote accepted")
    bad = copy.deepcopy(FIX); bad["on_after_deadline"]["action"] = "haggle"
    check(validate(bad), "unknown action accepted")


def test_cases():
    expect(turn("2026-10-16"), "ok", "2026-10-16", "continue")                                       # normal business day
    expect(turn("2026-10-14"), "ok", "2026-10-14", "continue")                                       # today allowed
    expect(turn("2026-10-17"), "non_business_day", "2026-10-19", "say", ["Saturday 17 October", "Monday 19 October"])
    expect(turn("2026-10-26"), "non_business_day", "2026-10-27", "say", ["Monday 26 October", "Tuesday 27 October"])  # holiday
    expect(turn("2026-10-24"), "non_business_day", "2026-10-27", "say")                              # Sat -> Mon holiday -> Tue
    expect(turn("2026-10-23", LATE), "ok", "2026-10-23", "continue")                                 # on the deadline
    expect(turn("2026-10-22", LATE), "ok", "2026-10-22", "continue")                                 # before the deadline
    expect(turn("2026-10-27", LATE), "after_deadline", "2026-10-23", "say", ["Friday 23 October"])  # after the deadline
    expect(turn("2026-11-06", LATE), "after_deadline", "2026-10-23", "say")
    expect(turn("2026-11-02"), "ok", "2026-11-02", "continue")                                       # early-band deadline
    expect(turn("2026-11-03"), "after_deadline", "2026-11-02", "say", ["Monday 2 November"])
    expect(turn("2026-10-10"), "before_earliest", "", "say")                                         # past
    expect(turn("tomorrow"), "invalid", "", "say")                                                    # not normalized
    expect(turn("vague: next week"), "vague", "", "say", ["exact day"])


def test_month_and_year_boundary():
    # now Wed 2026-12-30: 12-31 Thu ok, 2027-01-01 holiday Fri -> Mon 01-04, early deadline crosses the year
    expect(turn("2026-12-31", now="2026-12-30T10:00"), "ok", "2026-12-31", "continue")
    expect(turn("2027-01-01", now="2026-12-30T10:00"), "non_business_day", "2027-01-04", "say", ["Friday 1 January", "Monday 4 January"])
    v = turn("2027-01-20", LATE, now="2026-12-30T10:00")
    expect(v, "after_deadline", v["date_deadline"], "say")
    check(v["date_deadline"] == "2027-01-11", f"late deadline across the year: {v['date_deadline']}")
    # month boundary: now Fri 2026-10-30, Sat 10-31 -> Mon 11-02
    expect(turn("2026-10-31", now="2026-10-30T09:00"), "non_business_day", "2026-11-02", "say")


def test_runtime_now_changes_the_answer():
    expect(turn("2026-10-16", now="2026-10-14T11:00"), "ok", "2026-10-16", "continue")
    expect(turn("2026-10-16", now="2026-10-19T11:00"), "before_earliest", "", "say")
    a, b = turn("2026-10-30", LATE, now="2026-10-14T11:00"), turn("2026-10-30", LATE, now="2026-10-21T11:00")
    check(a["date_reason"] == "after_deadline" and b["date_reason"] == "ok", (a["date_reason"], b["date_reason"]))


def test_product_deadlines():
    prods = [{"product_id": "p1", "days_late": 4}, {"product_id": "p2", "days_late": 20}]
    expect(turn("2026-10-30", prods, current="p1"), "ok", "2026-10-30", "continue")                 # early band
    expect(turn("2026-10-30", prods, current="p2"), "after_deadline", "2026-10-23", "say")          # late band
    expect(turn("2026-10-30", prods, current="missing"), "ok", "2026-10-30", "continue")            # falls back to first
    v = turn("2026-10-30", [], state={"days_late": "20"})                                            # plain variable
    expect(v, "after_deadline", "2026-10-23", "say")


def test_correction_sticky_and_empty():
    v = turn("2026-10-21")
    expect(v, "ok", "2026-10-21", "continue")
    v = turn("2026-10-20", state=v)                                                                   # corrected -> new decision
    check(v["date_state"] == "new", "correction is a new value")
    expect(v, "ok", "2026-10-20", "continue")
    v = turn("2026-10-26", state=v)
    expect(v, "non_business_day", "2026-10-27", "say")
    v = turn("2026-10-26", state=v)                                                                   # sticky: no new date this turn
    check(v["date_state"] == "same" and v["route_date"] == "continue", "sticky value must not be re-decided")
    check(v["accepted_date"] == "2026-10-27" and v["date_reason"] == "non_business_day", "earlier decision kept")
    v = turn("", state={})
    check(v["route_date"] == "continue" and "date_reason" not in v, "empty extraction does nothing")


def test_vague_then_final():
    v = turn("vague: next week")
    expect(v, "vague", "", "say")
    v = turn("vague: when my salary comes", state=v)
    expect(v, "vague_final", "2026-11-02", "say", ["Monday 2 November"])
    v = turn("2026-10-28", state=v)                                                                   # then an exact day
    expect(v, "ok", "2026-10-28", "continue")


def test_never_raises():
    for bad in ({"now": "garbage", "date_said": "2026-10-16"}, {"date_said": "2026-10-16"},
                {"now": NOW, "date_said": "2026-10-16", "products": "{not json", "days_late": "x"}):
        v = run(FIX, dict(bad))
        check(v["date_reason"] == "error" and v["route_date"] == "continue" and v["accepted_date"] == "", v)
    check(all(isinstance(v, str) for k, v in turn("2026-10-26").items() if k in ("route_date", "date_state", "date_reason")),
          "routing flags are strings")


def test_metamorphic():
    base = turn("2026-10-21")["date_reason"]
    p = copy.deepcopy(FIX); p["business_days"]["holidays"].append("2026-10-21")
    check(base == "ok" and turn("2026-10-21", policy=p)["date_reason"] == "non_business_day", "a new holiday must change the answer")
    p = copy.deepcopy(FIX); p["deadline"]["bands"][0]["days"] = 3                                    # early deadline -> 10-19
    check(turn("2026-10-21", policy=p)["date_reason"] == "after_deadline", "a shorter deadline must change the answer")
    p = copy.deepcopy(FIX); p["business_days"]["weekdays"] = [0, 1, 2, 3, 4, 5]                      # Saturday becomes a business day
    check(turn("2026-10-17", policy=p)["date_reason"] == "ok", "a working Saturday must be accepted")
    p = copy.deepcopy(FIX); p["on_non_business_day"]["action"] = "previous_business_day"
    expect(turn("2026-10-17", policy=p), "non_business_day", "2026-10-16", "say")
    p = copy.deepcopy(FIX); p["on_after_deadline"]["action"] = "reject"
    expect(turn("2026-11-06", LATE, policy=p), "after_deadline", "", "say")
    p = copy.deepcopy(FIX); p["earliest"]["allow_today"] = False
    expect(turn("2026-10-14", policy=p), "before_earliest", "", "say")
    p = copy.deepcopy(FIX); p["deadline"]["rule"] = "calendar_days_after_today"; p["deadline"]["bands"][0]["days"] = 3
    v = turn("2026-10-19", policy=p)                                                                  # deadline Sat 10-17 -> Fri 10-16
    check(v["date_deadline"] == "2026-10-16" and v["date_reason"] == "after_deadline", (v["date_deadline"], v["date_reason"]))
    # invariants over a range of days: whatever is accepted is a business day inside [today, deadline]
    for i in range(0, 40):
        for prods in (EARLY, LATE):
            d = (datetime.date(2026, 10, 14) + datetime.timedelta(days=i)).isoformat()
            v = turn(d, prods)
            if v["accepted_date"]:
                a = datetime.date.fromisoformat(v["accepted_date"])
                check(a.weekday() < 5 and v["accepted_date"] not in FIX["business_days"]["holidays"], f"{d}: accepted non-business {a}")
                check(datetime.date(2026, 10, 14) <= a <= datetime.date.fromisoformat(v["date_deadline"]), f"{d}: accepted outside window")


def test_code_string_rules():
    code = code_source(FIX)
    check("{{" not in code and "}}" not in code, "double braces in the code string")
    check("raise" not in code.split("def run_safe")[1], "run_safe must not raise")
    # nested policy dicts serialise to '}}' in JSON; the emitter must break them up (checked above on FIX itself)
    check("}}" in json.dumps(FIX), "fixture exercises the nested-brace case")
    tricky = copy.deepcopy(FIX); tricky["on_invalid"]["say"] = "Sorry, which date? {{x}}"
    try:
        code_source(tricky); check(False, "a sentence with a placeholder must be rejected")
    except ValueError:
        pass


def test_no_public_values_in_builder():
    banned = set(FIX["business_days"]["holidays"]) | {"2026-10-14", "2026-11-02", "2026-10-23", "Freya Bank", "Reyes"}
    for d, _, fs in os.walk(os.path.join(ROOT, "builder")):
        for f in fs:
            if f.endswith((".py", ".json", ".md")):
                text = open(os.path.join(d, f)).read()
                hit = sorted(b for b in banned if b in text)
                check(not hit, f"builder/{f} contains public brief values {hit}")
                check(not re.search(r"\b(12th|7th) business day\b", text), f"builder/{f} contains brief A band wording")


if __name__ == "__main__":
    n = 0
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f(); n += 1; print("ok", name)
    print(f"{n} test groups passed")
