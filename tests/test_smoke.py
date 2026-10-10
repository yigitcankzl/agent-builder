"""Offline checks of builder/smoke.py on a recorded real call (no Freya). python3 tests/test_smoke.py"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import smoke

REC = os.path.join(ROOT, "tests", "smoke", "recorded_main.json")
WF = json.load(open(os.path.join(ROOT, "tests", "fallback", "runs", "none", "brief-a.workflow.json")))
WF = WF.get("workflow", WF)
L3 = json.load(open(os.path.join(ROOT, "tests", "fallback", "brief-a.l3.workflow.json")))


def go(wf=WF, mutate=None, **kw):
    rec = smoke.Recorded(REC, mutate)
    return smoke.run(rec.api, rec.get_call, "wf", wf, **kw)


def strip_hub_complete(kind, x):
    if kind == "call":
        x["messages"] = [m for m in x["messages"] if not (m["nodeId"] == "hub" and "function_call_complete" in str(m["message"]))]
    return x


def vars_unchanged(kind, x):
    if kind == "call":
        for m in x["messages"]:
            vt = (m.get("workflowSnapshot") or {}).get("variableTable")
            if vt:
                vt["route"] = {"value": "stale"}
    return x


def hub_error(kind, x):
    if kind == "call":
        x["messages"][-1]["workflowSnapshot"]["variableTable"]["hub_error"] = {"value": "KeyError: 'st'"}
    return x


def placeholder(kind, x):
    if kind == "reply" and "date of birth" in x["response"]:
        x["response"] = "Hello {{bogus}}, can you tell me your date of birth?"
    return x


def http_error(kind, x):
    if kind == "reply":
        raise RuntimeError("POST /api/v2/chat/message -> 503: Internal server error")
    return x


def timeout(kind, x):
    if kind == "reply":
        raise TimeoutError("The read operation timed out")
    return x


def http_422(kind, x):
    if kind == "reply":
        raise RuntimeError("POST /api/v2/chat/message -> 422: workflow node 'hub' has no transitions")
    return x


def key_503(kind, x):
    if kind == "reply":
        raise RuntimeError("POST /api/v2/chat/message -> 503: API key validation temporarily unavailable")
    return x


# expected: "pass" (ok), "s7" (workflow-side failure), "skip" (platform-side: skipped, the saved workflow kept)
CASES = [
    ("recorded main call passes", dict(), "pass"),
    ("L3 workflow (no hub): reply checks only", dict(wf=L3), "pass"),
    ("hub code_exec never completed", dict(mutate=strip_hub_complete), "s7"),
    ("route still at its initial value", dict(mutate=vars_unchanged), "s7"),
    ("hub_error set", dict(mutate=hub_error), "s7"),
    ("{{bogus}} in a reply", dict(mutate=placeholder), "s7"),
    ("HTTP 503 on turn 0: platform, skipped, main kept", dict(mutate=http_error), "skip"),
    ("API key validation 503: platform, skipped", dict(mutate=key_503), "skip"),
    ("a timeout: platform, skipped", dict(mutate=timeout), "skip"),
    ("HTTP 422 on the workflow: S7", dict(mutate=http_422), "s7"),
    ("simulation running: skipped, not failed", dict(sims_running=["sim1"]), "skip"),
]

if __name__ == "__main__":
    bad = 0
    for name, kw, want in CASES:
        r = go(**kw)
        got = "s7" if r["signal"] == "S7" else ("skip" if r["skipped"] else ("pass" if r["ok"] else "fail"))
        ok = got == want
        bad += not ok
        print(("ok  " if ok else "FAIL"), name, "->", r["ok"], r["signal"], r["reason"][:120] or ("skipped" if r["skipped"] else ""))
    print("PASS" if not bad else "FAIL")
    sys.exit(1 if bad else 0)
