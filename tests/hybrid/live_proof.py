"""LIVE proof of the hybrid gates on hybrid-raw-4 (own slot; only with no simulation running). Two chat calls on
practice session PUB-01 (credit card 420, 6 days late = raw-4 early band: deadline Wed 21 Oct, one attempt; Fri 16 Oct a holiday).

  A "wrong then right": Friday 16 (holiday) -> blocked; 6 November (after the deadline) -> blocked; Monday 19 -> read-back,
    yes -> create_promise passes (ledger: 420 on 2026-10-19).
  B "extra offer": flat no to every offer -> the early band has one attempt: one offer, no second, close refused.

Gate decisions are read from the call's system events (function_call_start/complete of check_terms / next_offer /
confirm / create_promise) and the variable table; the ledger is the mock bank's.

    python3 tests/hybrid/live_proof.py [--only A|B]
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya
from score import http
from builder import smoke

STATE = os.path.join(ROOT, "tests", ".platform-agents.json")
ID = ["Hello?", "Yes, speaking.", "My date of birth is the 14th of March 1988.", "The last four digits are 4471."]
SCRIPTS = {
    "A": ID + ["I can't pay today. I could pay the full 420 on Friday the 16th.",
               "Could I do the 6th of November instead?",
               "Fine, Monday the 19th of October then, the full 420.",
               "Yes, I confirm.",
               "No, that's all, thank you. Bye."],
    "B": ID + ["No, I can't pay that.", "No.", "No, I said no.", "No. Goodbye."],
}


def run(name, wf_id):
    v = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    out, call = {"case": name, "turns": []}, None
    for m in SCRIPTS[name]:
        body = {"workflowId": wf_id, "message": m, "customerVariables": v}
        if call: body["callId"] = call
        t = time.time()
        try:
            r = freya.api("POST", "/api/v2/chat/message", body)
        except Exception as e:      # the closing turn returns 504 (the agent ended the call); never re-sent
            out["turns"].append({"user": m, "error": str(e)[:200], "s": round(time.time() - t, 1)}); print(name, out["turns"][-1]); break
        call = r.get("callId", call)
        out["turns"].append({"user": m, "agent": r.get("response"), "s": round(time.time() - t, 1)}); print(name, out["turns"][-1])
    if call:
        c = freya.get_call(call)
        ev = []
        for x in c.get("messages") or []:
            if x.get("role") == "system":
                try: e = json.loads(x.get("message") or "{}")
                except ValueError: continue
                if e.get("event") in ("function_call_start", "function_call_complete") and e.get("function") != "code_exec":
                    a = e.get("args") or {}
                    ev.append({"node": x.get("nodeId"), "event": e["event"], "function": e.get("function"),
                               "args": a.get("params") or a.get("body") or {k: a[k] for k in a if k not in ("code", "headers")} or None,
                               "url": a.get("url"), "result": json.dumps(e.get("result"))[:240] if e.get("result") else None})
                if e.get("event") == "route_evaluated" and e.get("matched"):
                    ev.append({"node": x.get("nodeId"), "event": "route", "to": e.get("to_node") or e.get("target_node"),
                               "vars": {k: (e.get("variable_table") or {}).get(k) for k in ("gate_status", "gate_say", "gate_ok", "gate_out_date")}})
            elif x.get("role") in ("assistant", "user"):
                ev.append({"node": x.get("nodeId"), "role": x["role"], "text": x.get("message")})
        out["events"] = ev
        out["vars"] = {k: val for k, val in smoke._vars(c).items() if k.startswith("gate_") and k not in ("gate_st", "gate_account")}
        try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception: pass
    out["ledger"] = http(f"/v1/practice/ledger/{v['customer_id']}")
    return out


if __name__ == "__main__":
    sims = smoke.running_sims(freya)
    if sims is None or sims:
        sys.exit(f"STOP: simulation running or unknown ({sims}); nothing sent")
    wf = json.load(open(os.path.join(ROOT, "tests", "hybrid", "hybrid-raw-4.workflow.json")))
    ids = freya.save_workflow("hybrid-raw-4", wf, STATE)
    print("saved", ids)
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    res = {"ids": ids, "runs": [run(n, ids["workflow_id"]) for n in SCRIPTS if not only or n == only]}
    json.dump(res, open(os.path.join(ROOT, "tests", "hybrid", "live_proof.json"), "w"), indent=1, default=str)
    for r in res["runs"]:
        led = r["ledger"]
        print(r["case"], "ledger:", led.get("outcome"), led.get("reason"), led.get("promises"), [c["tool"] for c in led.get("calls") or []])
