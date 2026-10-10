"""Probe (lane granted, chat only, slot m0-zlib): can a code node import zlib/base64, decompress a ~90 KB program and
exec it with access to `vars`? Also reports the sandbox Python version and the run time.
    python3 tests/probe_zlib.py"""
import base64, json, os, sys, time, zlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya

# ~90 KB payload: a real-size program (many small functions) that writes into vars
body = ["def f%d(x):\n    return x + %d\n" % (i, i) for i in range(2600)]
payload = "".join(body) + "\nvars['zp_sum'] = str(sum(f%d(1) for f in [0]) if False else f2599(1))\n" \
                          "vars['zp_seen'] = str(vars.get('zp_in'))\nimport sys as _s\nvars['zp_py'] = _s.version.split()[0]\n"
blob = base64.b64encode(zlib.compress(payload.encode(), 9)).decode()
loader = ("import zlib, base64, time\n"
          "t0 = time.time()\n"
          "try:\n"
          "    g = dict(vars=vars)\n"
          "    exec(compile(zlib.decompress(base64.b64decode(" + json.dumps(blob) + ")).decode(), 'hub', 'exec'), g)\n"
          "    vars['zp_ok'] = 'yes'\n"
          "except Exception as e:\n"
          "    vars['zp_ok'] = 'error: ' + str(e)[:150]\n"
          "vars['zp_ms'] = str(int((time.time() - t0) * 1000))\n")
assert "{{" not in loader and "}}" not in loader
WF = {"initial_node": "talk", "system_prompt": "Test assistant. English. One short sentence.",
      "nodes": {
          "talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Probe ready."},
                   "task_message": "Say one short sentence. No tool call is allowed.", "max_node_turns": 30,
                   "transitions": [{"target_node": "run", "description": "always", "condition": {"operator": "always"}}]},
          "run": {"name": "run", "node_type": "code", "passthrough": True, "passthrough_default_transition": "said",
                  "on_enter": {"type": "silent"},
                  "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                   "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": loader},
                                                                                   "timeout_ms": {"type": "number", "default": 20000}}}}}],
                  "transitions": [{"target_node": "said", "description": "always", "condition": {"operator": "always"}}]},
          "said": {"name": "said", "node_type": "conversation",
                   "on_enter": {"type": "tts", "text": "ok {{zp_ok}} sum {{zp_sum}} seen {{zp_seen}} py {{zp_py}} ms {{zp_ms}}"},
                   "task_message": "No tool call is allowed.", "max_node_turns": 30,
                   "transitions": [{"target_node": "run", "description": "always", "condition": {"operator": "always"}}]}},
      "test_variables": {"zp_in": "hello-from-vars"}}

if __name__ == "__main__":
    print(f"payload {len(payload)/1024:.1f} KB -> packed {len(blob)/1024:.1f} KB; loader {len(loader)/1024:.1f} KB")
    try:
        print("dry run:", freya.validate_workflow("m0-zlib", WF))
        ids = freya.save_workflow("m0-zlib", WF, os.path.join(ROOT, "tests", ".platform-agents.json"))
        call = None
        for msg in ["Hello?", "Run it."]:
            body = {"workflowId": ids["workflow_id"], "message": msg, "customerVariables": {"zp_in": "hello-from-vars"}}
            if call:
                body["callId"] = call
            r = freya.api("POST", "/api/v2/chat/message", body)
            call = r.get("callId", call)
            print("USER:", msg, "| AGENT:", r.get("response"))
        freya.api("POST", "/api/v2/chat/end", {"callId": call})
        time.sleep(3)
        c = freya.get_call(call)
        vt = {}
        for m in c.get("messages") or []:
            vt.update({k: x.get("value") for k, x in ((m.get("workflowSnapshot") or {}).get("variableTable") or {}).items()})
            if m.get("role") == "system" and "code_exec" in str(m.get("message")):
                print("  event:", str(m.get("message"))[:220])
        print(json.dumps({k: vt.get(k) for k in ("zp_ok", "zp_sum", "zp_seen", "zp_py", "zp_ms")}))
    except RuntimeError as e:
        print("ERROR (not re-sent):", str(e)[:600])
