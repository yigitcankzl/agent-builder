"""Run the two independent date fixtures through the SAME code string the workflow carries (tests/test_dates.run).

    python3 tests/test_independent.py
- Cursor:       tests/fixtures/independent/cursor_date_cases.json  (black-box oracle from the briefs; spec alongside)
- other Claude: tests/fixtures/independent/claude_date_cases.json (transcribed from branch date-engine)
Adapter only: it maps each fixture's input to the two extraction fields and the engine's output to the fixture's
vocabulary. Multi-product cases run the engine once per product (per-product state belongs to the next milestone).
"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.test_dates import FIX, labels, run

IND = os.path.join(ROOT, "tests", "fixtures", "independent")
WD = {"monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun"}
ACTION = {"ok": "accept", "non_business_day": "offer_next_business_day", "after_deadline": "offer_deadline",
          "vague": "ask_exact", "vague_final": "propose_deadline"}


def cursor_policy(c):
    p = copy.deepcopy(FIX)
    p["business_days"]["holidays"] = c["policy"]["holidays"]
    p["deadline"]["bands"] = [{"name": b["id"], "max_days_late": b["days_late_max"], "days": b["deadline_business_days_after_today"]}
                              for b in c["policy"]["bands"]]
    return p


def fields(ex):
    k = ex["kind"]
    if k in ("absolute", "confirm_repeat"):
        return ex["date"], labels(ex["date"])
    if k == "relative_weekday":
        return "", labels(wd=WD[ex["relative"]["weekday"]], wk=ex["relative"]["which"])
    if k == "vague":
        return "", labels(wk="next" if ex["vague"] == "next_week" else "none", vague="yes")
    return "", ""


def run_cursor():
    cases = json.load(open(os.path.join(IND, "cursor_date_cases.json")))["cases"]
    res = []
    for c in cases:
        p, st, ex = cursor_policy(c), c["current_state"], c["extraction"]
        for pid, exp in c["expected"]["products"].items():
            prior = (st.get("dates") or {}).get(pid)
            v = {"now": st["now"], "products": json.dumps(st["products"]), "current_product_id": pid}
            if prior:  # what the earlier turn left behind: sticky fields, handled signature, accepted date
                v.update(date_iso=prior, date_spec=labels(prior), date_handled=prior + "|" + labels(prior), accepted_date=prior)
            if st.get("vague_ask_used"):
                v["date_vague_count"] = "1"
            in_scope = ex["scope"] == "all" or ex.get("product_id") == pid
            if ex["mentioned_this_turn"] and in_scope:
                v["date_iso"], v["date_spec"] = fields(ex)
            run(p, v)
            if v["date_state"] == "same":
                got = ("keep" if ex["kind"] == "confirm_repeat" else "unchanged", v.get("accepted_date") or prior, None)
            else:
                act = ACTION.get(v.get("date_reason"), v.get("date_reason"))
                acc = v.get("accepted_date") or None
                got = (act, acc if act == "accept" else None, acc if act != "accept" else None)
            want = (exp["action"], exp.get("date"), exp.get("offered_date"))
            dl_ok = v.get("date_deadline") in (None, c["expected"]["deadlines"].get(pid))
            res.append((c["id"], pid, want, got, dl_ok, c["expected"].get("ambiguous", False)))
    return res


def run_claude():
    d = json.load(open(os.path.join(IND, "claude_date_cases.json")))
    m = {"non_business": "non_business_day", "unclear": "invalid", "past": "before_earliest"}
    res = []
    for spec, iso, late, st, rec, vc in d["cases"]:
        full = labels(**{k: v for k, v in (x.split("=") for x in spec.split(";") if x)}) if spec else ""
        v = run(FIX, {"now": d["now"], "products": json.dumps([{"product_id": "p1", "days_late": late}]),
                      "current_product_id": "p1", "date_iso": iso, "date_spec": full, "date_vague_count": str(vc)})
        res.append((f"{spec or '-'} | {iso or '-'}", "p1", (m.get(st, st), rec), (v.get("date_reason"), v.get("accepted_date", "")), True, False))
    for e in d["extra"]:
        full = labels(**{k: v for k, v in (x.split("=") for x in e["spec"].split(";") if x)})
        v = run(FIX, {"now": e["now"], "days_late": str(e["days_late"]), "date_iso": e["iso"], "date_spec": full})
        res.append((e["note"], "p1", ("ok", e["named"]), (v.get("date_reason"), v.get("accepted_date")), True, False))
    return res


def report(name, res):
    bad = [r for r in res if (r[2] != r[3] or not r[4]) and not r[5]]
    amb = [r for r in res if r[5]]
    print(f"{name}: {len(res) - len(bad) - len(amb)}/{len(res) - len(amb)} pass" + (f", {len(amb)} ambiguous (no oracle verdict)" if amb else ""))
    for r in bad:
        print("   FAIL", r[0], r[1], "expected", r[2], "got", r[3], "" if r[4] else "(deadline differs)")
    for r in amb:
        print("   AMBIGUOUS", r[0], r[1], "engine:", r[3])
    return bad


if __name__ == "__main__":
    bad = report("cursor", run_cursor()) + report("claude", run_claude())
    sys.exit(1 if bad else 0)
