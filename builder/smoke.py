"""Post-save chat smoke test (FINAL-PLAN signal S7). OFF unless BUILDER_SMOKE=1.

Two chat turns to the saved workflow, then one read of the call:
  turn 0 "Hello?" (chat does not route the first turn), turn 1 a name confirmation (extraction -> routing -> engine).
Fails (signal S7) only on workflow-side evidence: a greet placeholder that is neither a call variable nor a test
variable (static, with call_vars: chat never speaks the greet), a reply containing "{{", a started call with no reply,
an HTTP 4xx that points at the workflow (400/404/409/422), and, when the workflow has the engine hub: no successful
code_exec in the hub node, a hub_error, or route/say_next still at their initial values after turn 1. Platform-side
failures (HTTP 5xx/429/401/403, connection errors, timeouts, a call that never started, every turn slow, get_call
failing) give skipped=True with the reason: the saved workflow is kept. An L3 workflow (no hub) gets the reply checks only.
Skipped (not a failure) while a simulation runs in the workspace: chat then times out and slows the simulation.

    from builder import smoke
    s = smoke.run(api, get_call, workflow_id, wf)     # api(method, path, body) -> dict; get_call(call_id) -> call dict
    s -> {"ok": bool, "skipped": bool, "signal": "S7" | None, "reason": str, "turns": [...]}
"""
import json, os, re, time

SLOW_S = 20
TURNS = ["Hello?", "Yes, speaking."]


def enabled():
    return os.environ.get("BUILDER_SMOKE") == "1"


def running_sims(freya):
    """Ids of simulations running in the workspace now (freya: the freya client module). None if it cannot be read."""
    try:
        r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=5)
        return [x["id"] for x in (r.get("simulations") or r.get("items") or r) if x.get("status") not in ("completed", "failed", "paused")]
    except Exception:
        return None


def _vars(call):
    """Variable values after the last message that carries a snapshot."""
    out = {}
    for m in call.get("messages") or []:
        vt = (m.get("workflowSnapshot") or {}).get("variableTable") or {}
        if vt:
            out = {k: (x.get("value") if isinstance(x, dict) else x) for k, x in vt.items()}
    return out


def _events(call):
    for m in call.get("messages") or []:
        if m.get("role") == "system":
            try:
                yield m.get("nodeId"), json.loads(m.get("message") or "{}")
            except (TypeError, ValueError):
                continue


def check_call(call, wf):
    """Engine checks on the call record after turn 1. Returns a list of problems."""
    nodes, tv = wf.get("nodes") or {}, wf.get("test_variables") or {}
    hub = next((k for k, n in nodes.items() if n.get("node_type") == "code" and k == "hub"), None)
    if not hub:
        return []
    bad, ran = [], False
    for node, e in _events(call):
        if e.get("function") == "code_exec" and node == hub:
            if e.get("event") == "function_call_complete" and (e.get("result") or {}).get("status") == "success":
                ran = True
            elif e.get("event") in ("function_call_error", "function_call_failed") or (e.get("result") or {}).get("status") == "error":
                bad.append(f"hub code_exec failed: {json.dumps(e.get('result') or e)[:200]}")
    if not ran:
        bad.append("no successful code_exec in the hub node")
    v = _vars(call)
    if v.get("hub_error"):
        bad.append(f"hub_error: {str(v['hub_error'])[:200]}")
    for k in ("route", "say_next"):
        if not v.get(k) or v.get(k) == tv.get(k):
            bad.append(f"{k} not written by the hub (value {str(v.get(k))[:60]!r})")
    return bad


_PLATFORM_HTTP = re.compile(r"\b(5\d\d|429|401|403)\b")
_PLATFORM_WORDS = re.compile(r"timed? ?out|timeout|connection|temporarily unavailable|unavailable|reset by peer|"
                             r"name resolution|ssl|refused|api key validation", re.I)
_WORKFLOW_HTTP = re.compile(r"\b(400|404|409|422)\b")


def classify_error(text):
    """An exception text from the chat API -> 'platform' (a transient or auth/infra failure: never S7) or 'workflow'
    (a 4xx that points at the workflow). Unknown errors count as platform: a good main workflow is never replaced on
    a guess."""
    t = str(text or "")
    if _WORKFLOW_HTTP.search(t) and not _PLATFORM_HTTP.search(t):
        return "workflow"
    return "platform"


