"""Phase 1 platform step (lane granted by the coordinator): dry-run, save to slot `ours-brief-a`, 2 chat turns, then
read the call events. No simulation, no re-send on 503/504.   python3 tests/platform_step1.py"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya
from builder import generator
from builder.generator import generate
from builder.validate_workflow import validate

OAS = os.path.join(ROOT, "tools", "openapi.json")
OUT = os.path.join(ROOT, "tests", "platform")
CV = {"customer_id": "c_ours_probe", "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"}
TURNS = ["Yes, this is Daniel Reyes.", "My date of birth is the fourteenth of March 1988."]


def once(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except RuntimeError as e:          # reported, never re-sent
        return None, str(e)[:800]


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    rp = json.load(open(os.path.join(ROOT, "tests", "generated", "brief-a.reducer_policy.json")))
    wf = generate(rp, OAS)
    errs = validate(wf, rp, OAS)
    code = wf["nodes"]["hub"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    rep = {"hub_from": generator.GENERATED_FROM, "hub_kb": round(len(code) / 1024, 1), "workflow_kb": round(len(json.dumps(wf)) / 1024, 1),
           "local_validator": errs}
    print(json.dumps(rep))
    dry, err = once(freya.validate_workflow, "ours-brief-a", wf)
    rep["dry_run"] = dry or err
    print("dry run:", rep["dry_run"])
    if not (dry and dry.get("valid")):
        json.dump(rep, open(os.path.join(OUT, "step1.json"), "w"), indent=1)
        sys.exit(1)
    ids, err = once(freya.save_workflow, "ours-brief-a", wf, os.path.join(ROOT, "tests", ".platform-agents.json"))
    rep["save"] = ids or err
    print("save:", rep["save"])
    if not ids:
        json.dump(rep, open(os.path.join(OUT, "step1.json"), "w"), indent=1)
        sys.exit(1)
    call, said = None, []
    for msg in TURNS:
        body = {"workflowId": ids["workflow_id"], "message": msg, "customerVariables": CV}
        if call:
            body["callId"] = call
        r, err = once(freya.api, "POST", "/api/v2/chat/message", body)
        if err:
            said.append({"user": msg, "error": err})
            break
        call = r.get("callId", call)
        said.append({"user": msg, "agent": r.get("response")})
        print("USER:", msg, "\nAGENT:", r.get("response"))
    if call:
        once(freya.api, "POST", "/api/v2/chat/end", {"callId": call})
        time.sleep(3)
        c, err = once(freya.get_call, call)
        rep["call_id"] = call
        if c:
            json.dump(c, open(os.path.join(OUT, "step1_call.json"), "w"), indent=1, default=str)
            ev = []
            for m in c.get("messages") or []:
                if m.get("role") == "system":
                    try:
                        e = json.loads(m.get("message") or "{}")
                    except Exception:
                        continue
                    if e.get("event") in ("function_call_complete", "function_call_start", "node_enter", "route_evaluated", "variable_extracted", "error"):
                        ev.append({k: (str(v)[:160] if k in ("result", "args", "reason") else v) for k, v in e.items() if k in ("event", "function", "node", "from_node", "target", "result", "name", "value", "reason")} | {"node_id": m.get("nodeId")})
            rep["events"] = ev
            vt = {}
            for m in c.get("messages") or []:
                vt.update({k: x.get("value") for k, x in ((m.get("workflowSnapshot") or {}).get("variableTable") or {}).items()})
            rep["vars"] = {k: (str(v)[:120] if v is not None else None) for k, v in vt.items()
                           if k in ("route", "say_next", "route_ok", "ev", "ev_tok", "close_outcome", "close_reason", "farewell", "talk_hint", "hub_error")
                           or k.startswith("w_go_") or k.startswith("w_verify")}
            rep["st_present"] = "st" in vt
        else:
            rep["get_call_error"] = err
    rep["turns"] = said
    json.dump(rep, open(os.path.join(OUT, "step1.json"), "w"), indent=1, default=str)
    print(json.dumps({k: rep.get(k) for k in ("vars", "st_present", "call_id")}, indent=1))
