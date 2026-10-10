"""Inspect one simulated call: speaking order, routing on turn 1, hub runs, tool nodes and w_go values.
    python3 tests/inspect_call.py <run_cases --out json> [case_id]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya

r = json.load(open(sys.argv[1]))
row = [x for x in r["rows"] if len(sys.argv) < 3 or x["id"] == sys.argv[2]][0]
c = freya.get_call(row["call_id"])
json.dump(c, open(sys.argv[1].replace(".json", "_call.json"), "w"), indent=1, default=str)
print("call", row["call_id"], "ended", c.get("endedReason"))
last = {}
for m in c.get("messages") or []:
    role = m.get("role")
    vt = {k: x.get("value") for k, x in ((m.get("workflowSnapshot") or {}).get("variableTable") or {}).items()}
    if role in ("user", "assistant", "bot"):
        print(f"{role[:4].upper():4} [{m.get('nodeId')}] {(m.get('message') or '')[:110]!r}")
        diff = {k: vt[k] for k in vt if (k == "route" or k.startswith("w_go_") or k in ("route_ok", "ev_tok", "hub_error")) and last.get(k) != vt[k]}
        if diff:
            print("      vars:", diff)
        last.update(vt)
    elif role == "system":
        try:
            e = json.loads(m.get("message") or "{}")
        except Exception:
            continue
        if e.get("event") in ("route_evaluated",) and "Suppressed" in str(e.get("reason")):
            print("      SUPPRESSED routing:", e.get("reason"))
        if e.get("event") == "node_enter":
            print(f"      -> {e.get('node')}")
        if e.get("event") == "function_call_complete" and e.get("function") not in ("code_exec",):
            print(f"      tool {e.get('function')}: {str(e.get('result'))[:140]}")
