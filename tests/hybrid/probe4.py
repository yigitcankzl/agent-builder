"""LIVE probe 4 (own slot hybrid-probe4; only with no simulation running): do api_call hooks persist vars?

Q1 a var written by pre_process_code / post_process_code: visible to a later code tool and to the next hook?
Q2 does vars.pop() in a hook / code tool remove the variable for later runs?
Q3 which auto vars does the platform write after a model-called api_call (create_promise_args.*, *_response.data.ok)?

Turns: promise -> peek -> promise -> peek. create_promise goes to the mock without verified identity, so the bank
answers ok:false (a definite failure) and nothing is recorded.

    python3 tests/hybrid/probe4.py     # writes tests/hybrid/probe4_result.json
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya
from score import http
from builder import smoke

MOCK = "https://freya-bank-mock.freyavoice.workers.dev/v1/"
PRE = ("vars['hk_pre'] = str(int(vars.get('hk_pre') or 0) + 1)\n"
       "vars['hk_seen_post'] = str(vars.get('hk_post'))\n"
       "vars['hk_seen_args'] = str(vars.get('create_promise_args.product_id')) + '|' + str(vars.get('create_promise_response.data.ok'))\n"
       "vars.pop('hk_doomed', None)\n")
POST = ("vars['hk_post'] = str(int(vars.get('hk_post') or 0) + 1)\n"
        "d = result.get('data') if isinstance(result, dict) else None\n"
        "vars['hk_post_ok'] = str(d.get('ok')) if isinstance(d, dict) else 'none'\n")
PEEK = ("vars['peek'] = ';'.join(k + '=' + str(vars.get(k))[:40] for k in sorted(vars) if k.startswith('hk_') or k.startswith('create_promise'))\n")


def workflow():
    body = {"customer_id": {"type": "string", "default": "{{customer_id}}"}, "product_id": {"type": "string", "default": "{{product_id}}"},
            "amount": {"type": "number", "default": "{{amount}}"}, "date": {"type": "string", "default": "{{date}}"}}
    cp = {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0},
          "function": {"name": "create_promise", "handler": "__function__:api_call",
                       "description": "Call it when the user says 'promise' with product p1, amount 420, date 2026-10-19.",
                       "parameters": {"type": "object", "properties": {
                           "url": {"type": "string", "default": MOCK + "create_promise"}, "method": {"type": "string", "default": "POST"},
                           "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                           "body": {"type": "object", "properties": body, "required": list(body)}}}},
          "pre_process_code": PRE, "post_process_code": POST}
    seed = {"type": "function", "config": {"timeoutMs": 10000},
            "function": {"name": "seed", "handler": "__function__:code_exec", "description": "Call it when the user says 'seed'.",
                         "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": "vars['hk_doomed'] = 'x'\n"},
                                                                         "timeout_ms": {"type": "number", "default": 5000}}}}}
    peek = {"type": "function", "config": {"timeoutMs": 10000},
            "function": {"name": "peek", "handler": "__function__:code_exec", "description": "Call it when the user says 'peek'.",
                         "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": PEEK},
                                                                         "timeout_ms": {"type": "number", "default": 5000}}}}}
    return {"initial_node": "talk", "system_prompt": "You are a test agent. Short replies.", "test_variables": {"customer_id": "c_test"},
            "nodes": {"talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Ready."},
                               "on_enter_first_entry_only": True, "max_node_turns": 20,
                               "task_message": "When the user says 'promise', call create_promise (p1, 420, 2026-10-19) and say only OK. "
                                               "When the user says 'peek', call peek and say OK. When the user says 'seed', call seed and say OK.",
                               "tools": [cp, peek, seed], "transitions": []}}, "tools": []}


if __name__ == "__main__":
    sims = smoke.running_sims(freya)
    if sims is None or sims:
        sys.exit(f"STOP: simulation running or unknown ({sims}); nothing sent")
    ids = freya.save_workflow("hybrid-probe4", workflow(), os.path.join(ROOT, "tests", ".platform-agents.json"))
    v = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    call, out = None, {"turns": []}
    for m in ["Hello?", "seed", "promise", "peek", "promise", "peek"]:
        body = {"workflowId": ids["workflow_id"], "message": m, "customerVariables": v}
        if call: body["callId"] = call
        r = freya.api("POST", "/api/v2/chat/message", body)
        call = r.get("callId", call)
        out["turns"].append({"user": m, "agent": r.get("response")})
    c = freya.get_call(call)
    out["peeks"], out["errors"] = [], []
    for x in c.get("messages") or []:
        if x.get("role") == "system":
            e = json.loads(x.get("message") or "{}")
            vt = e.get("variable_table") or {}
            if "peek" in vt:
                p = vt["peek"].get("value") if isinstance(vt["peek"], dict) else vt["peek"]
                if p not in out["peeks"]:
                    out["peeks"].append(p)
            if e.get("event") == "function_call_error":
                out["errors"].append(str(e.get("error"))[:200])
    try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
    except Exception: pass
    json.dump(out, open(os.path.join(ROOT, "tests", "hybrid", "probe4_result.json"), "w"), indent=1)
    for p in out["peeks"]:
        print("PEEK", p)
    print("errors", out["errors"])
