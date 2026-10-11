"""LIVE probe of the platform mechanics the hybrid gates need (own slot hybrid-probe; only with no simulation running).

Questions:
  Q1 does the model see what a model-called code_exec tool computed (result= / print / vars), and how do its args arrive?
  Q2 does a {{var}} written by that tool resolve in task_message on the next turn?
  Q3 does an api_call pre_process_code see vars (code-written and extracted) and can it block the call (url rewrite)?
  Q4 does post_process_code see vars / config?
  Q5 does an extracted enum (rb_answer) land in vars before the dialogue model's tool call in the same turn?

    python3 tests/hybrid/probe.py            # writes tests/hybrid/probe_result.json
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

MOCK = "https://freya-bank-mock.freyavoice.workers.dev/v1/"
GATE = """import json
try:
    g = globals()
    a = {k: g.get(k) for k in ('date', 'amount') if k in g}
    vs = {k: vars.get(k) for k in ('date', 'amount', 'gate_args.date', 'gate_args.amount', 'gate_args')}
    vars['probe_keys'] = ','.join(sorted(vars.keys()))[:1500]
    vars['probe_args'] = json.dumps({'globals': a, 'vars': vs}, default=str)
    d = str(a.get('date') or vs.get('gate_args.date') or vs.get('date') or '')
    st = 'holiday' if d.startswith('2026-10-16') else 'ok'
    vars['gate_ok'] = 'yes' if st == 'ok' else 'no'
    vars['rb_terms'] = d + '|' + str(a.get('amount') or vs.get('gate_args.amount') or vs.get('amount'))
    vars['rb_answer'] = 'none'
    vars['gate_say'] = 'GATE-VARS-7 status=' + st
    result = {'status': st, 'say': 'GATE-RESULT-42 status=' + st}
    print('GATE-PRINT-43 status=' + st)
except Exception as e:
    vars['gate_say'] = 'gate error ' + str(e)
"""
PRE = """try:
    b = config.get('body') or {}
    vars['pre_seen'] = json.dumps({'gate_ok': vars.get('gate_ok'), 'rb_answer': vars.get('rb_answer'), 'rb_terms': vars.get('rb_terms')}) if 'json' in globals() else str(vars.get('gate_ok')) + '/' + str(vars.get('rb_answer'))
    if vars.get('gate_ok') != 'yes' or vars.get('rb_answer') != 'yes':
        config['url'] = 'https://blocked.invalid/create_promise'
except Exception as e:
    config['url'] = 'https://blocked.invalid/error'
"""
POST = """try:
    extra = {}
    try:
        extra['post_vars'] = str(vars.get('gate_ok'))
    except Exception as e:
        extra['post_vars'] = 'no vars: ' + type(e).__name__
    try:
        extra['post_config_url'] = str(config.get('url'))
    except Exception as e:
        extra['post_config_url'] = 'no config: ' + type(e).__name__
    if isinstance(result, dict):
        result.pop('header', None)
        result['probe'] = extra
        d = result.get('data')
        ok = isinstance(d, dict) and d.get('ok') is True
        result['what_to_do_next'] = 'Saved.' if ok else 'BLOCKED-OR-FAILED: not saved. Tell the user it was not saved.'
except Exception:
    pass
