"""Live check of the date engine on Freya via the chat API (no simulation). Fixture policy, one fresh call per script.

    source env.sh && python3 tests/live_date_chat.py
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401  (loads env.sh)
import freya
from builder.engine import date_graph as G

POLICY = json.load(open(os.path.join(ROOT, "tests", "fixtures", "brief_a_date_policy.json")))
SCRIPTS = [  # (now, days_late, customer turns, expected (date_reason, accepted_date) after the last turn)
    ("2026-10-14T11:00", 5, ["I can't pay today.", "Monday the 26th"], ("non_business_day", "2026-10-27")),
    ("2026-10-14T11:00", 5, ["I can't pay today.", "Monday the 26th", "Yes, Tuesday works"], ("ok", "2026-10-27")),
    ("2026-10-14T11:00", 14, ["Not today.", "On the sixth of November"], ("after_deadline", "2026-10-23")),
    ("2026-10-14T11:00", 5, ["Not today.", "Next Friday"], ("ok", "2026-10-23")),
    ("2026-10-16T11:00", 5, ["Not today.", "Next Friday"], ("ok", "2026-10-23")),
    ("2026-10-14T11:00", 5, ["Not today.", "Two weeks later"], ("vague", "")),
    ("2026-10-14T11:00", 5, ["Not today.", "On the twenty", "first, sorry, I mean the twentieth"], ("ok", "2026-10-20")),
    ("2026-12-30T10:00", 5, ["Not today.", "On the first of January"], ("non_business_day", "2027-01-04")),
    ("2026-10-30T10:00", 5, ["Not today.", "Tomorrow"], ("non_business_day", "2026-11-02")),
    ("2026-11-20T10:00", 5, ["Not today.", "On the 3rd"], ("ok", "2026-12-03")),
]
WF = {"initial_node": "talk", "system_prompt": "You are a bank's digital assistant. English. One or two short sentences.",
      "nodes": {"talk": {"name": "talk", "node_type": "conversation", "max_node_turns": 30,
                         "task_message": "Ask when the customer can pay the overdue amount. No tool call is allowed.",
                         "transitions": []}}}

if __name__ == "__main__":
    wf = G.wire(json.loads(json.dumps(WF)), "talk", POLICY)
    print("dry run:", freya.validate_workflow("datelive", wf))
    ids = freya.save_workflow("datelive", wf, state_file=os.path.join(ROOT, "tests", ".live-agents.json"))
    ok = 0
    for now, late, turns, exp in SCRIPTS:
        call = None
        for msg in ["Hello?"] + turns:
            body = {"workflowId": ids["workflow_id"], "message": msg,
                    "customerVariables": {"now": now, "days_late": str(late), "customer_id": "c_live"}}
            if call: body["callId"] = call
            r = freya.api("POST", "/api/v2/chat/message", body); call = r.get("callId", call)
            print(f"  USER: {msg}\n  AGENT: {r.get('response')}")
        try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception: pass
        time.sleep(2)
        vt = {}
        for m in freya.get_call(call)["messages"]:
            vt.update({k: x.get("value") for k, x in ((m.get("workflowSnapshot") or {}).get("variableTable") or {}).items()})
        got = (vt.get("date_reason"), vt.get("accepted_date") or "")
        good = got == exp; ok += good
        print(("OK " if good else "BAD"), now[:10], turns[-1], "| got", got, "exp", exp, "| iso", vt.get("date_iso"), "spec", vt.get("date_spec"), "\n")
    print(f"{ok}/{len(SCRIPTS)}")
