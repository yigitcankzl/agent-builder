"""Measure Freya's real code_exec stdout limit. Uses the chat API. Do not run during a simulation sweep.

The sandbox prints __CODE_EXEC_RESULT__ plus the vars JSON and cuts that stdout. This saves a one-node
workflow whose code sets vars['pad'] to a string of length probe_n, sends one chat turn, and reads the
call. A binary search finds the largest pad whose code_exec result still parses.

    source env.sh && python3 probe/payload_budget.py

Writes probe/payload_budget_result.json. Does not start if a simulation is already running.
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CODE = (
    "n = int(vars.get('probe_n') or 0)\n"
    "vars['pad'] = 'x' * n\n"
    "vars['pad_n'] = str(n)\n"
    "vars['route'] = 'say'\n"
)


def _workflow():
    edge = {"target_node": "measure", "description": "always", "condition": {"operator": "always"}}
    say = {"target_node": "say", "description": "always", "condition": {"operator": "always"}}
    return {
        "initial_node": "greet",
        "system_prompt": "You are a test assistant. Speak English. One short sentence.",
        "test_variables": {"probe_n": "0", "route": "stale"},
        "nodes": {
            "greet": {"name": "greet", "node_type": "conversation",
                      "on_enter": {"type": "tts", "text": "Hello."},
                      "task_message": "Wait.", "max_node_turns": 5, "transitions": [edge]},
            "measure": {"name": "measure", "node_type": "code", "passthrough": True,
                        "passthrough_default_transition": "say", "on_enter": {"type": "silent"},
                        "pre_actions": [{"type": "function", "function": {
                            "name": "code_exec", "handler": "__function__:code_exec",
                            "parameters": {"type": "object", "properties": {
                                "code": {"type": "string", "default": CODE},
                                "timeout_ms": {"type": "number", "default": 10000}}}}}],
                        "transitions": [say]},
            "say": {"name": "say", "node_type": "conversation",
                    "on_enter": {"type": "tts", "text": "Done."},
                    "task_message": "Wait.", "max_node_turns": 5, "transitions": [edge]},
        },
    }


def _parsed(call):
    """(ok, printed_chars, error). ok is True when code_exec completed and pad survived."""
    printed, err, ok = 0, "", False
    for m in call.get("messages") or []:
        ev = m.get("event") or {}
        if not isinstance(ev, dict) or ev.get("function") != "code_exec":
            continue
        if ev.get("event") == "function_call_complete" and (ev.get("result") or {}).get("status") == "success":
            ok = True
        text = str(ev.get("error") or ev.get("result") or "")
        if "CODE_EXEC_RESULT" in text or "parse" in text.lower() or "Unterminated" in text:
            err = text[:500]
            printed = max(printed, len(text))
        v = m.get("vars") if isinstance(m.get("vars"), dict) else {}
        if v.get("pad_n") and str(v.get("pad_n")) == str(len(v.get("pad") or "")):
            ok = True
            printed = max(printed, len(json.dumps({"vars": v})))
    return ok, printed, err


def search(freya, lo=1000, hi=20000):
    """Largest pad length whose code_exec result parses. One new chat call per probe."""
    from builder.smoke import running_sims
    sims = running_sims(freya)
    if sims:
        raise SystemExit("simulation running (%s); not measuring" % ",".join(sims))
    wf = _workflow()
    if "{{" in CODE or "}}" in CODE:
        raise SystemExit("probe code has double braces")
    print("dry run:", freya.validate_workflow("payload-budget", wf))
    ids = freya.save_workflow("payload-budget", wf, state_file=os.path.join(os.path.dirname(__file__), ".freya-payload.json"))
    best, best_printed, last_err = 0, 0, ""

    def attempt(n):
        nonlocal best, best_printed, last_err
        cv = {"probe_n": str(n), "customer_id": "c_probe", "first_name": "Pat", "last_name": "Probe", "title": "Ms", "now": "2026-10-14T11:00"}
        r = freya.api("POST", "/api/v2/chat/message", {"workflowId": ids["workflow_id"], "message": "Hello", "customerVariables": cv})
        call = r.get("callId")
        time.sleep(2)
        try:
            freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception:
            pass
        time.sleep(2)
        ok, printed, err = _parsed(freya.get_call(call))
        last_err = err
        print("n=%d parsed=%s printed~%d" % (n, ok, printed))
        if ok and n > best:
            best, best_printed = n, printed
        return ok

    # Expand until a size fails, then binary-search the last success.
    n = lo
    if not attempt(n):
        hi = n
    else:
        while n < hi:
            nxt = min(hi, n * 2)
            if not attempt(nxt):
                hi = nxt
                break
            n = nxt
        lo = n
    while hi - lo > 200:
        mid = (lo + hi) // 2
        if attempt(mid):
            lo = mid
        else:
            hi = mid
    out = {"max_pad_chars": best, "printed_chars_at_max": best_printed, "next_fail_below": hi, "last_error": last_err[:300]}
    path = os.path.join(os.path.dirname(__file__), "payload_budget_result.json")
    json.dump(out, open(path, "w"), indent=1)
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import freya
    search(freya)