def greet_placeholders(wf, call_vars):
    """{{x}} in the initial node's spoken text that is neither a call variable of the brief nor a test variable. Chat
    never speaks the greet (turn 0 is not routed), so this is checked on the workflow itself, before any chat turn."""
    n = (wf.get("nodes") or {}).get(wf.get("initial_node")) or {}
    text = (n.get("on_enter") or {}).get("text") or ""
    known = set((wf.get("test_variables") or {}).keys()) | set(call_vars)
    return [v for v in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", text) if v not in known]


def run(api, get_call, workflow_id, wf, sims_running=None, end=True, call_vars=None, variables=None):
    """call_vars: the brief's call variable names; None skips the static greet check. variables: call variable values."""
    res = {"ok": False, "skipped": False, "signal": None, "reason": "", "turns": []}
    bogus = greet_placeholders(wf, call_vars) if call_vars is not None else []
    if bogus:
        res.update(signal="S7", reason=f"greet speaks undeclared placeholders {bogus}")
        return res
    if sims_running:
        res.update(ok=True, skipped=True, reason=f"simulation running ({','.join(sims_running)}): smoke skipped")
        return res
    call, slow, problems, platform = None, 0, [], []
    cv = {k: v for k, v in (wf.get("test_variables") or {}).items() if isinstance(v, str)}
    cv.update(variables or {})                         # call variable values (e.g. a practice session's), if given
    for msg in TURNS:
        body = {"workflowId": workflow_id, "message": msg, "customerVariables": cv}
        if call:
            body["callId"] = call
        t = time.time()
        try:
            r = api("POST", "/api/v2/chat/message", body)
        except Exception as e:                          # no re-send on 503/504: one attempt, the error is the result
            res["turns"].append({"user": msg, "error": str(e)[:300], "s": round(time.time() - t, 1)})
            (problems if classify_error(e) == "workflow" else platform).append(f"HTTP error on turn {len(res['turns']) - 1}: {str(e)[:200]}")
            break
        dt = round(time.time() - t, 1)
        call = r.get("callId", call)
        reply = r.get("response")
        res["turns"].append({"user": msg, "agent": reply, "s": dt})
        slow += dt > SLOW_S
        if not reply:     # no call id: the call never started (platform); a started call with no reply is the workflow's
            (problems if call else platform).append(f"no reply on turn {len(res['turns']) - 1}")
        elif "{{" in reply:
            problems.append(f"unresolved placeholder in the reply: {reply[:120]!r}")
    if slow == len(TURNS):
        platform.append(f"every turn slower than {SLOW_S} s")
    if call and not problems:
        try:
            problems += check_call(get_call(call), wf)
        except Exception as e:
            platform.append(f"get_call failed: {str(e)[:200]}")
    if call and end:
        try: api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception: pass
    if problems:          # workflow-side evidence only: S7
        res.update(ok=False, signal="S7", reason="; ".join(problems + platform), call_id=call)
    elif platform:        # platform-side: skipped, the saved workflow is kept
        res.update(ok=False, skipped=True, signal=None, reason="platform: " + "; ".join(platform), call_id=call)
    else:
        res.update(ok=True, signal=None, reason="", call_id=call)
    return res


class Recorded:
    """Offline stand-in for the chat API: replays the agent lines and the call record of a recorded call
    (an export_fails.py file: messages with role/node/message/vars)."""

    def __init__(self, path, mutate=None):
        d = json.load(open(path))
        self.msgs = d["messages"]
        self.mutate = mutate or (lambda kind, x: x)
        self.lines = [m["message"] for m in self.msgs if m["role"] == "assistant"]
        self.n = 0

    def api(self, method, path, body):
        if path.endswith("/chat/end"):
            return {"ended": True}
        # chat answers turn 0 without routing: a generic line; turn 1 gets the first engine line of the recording
        reply = "Hello! How can I help you today?" if self.n == 0 else self.lines[min(self.n, len(self.lines) - 1)]
        self.n += 1
        return self.mutate("reply", {"response": reply, "callId": "rec-call"})

    def get_call(self, call_id):
        msgs = [{"role": m["role"], "nodeId": m.get("node"), "message": m.get("message"),
                 **({"workflowSnapshot": {"variableTable": {k: {"value": v} for k, v in m["vars"].items()}}} if m.get("vars") else {})}
                for m in self.msgs]
        return self.mutate("call", {"messages": msgs})


if __name__ == "__main__":       # offline self-check: python3 builder/smoke.py <workflow.json> <recorded.json>
    import sys
    wf = json.load(open(sys.argv[1])); wf = wf.get("workflow", wf)
    rec = Recorded(sys.argv[2])
    print(json.dumps(run(rec.api, rec.get_call, "rec-wf", wf), indent=1))