"""


def workflow():
    gate = {"type": "function", "config": {"timeoutMs": 12000},
            "function": {"name": "gate", "handler": "__function__:code_exec",
                         "description": "Checks a date and amount. Call it when the user says 'check <date> <amount>'.",
                         "parameters": {"type": "object", "properties": {
                             "code": {"type": "string", "default": GATE}, "timeout_ms": {"type": "number", "default": 10000},
                             "date": {"type": "string", "description": "YYYY-MM-DD"}, "amount": {"type": "number"}},
                             "required": ["date", "amount"]}}}
    body = {"customer_id": {"type": "string", "default": "{{customer_id}}"},
            "product_id": {"type": "string", "default": "{{product_id}}", "description": "copy from get_account"},
            "amount": {"type": "number", "default": "{{amount}}"}, "date": {"type": "string", "default": "{{date}}", "description": "YYYY-MM-DD"}}
    api = lambda name, desc, props, req: {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0},
        "function": {"name": name, "handler": "__function__:api_call", "description": desc, "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "default": MOCK + name}, "method": {"type": "string", "default": "POST"},
            "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
            "body": {"type": "object", "properties": props, "required": req}}}}}
    from builder import hybrid
    from builder.engine.gates import gate_source
    rp = json.load(open(os.path.join(ROOT, "tests", "hybrid", "probe.brief-a.policy.json")))
    real = {"type": "function", "config": {"timeoutMs": 20000},
            "function": {"name": "check_terms", "handler": "__function__:code_exec",
                         "description": "The real date/amount gate. Call it when the user says 'real <date> <amount>'.",
                         "parameters": {"type": "object", "properties": {
                             "code": {"type": "string", "default": hybrid.prefix("check_terms") + gate_source(rp, "date_amount_gate")},
                             "timeout_ms": {"type": "number", "default": 15000},
                             "gate_product": {"type": "string", "description": "product_id from get_account"},
                             "gate_date": {"type": "string", "description": "YYYY-MM-DD"},
                             "gate_amount": {"type": "string", "description": "the amount, digits only"}},
                             "required": ["gate_product", "gate_date", "gate_amount"]}}}
    cp = api("create_promise", "Records a promise. Call it when the user says 'promise <date> <amount>'.", body, list(body))
    cp["pre_process_code"], cp["post_process_code"] = PRE, POST
    ga = api("get_account", "The customer's products. Call it first.", {"customer_id": body["customer_id"]}, ["customer_id"])
    return {
        "initial_node": "talk",
        "system_prompt": "You are a test agent. Short replies.",
        "test_variables": {"customer_id": "c_test", "gate_say": "none yet"},
        "nodes": {"talk": {
            "name": "talk", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": "Probe ready."}, "on_enter_first_entry_only": True, "max_node_turns": 50,
            "task_message": ("Latest gate note: {{gate_say}}.\nFirst call get_account. When the user says 'check <date> <amount>', call gate "
                             "with that date and amount, then repeat to the user, word for word, everything the tool returned, and add "
                             "'Do you confirm?'. When the user says 'promise <date> <amount>' or 'yes' after a check, call create_promise "
                             "with the product_id from get_account and that date and amount, then repeat word for word what it returned. "
                             "When the user asks 'note?', repeat the latest gate note. When the user says 'real <date> <amount>', "
                             "call check_terms with the product_id, date and amount, then repeat word for word what it returned."),
            "extraction_schema": [{"name": "rb_answer", "type": "string", "enum_values": ["yes", "no", "other"],
                                   "description": "The user's answer to the agent's last 'Do you confirm?': yes, no, or other.",
                                   "min_confidence": 0.5}],
            "tools": [ga, gate, cp, real], "transitions": []}},
        "tools": []}


TURNS = ["Hello?", "check 2026-10-16 420", "note?", "promise 2026-10-19 420", "check 2026-10-19 420", "Yes, I confirm.",
         "real 2026-10-26 300"]

if __name__ == "__main__":
    sims = smoke.running_sims(freya)
    if sims is None or sims:
        sys.exit(f"STOP: simulation running or unknown ({sims}); nothing sent")
    wf = workflow()
    ids = freya.save_workflow("hybrid-probe", wf, os.path.join(ROOT, "tests", ".platform-agents.json"))
    s = http("/v1/practice/sessions", {"case": "PUB-01"})
    v = s["variables"]
    out, call = {"turns": []}, None
    for m in TURNS:
        body = {"workflowId": ids["workflow_id"], "message": m, "customerVariables": v}
        if call: body["callId"] = call
        t = time.time()
        try:
            r = freya.api("POST", "/api/v2/chat/message", body)
        except Exception as e:
            out["turns"].append({"user": m, "error": str(e)[:300], "s": round(time.time() - t, 1)}); print(out["turns"][-1]); break
        call = r.get("callId", call)
        out["turns"].append({"user": m, "agent": r.get("response"), "s": round(time.time() - t, 1)}); print(out["turns"][-1])
    if call:
        c = freya.get_call(call)
        out["messages"] = [{"role": x.get("role"), "node": x.get("nodeId"), "message": x.get("message")} for x in c.get("messages") or []]
        out["vars"] = smoke._vars(c)
        try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception: pass
    out["ledger"] = http(f"/v1/practice/ledger/{v['customer_id']}")
    json.dump(out, open(os.path.join(ROOT, "tests", "hybrid", "probe_result.json"), "w"), indent=1, default=str)
    print(json.dumps({k: out["vars"].get(k) for k in ("gate_ok", "rb_answer", "rb_terms", "probe_args", "pre_seen", "gate_say", "gate_status", "gate_error",
                                                   "gate_prefix_error", "gate_out_date", "probe_keys")} if "vars" in out else {}, indent=1))
    print("ledger:", json.dumps(out["ledger"])[:600])
