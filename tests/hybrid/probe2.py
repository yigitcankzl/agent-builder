"""LIVE probe 2 (own slot hybrid-probe2, no simulation running): where does a model-called code_exec tool find the
arguments of the CURRENT call? (vars['<tool>_args.<name>'] holds the previous call's: written after the code ran.)

    python3 tests/hybrid/probe2.py     # writes tests/hybrid/probe2_result.json
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import freya
from score import http
from builder import smoke

DUMP = """import json
try:
    g = globals()
    keys = sorted(k for k in g.keys() if not k.startswith('__'))
    small = dict()
    for k in keys:
        v = g.get(k)
        if isinstance(v, (str, int, float, dict, list)) and k != 'vars':
            small[k] = str(v)[:200]
    vk = sorted(k for k in vars.keys() if 'dump' in str(k) or 'param' in str(k) or 'arg' in str(k))
    vars['dump_n'] = str(int(vars.get('dump_n') or 0) + 1)
    vars['dump_' + vars['dump_n']] = json.dumps(dict(globals=keys, small=small, varkeys=vk,
        varvals=dict((k, str(vars.get(k))[:100]) for k in vk)))[:3000]
except Exception as e:
    vars['dump_err'] = str(e)[:200]
"""


GRANT = """vars['gate_ok'] = 'yes'
vars['gate_status'] = 'write'
vars['gate_write_product_id'] = 'p1'
vars['gate_write_amount'] = '420.00'
vars['gate_write_date'] = '2026-10-19'
"""


def workflow():
    from builder import hybrid
    l3 = json.load(open(os.path.join(ROOT, "tests", "l3cmp", "out", "l3-raw-4.l3.workflow.json")))
    cp = next(t for n in l3["nodes"].values() for t in n.get("tools") or [] if t["function"]["name"] == "create_promise")
    cp = hybrid.gate_create_promise(cp)
    grant = {"type": "function", "config": {"timeoutMs": 12000},
             "function": {"name": "grant", "handler": "__function__:code_exec", "description": "Call it when the user says 'grant'.",
                          "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": GRANT},
                                                                          "timeout_ms": {"type": "number", "default": 10000}}}}}
    t = {"type": "function", "config": {"timeoutMs": 12000},
         "function": {"name": "dump", "handler": "__function__:code_exec",
                      "description": "Call it when the user says 'dump <word> <number>'.",
                      "parameters": {"type": "object", "properties": {
                          "code": {"type": "string", "default": DUMP}, "timeout_ms": {"type": "number", "default": 10000},
                          "word": {"type": "string"}, "number": {"type": "string"}}, "required": ["word", "number"]}}}
    return {"initial_node": "talk", "system_prompt": "You are a test agent. Short replies.", "test_variables": {"customer_id": "c_test"},
            "nodes": {"talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Ready."},
                               "on_enter_first_entry_only": True, "max_node_turns": 20,
                               "task_message": ("When the user says 'dump <word> <number>', call dump with that word and number, then say OK. "
                                                "When the user says 'grant', call grant. When the user says 'promise now', call create_promise "
                                                "at once (product p1, 420, 2026-10-16), then repeat word for word what it returned."),
                               "tools": [t, grant, cp], "transitions": []}}, "tools": []}


if __name__ == "__main__":
    sims = smoke.running_sims(freya)
    if sims is None or sims:
        sys.exit(f"STOP: simulation running or unknown ({sims}); nothing sent")
    ids = freya.save_workflow("hybrid-probe2", workflow(), os.path.join(ROOT, "tests", ".platform-agents.json"))
    v = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    call, out = None, {"turns": []}
    for m in ["Hello?", "dump apple 11", "dump banana 22", "promise now", "grant", "promise now"]:
        body = {"workflowId": ids["workflow_id"], "message": m, "customerVariables": v}
        if call: body["callId"] = call
        r = freya.api("POST", "/api/v2/chat/message", body)
        call = r.get("callId", call)
        out["turns"].append({"user": m, "agent": r.get("response")}); print(out["turns"][-1])
    c = freya.get_call(call)
    out["raw"] = [{"role": x.get("role"), "node": x.get("nodeId"), "message": x.get("message")} for x in c.get("messages") or []]
    cv = smoke._vars(c)
    out["dumps"] = {k: cv[k] for k in cv if str(k).startswith("dump")}
    try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
    except Exception: pass
    out["ledger_calls"] = http(f"/v1/practice/ledger/{v['customer_id']}").get("calls")
    print("ledger calls:", json.dumps(out["ledger_calls"])[:800])
    json.dump(out, open(os.path.join(ROOT, "tests", "hybrid", "probe2_result.json"), "w"), indent=1, default=str)
    for k, x in sorted(out["dumps"].items()):
        print(k, x[:1500])
