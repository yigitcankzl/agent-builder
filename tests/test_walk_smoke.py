"""The build's generic graph-walk smoke (selftest.walk_smoke) on built workflows, plus planted wiring bugs.

    WALK_DIR=tests/e2e-hon/submission python3 tests/test_walk_smoke.py
"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.selftest import walk_smoke

WD = os.path.join(ROOT, os.environ.get("WALK_DIR", "tests/e2e-hon/submission"))
OAS = os.path.join(ROOT, "tools", "openapi.json")
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


if __name__ == "__main__":
    for slot in sorted(f[:-len(".policy.json")] for f in os.listdir(WD) if f.endswith(".policy.json")):
        rp = json.load(open(os.path.join(WD, slot + ".policy.json")))
        wf = json.load(open(os.path.join(WD, slot + ".workflow.json")))
        wf = wf.get("workflow", wf)
        oas = os.path.join(ROOT, "tests", "fixtures", "general", slot, "openapi.json")
        oas = oas if os.path.exists(oas) else OAS
        r = walk_smoke(rp, wf, oas)
        check(r.get("run") and not r["errors"] and "close_call" in r["calls"], f"{slot}: walk clean, calls {r.get('calls')} {r.get('errors')}")
    # planted wiring bugs on the first workflow are caught
    slot = sorted(f[:-len(".policy.json")] for f in os.listdir(WD) if f.endswith(".policy.json"))[0]
    rp = json.load(open(os.path.join(WD, slot + ".policy.json")))
    wf0 = json.load(open(os.path.join(WD, slot + ".workflow.json")))
    wf0 = wf0.get("workflow", wf0)
    w = copy.deepcopy(wf0)
    w["nodes"]["greet"]["on_enter"]["text"] += " {{lastname}}"
    check(walk_smoke(rp, w, OAS)["errors"], "unresolved greet placeholder caught")
    w = copy.deepcopy(wf0)
    w["nodes"]["hub"]["transitions"] = [t for t in w["nodes"]["hub"]["transitions"] if t["target_node"] != "close_say"]
    check(walk_smoke(rp, w, OAS)["errors"], "hub edge to close_say removed caught")
    # the hub's last edges, freshly generated: say, the hub-failed close, one route_ok talk_post edge, then talk_pre
    from builder.generator import generate
    hub = generate(rp, OAS)["nodes"]["hub"]["transitions"]
    tg = [t["target_node"] for t in hub]
    check(tg[-4:] == ["exact_say", "close_say", "talk_post", "talk_pre"] and tg.count("talk_post") == 1
          and hub[-2]["condition"]["conditions"][0] == {"variable": "route_ok", "operator": "equals", "operand": "yes"},
          f"hub last edges: an unmatched route after verification goes to talk_post, never talk_pre ({tg[-4:]})")
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
