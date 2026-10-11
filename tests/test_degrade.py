"""L2 degraded build (builder/degrade.py) through build(), offline.

    python3 tests/test_degrade.py
1. A mandatory schedule_callback cannot be stripped; an unused callback tool can be stripped as a last resort.
2. The same on create_promise (core) -> no L2: exit 2, S5, next L3.
3. schedule_callback's response without an `ok` field (FINAL-PLAN exit check) -> the build still passes.
"""
import copy, json, os, shutil, sys, tempfile
from unittest.mock import patch
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.build import MockFreya, build
from builder.degrade import degrade

OAS = os.path.join(ROOT, "tools", "openapi.json")
POLICY = json.load(open(os.path.join(ROOT, "tests", "e2e-int", "submission", "brief-a.extracted.json")))
REPORT = json.load(open(os.path.join(ROOT, "tests", "policy_eval", "v3", "run4", "brief-a.report.json")))
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def variant(path, tool, how):
    d = json.load(open(OAS))
    for p, ops in d["paths"].items():
        if p.endswith(tool):
            for op in ops.values():
                if how == "required":
                    s = op["requestBody"]["content"]["application/json"]["schema"]
                    s["properties"]["channel"] = {"type": "string", "description": "the contact channel"}
                    s["required"] = list(s.get("required") or []) + ["channel"]
                else:
                    rs = op["responses"]
                    rs[next(c for c in rs if str(c).startswith("2"))]["content"]["application/json"]["schema"]["properties"].pop("ok", None)
    json.dump(d, open(path, "w"), indent=1)
    return path


def run(oas, slot, tmp, optional=False):
    pol = copy.deepcopy(POLICY)
    if optional:
        pol["writes"].pop("callback")
        pol["events"], pol["opening_situations"] = [], {}
    ex = lambda b, o, tp, r_, sink, dl: (copy.deepcopy(pol), REPORT)
    with patch("builder.build.reextract_fields", return_value={}):
        return build([os.path.join(ROOT, "briefs", "brief-a.md")], oas, slot, MockFreya(), os.path.join(tmp, "sub-" + slot),
                     os.path.join(tmp, "tr"), 2, 1500, ex)


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    try:
        r = run(variant(os.path.join(tmp, "cb.json"), "schedule_callback", "required"), "l2", tmp)
        check(r["exit_code"] == 2 and r.get("next") == "L3" and not r.get("degraded") and not r.get("export"),
              "mandatory callback broken -> L3, never stripped")
        r = run(variant(os.path.join(tmp, "optional.json"), "schedule_callback", "required"), "l2optional", tmp, optional=True)
        wf = json.load(open(r["export"]))["workflow"] if r.get("export") else {}
        check(r["exit_code"] == 0 and r.get("partial") and any("schedule_callback" in x for x in r.get("degraded") or [])
              and "t_schedule_callback" not in wf.get("nodes", {}), f"unused optional tool broken -> last-resort partial, saved: {r.get('degraded')}")
        ev = [json.loads(l) for l in open(r["trace"])]
        check(any(e["event"] == "degraded_build" and e["passed"] for e in ev), "degraded_build in the trace")
        check(any(e["event"] == "partial_agent" and e["last_resort"] for e in ev), "partial agent explicitly traced")
        r2 = run(variant(os.path.join(tmp, "cp.json"), "create_promise", "required"), "l2core", tmp)
        check(r2["exit_code"] == 2 and r2["signal"] == "S5" and r2["next"] == "L3" and not r2.get("degraded"),
              f"core tool broken -> no L2, S5 next L3 ({r2.get('fallback_reason')})")
        r3 = run(variant(os.path.join(tmp, "nook.json"), "schedule_callback", "no_ok"), "nook", tmp)
        check(r3["exit_code"] == 0, f"schedule_callback response without ok -> builds ({r3.get('fallback_reason')}, degraded={r3.get('degraded')})")
        rp, info = degrade({"hooks": [{"id": "h"}]}, ["17: hook h point 'x' is not one of ..."])
        check(rp is not None and rp["hooks"] == [] and info, "hook errors -> hooks stripped")
        rp, core = degrade({}, ["2: identity can be bypassed: greet reaches t_get_account"])
        check(rp is None and core, "a core error -> no L2")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
