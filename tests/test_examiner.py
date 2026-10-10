"""The independent examiner (builder/examiner.py), offline: the two Claude calls are replaced by canned answers.

    python3 tests/test_examiner.py
A planted misread (the extraction's late band says 9 days, the brief says 7) is found as a disagreement, re-checked
once, and patched only when the re-check quote is verbatim; 'ours' keeps ours; an unverifiable re-check stays an
examiner_disagree warning; equal answers give no disagreement. The live runs (real calls) are tests/examiner_live.py.
"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import examiner as E

BRIEF = [os.path.join(ROOT, "briefs", "brief-a.md")]
POL = json.load(open(os.path.join(ROOT, "tests", "e2e-int", "submission", "brief-a.extracted.json")))
Q_LATE = "| 8 to 45 | late | the 7th business day after today | 2 |"
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def answers(late_days=7):
    bands = copy.deepcopy(E.ours(POL, "bands"))
    for b in bands:
        if b["name"] == "late":
            b["days"] = late_days
    src = [{"file": "brief-a.md", "quote": Q_LATE}]
    return {"bands": {"value": bands, "source": src},
            "holidays": {"value": E.ours(POL, "holidays"), "source": [{"file": "brief-a.md", "quote": "2026-10-26"}]},
            "identity": {"value": E.ours(POL, "identity"), "source": [{"file": "brief-a.md", "quote": "After three wrong answers"}]}}


if __name__ == "__main__":
    check(not E.disagreements(POL, answers()), "the real extraction agrees with a faithful examiner")
    planted = copy.deepcopy(POL)
    for b in planted["deadline"]["bands"]:
        if b["name"] == "late":
            b["days"] = 9                      # the planted misread
    dis = E.disagreements(planted, answers())
    check(len(dis) == 1 and dis[0]["qid"] == "bands", f"the planted misread is caught: {[d['qid'] for d in dis]}")
    logs = []
    log = lambda ev, **kw: logs.append((ev, kw))
    real = E.recheck
    try:
        E.recheck = lambda *a, **k: {"bands": {"qid": "bands", "winner": "theirs", "verified": True,
                                                        "source": {"file": "brief-a.md", "quote": Q_LATE}, "why": "table row"}}
        fixed, rep = E.reconcile(planted, BRIEF, None, answers(), log=log)
        late = [b for b in fixed["deadline"]["bands"] if b["name"] == "late"][0]
        check(late["days"] == 7 and rep["patched"] == ["bands"] and any(e == "examiner_patch" for e, _ in logs),
              f"re-check 'theirs' with a verbatim quote patches the band: {rep}")
        E.recheck = lambda *a, **k: {"bands": {"qid": "bands", "winner": "ours", "verified": True}}
        same, rep2 = E.reconcile(planted, BRIEF, None, answers(), log=log)
        check(rep2["kept_ours"] == ["bands"] and [b["days"] for b in same["deadline"]["bands"] if b["name"] == "late"] == [9],
              "re-check 'ours' keeps ours")
        logs.clear()
        E.recheck = lambda *a, **k: {"bands": {"qid": "bands", "winner": "theirs", "verified": False}}
        kept, rep3 = E.reconcile(planted, BRIEF, None, answers(), log=log)
        check(rep3["unresolved"] == ["bands"] and any(e == "examiner_disagree" for e, _ in logs)
              and [b["days"] for b in kept["deadline"]["bands"] if b["name"] == "late"] == [9],
              "an unverifiable re-check -> examiner_disagree, the quote-verified extraction is kept")
    finally:
        E.recheck = real
    # build: the examiner runs in parallel and its patch reaches the bridged policy
    from builder.build import MockFreya, build
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        def ex(briefs, openapi, tp, rep_, sink, deadline):
            return copy.deepcopy(planted), json.load(open(os.path.join(ROOT, "tests", "policy_eval", "v3", "run4", "brief-a.report.json")))
        E.recheck = lambda *a, **k: {"bands": {"qid": "bands", "winner": "theirs", "verified": True,
                                                        "source": {"file": "brief-a.md", "quote": Q_LATE}}}
        r = build(BRIEF, os.path.join(ROOT, "tools", "openapi.json"), "exam", MockFreya(), os.path.join(tmp, "sub"),
                  os.path.join(tmp, "tr"), 2, 1500, ex, examiner=lambda b, o, sink, dl: answers())
        rp = json.load(open(os.path.join(tmp, "sub", "exam.policy.json")))
        check(r["exit_code"] == 0 and r["examiner"]["patched"] == ["bands"]
              and [b["days"] for b in rp["deadline"]["bands"] if b["name"] == "late"] == [7], f"build: examiner patch reaches the policy {r.get('examiner')}")
    finally:
        E.recheck = real
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
