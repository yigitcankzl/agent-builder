"""Property tests for builder/engine/dates.py against an independent brute-force oracle.

    python3 tests/test_dates.py
Brief A values appear only in tests/fixtures, never in builder/.
"""
import datetime, json, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import dates as E

D = datetime.date
FIX = json.load(open(os.path.join(ROOT, "tests", "fixtures", "brief_a_date_policy.json")))


# ---- oracle: day-by-day brute force, written without the engine's helpers
def o_bday(d, p): return d.weekday() in p["business_weekdays"] and d.isoformat() not in p["holidays"]

def o_deadline(today, late, p):
    n = next((b for b in p["deadline_bands"] if late <= b["max_days_late"]), p["deadline_bands"][-1])["business_days_after_today"]
    days = [today + datetime.timedelta(days=i) for i in range(1, 400)]
    return [d for d in days if o_bday(d, p)][n - 1]

def o_week_index(today, d):  # 0 = this calendar week (Mon-Sun), 1 = next, ...
    return (d - (today - datetime.timedelta(days=today.weekday()))).days // 7

def o_weekday(today, wd, wk, p):
    cands = [today + datetime.timedelta(days=i) for i in range(-7, 30) if (today + datetime.timedelta(days=i)).weekday() == wd]
    if wk == "next":
        return [d for d in cands if o_week_index(today, d) == 1][0]
    if wk == "after_next":
        return [d for d in cands if o_week_index(today, d) == 2][0]
    return [d for d in cands if d >= today][0]  # bare / this: the coming one, today included

def o_status(today, cand, late, p):
    dl = o_deadline(today, late, p)
    if cand < today: return "past", None
    if cand > dl: return "after_deadline", dl
    if o_bday(cand, p): return "ok", cand
    nxt = [cand + datetime.timedelta(days=i) for i in range(1, 60) if o_bday(cand + datetime.timedelta(days=i), p)][0]
    return ("non_business", nxt) if nxt <= dl else ("after_deadline", dl)


def rand_policy(rng):
    wds = sorted(rng.sample(range(7), rng.randint(3, 6)))
    start = D(2026, 1, 1)
    hol = sorted({(start + datetime.timedelta(days=rng.randint(0, 900))).isoformat() for _ in range(rng.randint(0, 25))})
    b1 = rng.randint(2, 15)
    return {"business_weekdays": wds, "holidays": hol, "next_weekday": "following_week",
            "deadline_bands": [{"max_days_late": b1, "business_days_after_today": rng.randint(1, 15)},
                               {"max_days_late": 999, "business_days_after_today": rng.randint(1, 15)}],
            "say": {}}


def check(cond, msg):
    if not cond: raise AssertionError(msg)


def test_fixture_cases():
    p, now = FIX, D(2026, 10, 14)
    check(E.deadline_for(now, 5, p) == D(2026, 11, 2), "early-band deadline")
    check(E.deadline_for(now, 14, p) == D(2026, 10, 23), "late-band deadline")
    cases = [  # spec, iso, days_late, expected status, expected record
        ("d=26;m=10;wd=mon", "2026-10-26", 5, "non_business", "2026-10-27"),   # PUB-07: holiday -> next business day
        ("d=6;m=11", "2026-11-06", 14, "after_deadline", "2026-10-23"),       # PUB-04: after deadline -> deadline
        ("wd=fri;wk=next", "2026-10-23", 5, "ok", "2026-10-23"),              # next = following calendar week
        ("wd=fri;wk=this", "2026-10-16", 5, "ok", "2026-10-16"),
        ("wd=fri", "", 5, "ok", "2026-10-16"),
        ("rel=tomorrow", "2026-10-15", 5, "ok", "2026-10-15"),
        ("rel=today", "2026-10-14", 5, "ok", "2026-10-14"),
        ("d=30;m=10", "2026-10-30", 4, "ok", "2026-10-30"),                   # PUB-13 card, early band
        ("d=30;m=10", "2026-10-30", 20, "after_deadline", "2026-10-23"),      # PUB-13 loan, late band
        ("d=20;corr=yes", "2026-10-20", 5, "ok", "2026-10-20"),
        ("d=24;m=10", "2026-10-24", 5, "non_business", "2026-10-27"),  # Sat -> Mon 26 holiday -> Tue 27
        ("wk=after_next;vague=yes", "", 5, "vague", ""),
        ("vague=yes", "", 5, "vague", ""),
        ("d=26;m=10;wd=tue", "2026-10-26", 5, "unclear", ""),                 # weekday contradicts the day
        ("d=27;m=10", "2026-10-28", 5, "unclear", ""),                        # iso disagrees with the labels
        ("d=10;m=10", "2026-10-10", 5, "past", ""),
        ("", "2026-10-22", 5, "ok", "2026-10-22"),                            # only iso available
    ]
    for spec, iso, late, st, rec in cases:
        r = E.resolve(now, late, iso, spec, 0, p)
        got = (r["status"], r["record"].isoformat() if r["record"] else "")
        check(got == (st, rec), f"{spec!r} {iso!r} late={late}: got {got}, expected {(st, rec)}")
    check(E.resolve(now, 5, "", "vague=yes", 1, p)["status"] == "vague_final", "second vague answer -> propose deadline")
    check(E.resolve(now, 5, "", "vague=yes", 1, p)["record"] == D(2026, 11, 2), "vague_final records the deadline")
    # a Friday saying "next Friday" means the Friday of the following week (rule: following calendar week)
    check(E.resolve(D(2026, 10, 16), 5, "", "wd=fri;wk=next", 0, p)["named"] == D(2026, 10, 23), "next Friday on a Friday")


