"""M0 platform probes (chat API only, no simulation). Own slots m0-*, own state file.

    python3 probe/m0_probe.py
Graph:  talk/exact_say/talk_llm --always--> hub (code reducer stand-in) --route--> exact_say | talk_llm | w_ok | w_bad
        w_ok / w_bad (api_request, code-baked args) --always--> hub
Freshness: hub writes ev_nonce; the extraction prompt echoes it as the first token of the composite field `ev`.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401  (loads env.sh, never prints)
import freya
sys.path.insert(0, os.path.join(ROOT, "tools"))
from score import http  # mock bank practice routes (team key from env)

STATE = os.path.join(ROOT, "probe", ".m0-agents.json")
MOCK = "https://freya-bank-mock.freyavoice.workers.dev/v1"
OUT = os.path.join(ROOT, "probe", "m0_evidence")

HUB = r"""import json, datetime
try:
    try:
        log = json.loads(str(vars.get('m0_log') or '[]'))
    except Exception:
        log = []
    runs = int(vars.get('hub_runs') or 0) + 1
    vars['hub_runs'] = str(runs)
    nonce = int(vars.get('ev_seq') or 0)
    tok = str(vars.get('ev_tok') or 'kstart')
    ev = str(vars.get('ev') or '')
    parts = dict()
    for p in ev.split(';'):
        if '=' in p:
            k, v = p.split('=', 1)
            parts[k.strip()] = v.strip()
    fresh = bool(ev) and parts.get('n') == tok
    us = datetime.datetime.now().microsecond + runs * 7919
    letters = 'abcdefghjkmnpqrstuvwxyz'
    nt = 'k'
    for _ in range(5):
        nt = nt + letters[us % 23]
        us = us // 23
    vars['ev_tok'] = nt
    act = parts.get('act', '') if fresh else ''
    refusals = int(vars.get('refusals') or 0)
    route = 'talk'
    say = ''
    pending = str(vars.get('w_pending') or '')
    if pending and not fresh:
        sc = vars.get(pending + '_success_count')
        fc = vars.get(pending + '_failure_count')
        ok = vars.get(pending + '_response.data.ok')
        st = vars.get(pending + '_response.status_code')
        hk = vars.get('m0_hook_' + pending)
        say = 'PROBE tool ' + pending + ': success ' + str(sc) + ', failure ' + str(fc) + ', ok ' + str(ok) + ', status ' + str(st) + ', hook ' + str(hk)
        vars['w_pending'] = ''
    elif fresh:
        vars['ev_seq'] = str(nonce + 1)
        if act in ('no', 'refuse'):
            refusals += 1
            say = 'PROBE refusal counted. Refusals now ' + str(refusals) + '. Turn ' + str(nonce + 1) + '.'
        elif act == 'tool_ok':
            route = 'w_ok'
            vars['w_pending'] = 'w_ok'
        elif act == 'tool_bad':
            route = 'w_bad'
            vars['w_pending'] = 'w_bad'
        elif act == 'brace':
            say = 'PROBE brace test: a }} b {{ c'
        else:
            say = 'PROBE nothing to count. Refusals still ' + str(refusals) + '.'
    vars['refusals'] = str(refusals)
    vars['say_next'] = say
    if route == 'talk' and say:
        route = 'say'
    vars['route'] = route
    log.append(dict(run=runs, tok=tok, new_tok=nt, ev=ev, fresh=fresh, act=act, route=route))
    vars['m0_log'] = json.dumps(log)
except Exception as e:
    vars['route'] = 'talk'
    vars['m0_error'] = str(e)[:200]
