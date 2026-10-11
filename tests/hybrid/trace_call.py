"""Print a hybrid call compactly (turns, gate/tool calls, extractions, routes). Read-only platform call.

    python3 tests/hybrid/trace_call.py <call_id> [--save path]
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya

SKIP = ("code_exec",)


def show(c):
    for x in c.get("messages") or []:
        node = x.get("nodeId")
        if x.get("role") == "system":
            try:
                e = json.loads(x.get("message") or "{}")
            except ValueError:
                continue
            ev = e.get("event")
            if ev == "function_call_start" and e.get("function") not in SKIP:
                a = e.get("args") or {}
                print("   ", node, "CALL", e["function"], json.dumps(a.get("params") or a.get("body"))[:170])
            elif ev == "function_call_complete" and e.get("function") not in SKIP + ("check_terms", "next_offer", "confirm"):
                print("   ", node, "DONE", e["function"], json.dumps(e.get("result"))[:220])
            elif ev == "variable_extracted":
                print("   ", node, "EXTRACT", e.get("name"), e.get("value"))
            elif ev == "route_evaluated" and e.get("matched"):
                vt = e.get("variable_table") or {}
                g = lambda k: (vt.get(k) or {}).get("value") if isinstance(vt.get(k), dict) else vt.get(k)
                print("   ", node, "ROUTE gate", g("gate_status"), g("gate_ok"))
        else:
            print("   ", node, x.get("role"), str(x.get("message"))[:200])


if __name__ == "__main__":
    c = freya.get_call(sys.argv[1])
    if "--save" in sys.argv:
        json.dump(c, open(sys.argv[sys.argv.index("--save") + 1], "w"), indent=1, default=str)
    show(c)