def test_random_against_oracle(n=4000, seed=7):
    rng = random.Random(seed)
    for i in range(n):
        p = rand_policy(rng)
        today = D(2026, 1, 1) + datetime.timedelta(days=rng.randint(0, 500))
        late = rng.randint(1, 45)
        check(E.deadline_for(today, late, p) == o_deadline(today, late, p), f"deadline {today} {late} {p}")
        kind = rng.choice(["dm", "d", "wd", "rel"])
        if kind == "dm":
            cand = today + datetime.timedelta(days=rng.randint(-20, 60)); spec = f"d={cand.day};m={cand.month}"
        elif kind == "d":
            cand = today + datetime.timedelta(days=rng.randint(0, 27)); spec = f"d={cand.day}"
        elif kind == "wd":
            wd, wk = rng.randint(0, 6), rng.choice(["this", "next", "after_next", "none"])
            cand = o_weekday(today, wd, wk, p); spec = f"wd={E.WD_KEYS[wd]};wk={wk}"
        else:
            r_ = rng.choice(["today", "tomorrow"]); cand = today + datetime.timedelta(days=0 if r_ == "today" else 1); spec = f"rel={r_}"
        r = E.resolve(today, late, cand.isoformat(), spec, 0, p)
        st, rec = o_status(today, cand, late, p)
        check(r["named"] == cand, f"named {spec} today={today}: {r['named']} != {cand}")
        check((r["status"], r["record"]) == (st, rec), f"{spec} today={today} late={late}: {(r['status'], r['record'])} != {(st, rec)}")
        if rec is not None:  # invariant: anything recordable is a business day inside [today, deadline]
            check(o_bday(rec, p) and today <= rec <= o_deadline(today, late, p), f"record invariant {rec}")


def test_runtime_vars():
    p = FIX
    v = {"now": "2026-10-14T11:00", "days_late": "5", "date_iso": "2026-10-26", "date_spec": "d=26;m=10;wd=mon"}
    E.run_safe(v, p)
    check(v["date_state"] == "new" and v["date_status"] == "non_business" and v["date_record"] == "2026-10-27", v)
    check(v["date_route"] == "say" and "Tuesday 27 October" in v["say_next"] and "Monday 26 October" in v["say_next"], v["say_next"])
    E.run_safe(v, p)
    check(v["date_state"] == "same", "same extraction twice -> same")
    v2 = {"now": "garbage", "date_iso": "x"}
    E.run_safe(v2, p)
    check(v2["date_status"] == "error" and v2["date_route"] == "cont", "never raises")


def test_no_public_values_in_builder():
    """Production code must not carry values from the public briefs (holidays, deadlines, band limits)."""
    banned = set(FIX["holidays"]) | {"2026-10-14", "2026-11-02", "2026-10-23", "2026-10-27"}
    for d, _, fs in os.walk(os.path.join(ROOT, "builder")):
        for f in fs:
            if f.endswith((".py", ".md", ".json")):
                text = open(os.path.join(d, f)).read()
                hit = [b for b in banned if b in text]
                check(not hit, f"{f} contains public brief values {hit}")


def test_code_node_safe():
    src = open(os.path.join(ROOT, "builder", "engine", "dates.py")).read()
    check("{{" not in src and "}}" not in src, "code-node source must not contain double braces")


def test_emitter():
    from builder.engine import date_graph as G
    code = G.code_source(FIX)
    check("{{" not in code and "}}" not in code, "emitted code has double braces")
    v = {"now": "2026-10-14T11:00", "days_late": "5", "date_iso": "2026-10-26", "date_spec": "rel=none;d=26;m=10;wd=mon;wk=none;vague=no;corr=no"}
    exec(compile(code, "date_resolve", "exec"), {"vars": v})  # the snippet runs as the code node would
    check(v["date_status"] == "non_business" and v["date_route"] == "say", v)
    import re
    check(re.match(G.SPEC_PATTERN, v["date_spec"]), "spec pattern accepts the documented format")
    wf = {"initial_node": "talk", "nodes": {"talk": {"name": "talk", "node_type": "conversation", "task_message": "T",
          "transitions": [{"target_node": "end", "description": "x", "condition": {"operator": "always"}}]},
          "end": {"name": "end", "node_type": "end_call"}}}
    G.wire(wf, "talk", FIX)
    n = wf["nodes"]
    check({"talk_date_say", "talk_cont", "date_resolve"} <= set(n), "nodes added")
    check(n["talk"]["transitions"][0]["target_node"] == "date_resolve", "date transition first")
    check(n["talk_date_say"]["on_enter"] == {"type": "tts", "text": "{{say_next}}"}, "say node speaks the code sentence")
    targets = [t["target_node"] for t in n["date_resolve"]["transitions"]]
    check(len(targets) == len(set(targets)), "one transition per target (engine merges duplicates)")
    check(all("{{now}}" in f["extraction_prompt"] for f in n["talk"]["extraction_schema"]), "extraction anchored to now")


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f(); print("ok", name)