"""
assert "{{" not in HUB.replace("'PROBE brace test: a }} b {{ c'", "") and "}}" not in HUB.replace("'PROBE brace test: a }} b {{ c'", "")

EV = {"name": "ev", "type": "string", "min_confidence": 0.3,
      "validation_pattern": r"^n=[a-z0-9]{1,8};act=(yes|no|refuse|tool_ok|tool_bad|brace|other)$",
      "description": "A code label in the form n=<code>;act=<label>, for example n=kqwrtz;act=no. Never the customer's own words.",
      "max_retries": 2,
      "extraction_prompt": ("Code: {{ev_tok}}. Label ONLY the customer's last message. Write exactly "
                            "n=<copy the code above letter by letter>;act=<one of: yes, no, refuse, tool_ok (they ask to run the good tool), "
                            "tool_bad (they ask to run the bad tool), brace (they ask for the brace test), other>. "
                            "Always fill it, use act=other if nothing applies. Examples: code kbmtpq, customer says 'No.' -> n=kbmtpq;act=no. "
                            "Code kxzrwa, customer talks about the weather -> n=kxzrwa;act=other. If the code above is not a word "
                            "of letters, write n=new. The value is a code label, never "
                            "the customer's words.\n{{extractor.type_preamble}}\n"
                            "{{extractor.variables_list}}\nConversation:\n{{extractor.conversation.last-10}}\n"
                            "Last message: {{extractor.speech}}")}
TO_HUB = [{"target_node": "hub", "description": "always", "condition": {"operator": "always"}}]


def conv(name, on_enter, task):
    return {"name": name, "node_type": "conversation", "on_enter": on_enter, "task_message": task,
            "extraction_schema": [EV], "max_node_turns": 60, "transitions": TO_HUB}


def api_node(name, url, body, hook):
    return {"name": name, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "hub",
            "on_enter": {"type": "silent"},
            "pre_actions": [{"type": "function", "config": {"timeoutMs": 10000, "maxRetries": 0},
                             "function": {"name": name + "_call", "handler": "__function__:api_call", "description": "probe",
                                          "parameters": {"type": "object", "properties": {
                                              "url": {"type": "string", "default": url},
                                              "method": {"type": "string", "default": "POST"},
                                              "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                                              "body": {"type": "object", "properties": body, "required": []}}}},
                             "post_process_code": hook}],
            "response_mapping": [{"path": "data.ok", "variable": name + "_mapped_ok"}],
            "transitions": TO_HUB}


def hook(name):
    return f"try:\n    vars['m0_hook_{name}'] = 'ran'\nexcept Exception:\n    pass\n"


def workflow(code=HUB):
    return {"initial_node": "talk", "test_variables": {"ev_tok": "kstart"}, "system_prompt": "You are a probe assistant. English. One short sentence. Never promise anything.",
            "nodes": {
                "talk": conv("talk", {"type": "tts", "text": "PROBE start."}, "Reply in one short sentence. No tool call is allowed."),
                "talk_llm": conv("talk_llm", {"type": "llm"}, "Reply in one short sentence. No tool call is allowed."),
                "exact_say": conv("exact_say", {"type": "tts", "text": "{{say_next}}"}, "Reply in one short sentence. No tool call is allowed."),
                "hub": {"name": "hub", "node_type": "code", "passthrough": True, "passthrough_default_transition": "talk_llm",
                        "on_enter": {"type": "silent"},
                        "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                         "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code},
                                                                                         "timeout_ms": {"type": "number", "default": 10000}}}}}],
                        "transitions": [
                            {"target_node": "exact_say", "description": "say", "condition": {"logic": "or", "conditions": [{"variable": "route", "operator": "equals", "operand": "say"}]}},
                            {"target_node": "w_ok", "description": "good tool", "condition": {"logic": "or", "conditions": [{"variable": "route", "operator": "equals", "operand": "w_ok"}]}},
                            {"target_node": "w_bad", "description": "bad tool", "condition": {"logic": "or", "conditions": [{"variable": "route", "operator": "equals", "operand": "w_bad"}]}},
                            {"target_node": "talk_llm", "description": "always", "condition": {"operator": "always"}}]},
                "w_ok": api_node("w_ok", MOCK + "/verify_identity",
                                 {"customer_id": {"type": "string", "default": "{{customer_id}}"},
                                  "field": {"type": "string", "default": "date_of_birth"},
                                  "answer": {"type": "string", "default": "{{w_answer}}"}}, hook("w_ok")),
                "w_bad": api_node("w_bad", MOCK + "/m0_no_such_route", {"customer_id": {"type": "string", "default": "c_m0_fake"}}, hook("w_bad")),
            }}


def chat(wid, msgs, cv):
    call, out = None, []
    for m in msgs:
        body = {"workflowId": wid, "message": m, "customerVariables": cv}
        if call: body["callId"] = call
        for attempt in range(4):
            try:
                r = freya.api("POST", "/api/v2/chat/message", body)
                break
            except RuntimeError as e:
                r = {"response": "<ERROR " + str(e)[:120] + ">"}
                print("   retry after", str(e)[:60])
                time.sleep(6)
        call = r.get("callId", call)
        out.append((m, r.get("response")))
        print(f"  USER: {m}\n  AGENT: {r.get('response')}")
        time.sleep(1)
    try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
    except Exception: pass
    time.sleep(3)
    return call, out


def evidence(call, name):
    c = freya.get_call(call)
    os.makedirs(OUT, exist_ok=True)
    json.dump(c, open(os.path.join(OUT, name + ".json"), "w"), indent=1, default=str)
    vt = {}
    for m in c["messages"]:
        vt.update({k: x.get("value") for k, x in ((m.get("workflowSnapshot") or {}).get("variableTable") or {}).items()})
    return c, vt


if __name__ == "__main__":
    sess = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]          # a real mock customer for the good tool
    dob = [x for x in json.load(open(os.path.join(ROOT, "public-test-set.json"))) if x["id"] == "PUB-01"][0]["identity"]["date_of_birth"]
    wf = workflow()
    print("dry run:", freya.validate_workflow("m0-hub", wf))
    ids = freya.save_workflow("m0-hub", wf, state_file=STATE)
    print(ids)
    cv = {"customer_id": sess["customer_id"], "now": "2026-10-14T11:00", "w_answer": dob}
    msgs = ["Hi", "No.", "No.", "The weather is lovely today, isn't it?", "Please run the good tool.",
            "Please run the bad tool.", "Do the brace test.", "No.", "Hmm."]
    call, out = chat(ids["workflow_id"], msgs, cv)
    c, vt = evidence(call, "m0_hub_main")
    print("CALL", call)
    for m in c["messages"]:
        if m.get("role") in ("user", "assistant"):
            print("   ", m["role"], m.get("nodeId"), "|", (m.get("message") or "")[:90])
    for row in json.loads(vt.get("m0_log") or "[]"):
        print("  hub", row)
    print({k: vt.get(k) for k in ("refusals", "hub_runs", "ev_tok", "m0_error", "w_ok_success_count", "w_ok_failure_count",
                                   "w_bad_success_count", "w_bad_failure_count", "w_ok_mapped_ok", "w_bad_mapped_ok",
                                   "m0_hook_w_ok", "m0_hook_w_bad", "w_ok_response.status_code", "w_bad_response.status_code")})
    # without ev_nonce as a call variable: what does the extractor see before the hub ever ran?
    cv2 = dict(cv)
    call2, _ = chat(ids["workflow_id"], ["Hi", "No.", "No."], cv2)
    c2, vt2 = evidence(call2, "m0_hub_no_initial_nonce")
    print("CALL2", call2, [r for r in json.loads(vt2.get("m0_log") or "[]")], vt2.get("refusals"))
