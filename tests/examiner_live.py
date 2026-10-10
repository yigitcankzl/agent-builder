"""Live examiner runs (real Claude calls, no Freya): A, A+B, raw-a, raw-b, mut-03 against their saved extractions, and a
planted misread on A (late band days 7 -> 9) that must be caught and fixed by the re-check.

    python3 tests/examiner_live.py      # writes tests/examiner_live.json
"""
import concurrent.futures as cf, copy, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import examiner as E

G, FX, SUB = os.path.join(ROOT, "tests", "fixtures", "general"), os.path.join(ROOT, "tests", "fixtures", "briefs"), os.path.join(ROOT, "tests", "e2e-int", "submission")
OAS = os.path.join(ROOT, "tools", "openapi.json")
RUNS = {"brief-a": [os.path.join(ROOT, "briefs", "brief-a.md")],
        "brief-ab": [os.path.join(ROOT, "briefs", "brief-a.md"), os.path.join(ROOT, "briefs", "brief-b.md")],
        "raw-a": [os.path.join(FX, "raw-a")],
        "raw-b": [os.path.join(G, "raw-b", f) for f in ("email-from-dialler-ops.eml", "policy-extract.md", "memo-2026-10-08.md", "codes.csv")],
        "mut-03": [os.path.join(FX, "mut-03.md")]}


def policy(slot):
    f = os.path.join(SUB, slot + ".extracted.json")
    return json.load(open(f)) if os.path.exists(f) else json.load(open(os.path.join(ROOT, "tests", "policy_eval", "v3", "run5", slot + ".json")))


def one(slot):
    try:
        return _one(slot)
    except Exception as e:
        return {"slot": slot, "seconds": None, "answered": [], "disagreements": [], "error": f"{type(e).__name__}: {e}"[:300]}


def _one(slot):
    t0 = time.time()
    ans = E.examine(RUNS[slot], OAS)
    pol = policy(slot)
    out = {"slot": slot, "seconds": round(time.time() - t0, 1), "answered": sorted(ans),
           "disagreements": [{k: d[k] for k in ("qid", "ours", "theirs")} for d in E.disagreements(pol, ans)]}
    if slot == "brief-a":
        planted = copy.deepcopy(pol)
        for b in planted["deadline"]["bands"]:
            if b["name"] == "late":
                b["days"] = 9
        logs = []
        fixed, rep = E.reconcile(planted, RUNS[slot], OAS, ans, log=lambda ev, **kw: logs.append({"event": ev, **kw}))
        out["planted"] = {"report": rep, "late_days_after": [b["days"] for b in fixed["deadline"]["bands"] if b["name"] == "late"],
                          "log": logs}
    return out


if __name__ == "__main__":
    with cf.ThreadPoolExecutor(len(RUNS)) as ex:
        res = list(ex.map(one, RUNS))
    for r in res:
        print(f"{r['slot']:9} {r['seconds']!s:6} s {r.get('error') or ''}  answered {len(r['answered'])}/{len(E.QUESTIONS)}  disagreements: {[d['qid'] for d in r['disagreements']]}")
        for d in r["disagreements"]:
            print("      ", d["qid"], "| ours:", json.dumps(d["ours"], default=str)[:150], "| theirs:", json.dumps(d["theirs"], default=str)[:150])
        if "planted" in r:
            print("   planted late band 7->9:", r["planted"]["report"], "late days after:", r["planted"]["late_days_after"])
    json.dump(res, open(os.path.join(ROOT, "tests", "examiner_live.json"), "w"), indent=1, default=str)
