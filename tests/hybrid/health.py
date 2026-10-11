"""One single-turn chat on the tiny hybrid-probe2 workflow every 10 min until chat answers (max 2 h). Allowed during
a simulation (coordinator, 2026-10-11). Prints one line per check; exit 0 when healthy.

    python3 tests/hybrid/health.py
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya

wid = json.load(open(os.path.join(ROOT, "tests", ".platform-agents.json")))["hybrid-probe2"]["workflow_id"]
for i in range(12):
    t = time.time()
    try:
        r = freya.api("POST", "/api/v2/chat/message", {"workflowId": wid, "message": "Hello?", "customerVariables": {}})
        print(time.strftime("%H:%M"), "HEALTHY", round(time.time() - t, 1), "s", flush=True)
        try: freya.api("POST", "/api/v2/chat/end", {"callId": r["callId"]})
        except Exception: pass
        sys.exit(0)
    except Exception as e:
        print(time.strftime("%H:%M"), "down", round(time.time() - t, 1), "s", str(e)[:80], flush=True)
    time.sleep(600)
sys.exit(1)
