"""Probe (contract v2 §10.13): does a passthrough conversation node with on_enter tts {{farewell}} speak and then route
to close_call and end WITHOUT a user turn, with the farewell before the close_call event in the transcript?
Chat API only. Uses the mock close_call with a fresh practice session (no simulation).

    python3 probe/m0_close_say.py
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "probe"))
from m0_probe import freya, http, chat, evidence, STATE, MOCK

HUB = r"""try:
    vars['farewell'] = 'Thank you for your time, goodbye.'
    vars['close_outcome'] = 'not_reached'
    vars['close_reason'] = 'unclear'
    vars['route'] = 'close'
except Exception as e:
    vars['route'] = 'close'
"""

WF = {"initial_node": "talk", "system_prompt": "Probe assistant. English. One short sentence.",
      "nodes": {
          "talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "llm"}, "task_message": "Reply briefly. No tool call is allowed.",
                   "transitions": [{"target_node": "hub", "description": "always", "condition": {"operator": "always"}}]},
          "hub": {"name": "hub", "node_type": "code", "passthrough": True, "passthrough_default_transition": "close_say", "on_enter": {"type": "silent"},
                  "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                   "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": HUB}, "timeout_ms": {"type": "number", "default": 10000}}}}}],
                  "transitions": [{"target_node": "close_say", "description": "always", "condition": {"operator": "always"}}]},
          "close_say": {"name": "close_say", "node_type": "conversation", "passthrough": True, "passthrough_default_transition": "t_close_call",
                        "on_enter": {"type": "tts", "text": "{{farewell}}"}, "task_message": "Say nothing else. No tool call is allowed.",
                        "transitions": [{"target_node": "t_close_call", "description": "always", "condition": {"operator": "always"}}]},
          "t_close_call": {"name": "t_close_call", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "end",
                           "on_enter": {"type": "silent"},
                           "pre_actions": [{"type": "function", "config": {"timeoutMs": 10000, "maxRetries": 0},
                                            "function": {"name": "close_call", "handler": "__function__:api_call", "description": "close",
                                                         "parameters": {"type": "object", "properties": {
                                                             "url": {"type": "string", "default": MOCK + "/close_call"},
                                                             "method": {"type": "string", "default": "POST"},
                                                             "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                                                             "body": {"type": "object", "required": [], "properties": {
                                                                 "customer_id": {"type": "string", "default": "{{customer_id}}"},
                                                                 "outcome": {"type": "string", "default": "{{close_outcome}}"},
                                                                 "reason": {"type": "string", "default": "{{close_reason}}"}}}}}}}],
                           "transitions": [{"target_node": "end", "description": "always", "condition": {"operator": "always"}}]},
          "end": {"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                  "terminal": {"type": "function", "function": {"name": "probe_closed", "handler": "__function__:end_call",
                               "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}}}

if __name__ == "__main__":
    sess = http("/v1/practice/sessions", {"case": "PUB-02"})["variables"]
    print("dry run:", freya.validate_workflow("m0-close", WF))
    ids = freya.save_workflow("m0-close", WF, state_file=STATE)
    call, out = chat(ids["workflow_id"], ["Hello?", "Who is this?"], {"customer_id": sess["customer_id"]})
    c, vt = evidence(call, "m0_close_say")
    print("CALL", call, "endedReason", c.get("endedReason"))
    for m in c["messages"]:
        t = str(m.get("message"))
        if m.get("role") in ("user", "assistant"):
            print("   ", m["role"], m.get("nodeId"), "|", t[:90])
        elif '"node_enter"' in t or 'close_call' in t or '"call_ended"' in t:
            print("      ", t[:140])
    led = http("/v1/practice/ledger/" + sess["customer_id"])
    print("ledger:", led.get("outcome"), led.get("reason"), [x["tool"] for x in led.get("calls", [])])
