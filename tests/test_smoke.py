"""Offline checks of builder/smoke.py on a recorded real call (no Freya). python3 tests/test_smoke.py"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import smoke

REC = os.path.join(ROOT, "tests", "smoke", "recorded_main.json")
WF = json.load(open(os.path.join(ROOT, "tests", "fallback", "runs", "none", "brief-a.workflow.json")))
WF = WF.get("workflow", WF)
L3 = json.load(open(os.path.join(ROOT, "tests", "fallback", "brief-a.l3.workflow.json")))


CALL_VARS = ["customer_id", "first_name", "last_name", "title", "now"]     # the practice session's variables


def go(wf=WF, mutate=None, **kw):
    rec = smoke.Recorded(REC, mutate)
    return smoke.run(rec.api, rec.get_call, "wf", wf, call_vars=CALL_VARS, **kw)


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


CASES = [
    ("recorded main call passes", dict(), True),
    ("L3 workflow (no hub): reply checks only", dict(wf=L3), True),
    ("hub code_exec never completed", dict(mutate=strip_hub_complete), False),
    ("route still at its initial value", dict(mutate=vars_unchanged), False),
    ("hub_error set", dict(mutate=hub_error), False),
    ("{{bogus}} in a reply", dict(mutate=placeholder), False),
    ("HTTP 503 on turn 0", dict(mutate=http_error), False),
    ("{{bogus}} in the greet (static, before any chat turn)", dict(wf=dict(WF, nodes=dict(WF["nodes"], greet=dict(
        WF["nodes"]["greet"], on_enter={"type": "tts", "text": "Hello {{bogus}}, am I speaking with {{title}} {{last_name}}?"})))), False),
    ("simulation running: skipped, not failed", dict(sims_running=["sim1"]), True),
]

if __name__ == "__main__":
    bad = 0
    for name, kw, want in CASES:
        r = go(**kw)
        ok = r["ok"] == want and (r["signal"] == ("S7" if not want else None))
        bad += not ok
        print(("ok  " if ok else "FAIL"), name, "->", r["ok"], r["signal"], r["reason"][:120] or ("skipped" if r["skipped"] else ""))
    print("PASS" if not bad else "FAIL")
    sys.exit(1 if bad else 0)
