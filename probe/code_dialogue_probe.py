"""Probe: can a code node decide and the agent speak that decision in the SAME turn, with state kept across turns?

    source env.sh && python3 probe/code_dialogue_probe.py
Flow: ask (extract requested_date) -> resolve (code: next business day, attempt counter, say_next, clear input)
      -> respond (on_enter tts "{{say_next}}", extract again) -> resolve ...
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import freya

CODE = """import datetime
try:
    raw = str(vars.get('requested_date') or '')[:10]
    if raw == str(vars.get('handled_date') or ''):
        vars['date_state'] = 'same'
        raise StopIteration
    vars['handled_date'] = raw
    vars['date_state'] = 'new'
    n = int(vars.get('attempts') or 0) + 1
    vars['attempts'] = str(n)
    day = datetime.date.fromisoformat(raw)
    orig = day
    while day.weekday() >= 5 or day.isoformat() in ['2026-10-26']:
        day = day + datetime.timedelta(days=1)
    vars['resolved_date'] = day.isoformat()
    if day == orig:
        vars['say_next'] = 'PROBE ' + str(n) + ': ' + day.isoformat() + ' is fine. Do you confirm?'
    else:
        vars['say_next'] = 'PROBE ' + str(n) + ': ' + orig.isoformat() + ' is not a business day, I can offer ' + day.isoformat() + '. Does that work?'
except StopIteration:
    pass
except Exception:
    vars['date_state'] = 'new'
    vars['say_next'] = 'PROBE: I could not read that date.'
"""
DATE = [{"name": "requested_date", "type": "date", "description": "The payment date the customer just named, if any", "min_confidence": 0.5}]
TO_RESOLVE = {"target_node": "resolve", "description": "A new date was named",
              "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                  {"variable": "requested_date", "operator": "is_set"}]}]}}
WF = {
    "initial_node": "ask",
    "system_prompt": "You are a test assistant. Speak English. One short sentence per turn.",
    "test_variables": {"customer_id": "c_probe", "now": "2026-10-14T11:00"},
    "nodes": {
        "ask": {"name": "ask", "node_type": "conversation", "on_enter": {"type": "tts", "text": "PROBE start. When can you pay?"},
                "task_message": "Ask for a payment date. No tool call is allowed.", "extraction_schema": DATE,
                "max_node_turns": 30, "transitions": [TO_RESOLVE]},
        "resolve": {"name": "resolve", "node_type": "code", "passthrough": True, "passthrough_default_transition": "respond",
                    "on_enter": {"type": "silent"},
                    "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                     "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": CODE},
                                                                                     "timeout_ms": {"type": "number", "default": 10000}}}}}],
                    "transitions": [{"target_node": "listen", "description": "same date as before", "condition": {"logic": "or", "conditions": [{"variable": "date_state", "operator": "equals", "operand": "same"}]}},
                                    {"target_node": "respond", "description": "always", "condition": {"operator": "always"}}]},
        "listen": {"name": "listen", "node_type": "conversation", "on_enter": {"type": "llm"},
                   "task_message": "Answer the customer briefly. The date on the table is {{resolved_date}}. No tool call is allowed.",
                   "extraction_schema": DATE, "max_node_turns": 30, "transitions": [TO_RESOLVE]},
        "respond": {"name": "respond", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{say_next}}"},
                    "task_message": "Answer briefly. Resolved date so far: {{resolved_date}}. Attempts: {{attempts}}. No tool call is allowed.",
                    "extraction_schema": DATE, "max_node_turns": 30, "transitions": [TO_RESOLVE]},
    },
}

if __name__ == "__main__":
    assert "{{" not in CODE and "}}" not in CODE
    print("dry run:", freya.validate_workflow("probe", WF))
    ids = freya.save_workflow("probe", WF, state_file=os.path.join(os.path.dirname(__file__), ".freya-agents.json"))
    print(ids)
    cv = {"customer_id": "c_probe", "first_name": "Pat", "last_name": "Probe", "title": "Mr", "now": "2026-10-14T11:00"}
    call = None
    for msg in ["Hi", "I can pay on October 26, 2026", "Thanks, just a second", "Make it October 28, 2026 instead", "Yes"]:
        body = {"workflowId": ids["workflow_id"], "message": msg, "customerVariables": cv}
        if call: body["callId"] = call
        r = freya.api("POST", "/api/v2/chat/message", body)
        call = r.get("callId", call)
        print(f"USER: {msg}\nAGENT: {r.get('response')}\n")
        time.sleep(1)
    try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
    except Exception as e: print("end:", e)
    time.sleep(3)
    c = freya.get_call(call)
    json.dump(c, open(os.path.join(os.path.dirname(__file__), "probe_call.json"), "w"), indent=1, default=str)
    print("call keys:", list(c)[:40])
