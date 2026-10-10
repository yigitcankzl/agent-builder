"""LIVE smoke check (only in a granted window, no simulation running). Own slots only (smoke-main, smoke-bogus).

1. the integration build's brief-A workflow -> slot smoke-main -> smoke.run must pass (engine runs in chat);
2. the same workflow with "{{bogus}}" in the spoken say node -> slot smoke-bogus -> smoke.run must fail with S7;
3. the same with "{{bogus}}" in the greet -> static check must fail with S7 (no chat turn).
Variables come from a practice session (PUB-01) of the mock bank.

    python3 tests/smoke_live.py [workflow.json]
"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya
from score import http
from builder import smoke

STATE = os.path.join(ROOT, "tests", ".platform-agents.json")
CALL_VARS = ["customer_id", "first_name", "last_name", "title", "now"]

if __name__ == "__main__":
    wf = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "fallback", "runs", "none", "brief-a.workflow.json")))
    wf = wf.get("workflow", wf)
    sims = smoke.running_sims(freya)
    if sims is None or sims:
        sys.exit(f"STOP: simulation running or unknown ({sims}); nothing sent")
    out = {}
    v = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    print("dry run:", freya.validate_workflow("smoke-main", wf))
    ids = freya.save_workflow("smoke-main", wf, STATE)
    out["main"] = smoke.run(freya.api, freya.get_call, ids["workflow_id"], wf, call_vars=CALL_VARS, variables=v)
    print("main:", json.dumps(out["main"], indent=1))
    bad = copy.deepcopy(wf)
    say = next(k for k, n in bad["nodes"].items() if (n.get("on_enter") or {}).get("text") == "{{say_next}}")
    bad["nodes"][say]["on_enter"]["text"] = "{{say_next}} {{bogus}}"
    ids2 = freya.save_workflow("smoke-bogus", bad, STATE)
    v2 = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    out["bogus_say"] = smoke.run(freya.api, freya.get_call, ids2["workflow_id"], bad, call_vars=CALL_VARS, variables=v2)
    print("bogus in say:", json.dumps(out["bogus_say"], indent=1))
    g = copy.deepcopy(wf)
    g["nodes"][g["initial_node"]]["on_enter"]["text"] = "Hello {{bogus}}. " + g["nodes"][g["initial_node"]]["on_enter"]["text"]
    out["bogus_greet"] = smoke.run(None, None, "-", g, call_vars=CALL_VARS)
    print("bogus in greet:", json.dumps(out["bogus_greet"]))
    ok = out["main"]["ok"] and not out["main"]["skipped"] and out["bogus_say"]["signal"] == "S7" and out["bogus_greet"]["signal"] == "S7"
    json.dump(out, open(os.path.join(ROOT, "tests", "smoke", "live_result.json"), "w"), indent=1)
    print("LIVE SMOKE", "PASS" if ok else "FAIL")
