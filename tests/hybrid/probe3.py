"""LIVE probe 3 (own slot hybrid-probe3; only with no simulation running): does an api_call hook stop working once a
code tool has written a var whose name starts with "_" (v6 PUB-06 8c4f0608)?

Turns: account (hook should run) -> mark (code tool writes _x) -> account (hook?) .
The hook adds result['hooked'] = 'yes'; a broken hook shows function_call_error "Sandbox did not return a parseable result".

    python3 tests/hybrid/probe3.py
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


def workflow():
    acct = {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0},
            "function": {"name": "get_account", "handler": "__function__:api_call", "description": "Call it when the user says 'account'.",
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": MOCK + "get_account"}, "method": {"type": "string", "default": "POST"},
                             "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                             "body": {"type": "object", "properties": {"customer_id": {"type": "string", "default": "{{customer_id}}"}},
                                      "required": ["customer_id"]}}}},
            "post_process_code": "try:\n    result['hooked'] = 'yes'\nexcept Exception:\n    pass\n"}
    mark = {"type": "function", "config": {"timeoutMs": 10000},
            "function": {"name": "mark", "handler": "__function__:code_exec", "description": "Call it when the user says 'mark'.",
                         "parameters": {"type": "object", "properties": {
                             "code": {"type": "string", "default": "vars['_x'] = 'a'\nvars['_y'] = ''\n"},
                             "timeout_ms": {"type": "number", "default": 5000}}}}}
    return {"initial_node": "talk", "system_prompt": "You are a test agent. Short replies.", "test_variables": {"customer_id": "c_test"},
            "nodes": {"talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Ready."},
                               "on_enter_first_entry_only": True, "max_node_turns": 20,
                               "task_message": "When the user says 'account', call get_account and repeat word for word what it returned. "
                                               "When the user says 'mark', call mark, then say OK.",
                               "tools": [acct, mark], "transitions": []}}, "tools": []}


if __name__ == "__main__":
    sims = smoke.running_sims(freya)
    if sims is None or sims:
        sys.exit(f"STOP: simulation running or unknown ({sims}); nothing sent")
    ids = freya.save_workflow("hybrid-probe3", workflow(), os.path.join(ROOT, "tests", ".platform-agents.json"))
    v = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    call = None
    for m in ["Hello?", "account", "mark", "account"]:
        body = {"workflowId": ids["workflow_id"], "message": m, "customerVariables": v}
        if call: body["callId"] = call
        r = freya.api("POST", "/api/v2/chat/message", body)
        call = r.get("callId", call)
        print(m, "->", str(r.get("response"))[:160])
    c = freya.get_call(call)
    for x in c.get("messages") or []:
        if x.get("role") == "system":
            e = json.loads(x.get("message") or "{}")
            if e.get("event") in ("function_call_complete", "function_call_error") and e.get("function") in ("get_account", "mark"):
                print(e["event"], e.get("function"), ("hooked" in json.dumps(e)), str(e.get("error") or "")[:90])
    try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
    except Exception: pass
