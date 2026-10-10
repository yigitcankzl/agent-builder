"""PUB-07 regression for the date engine. Host = the frozen baseline Brief A workflow (fixture); the engine is wired
into its `negotiate` node, saved as slot "dateslice-a2" and the agent id is printed. Then:

    python3 tests/regress_pub07.py
    python3 tests/run_cases_env.py <agent_id> --brief A --only PUB-07 --reps 3
The host prompt's own date-table rule is replaced by a pointer to the engine (fixture-level patch only).
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya
from builder.engine import date_graph as G

POLICY = json.load(open(os.path.join(ROOT, "tests", "fixtures", "brief_a_date_policy.json")))
OLD = ("- Whenever the customer names a day, find that exact day in the calendar above (match the day of the month and "
       "the month) and do exactly what its line says. Never decide from memory whether a date is a holiday or after the deadline.")
NEW = ("- When the customer names a day, the system checks it and tells them the result. Never judge a named date yourself; "
       "follow the DATE CHECK line below. When the customer agrees to a checked date, the date to record is that line's "
       "recordable date.")

if __name__ == "__main__":
    wf = json.load(open(os.path.join(ROOT, "baseline", "example-brief-a", "brief-a.workflow.json")))
    wf = wf.get("workflow", wf)
    wf.pop("agent_config", None)
    tm = wf["nodes"]["negotiate"]["task_message"]
    assert OLD in tm, "baseline prompt changed"
    wf["nodes"]["negotiate"]["task_message"] = tm.replace(OLD, NEW)
    G.wire(wf, "negotiate", POLICY)
    print("dry run:", freya.validate_workflow("dateslice-a2", wf), file=sys.stderr)
    ids = freya.save_workflow("dateslice-a2", wf, state_file=os.path.join(ROOT, "tests", ".live-agents.json"))
    json.dump(wf, open(os.path.join(ROOT, "tests", "dateslice-a2.workflow.json"), "w"), indent=1)
    print(ids["agent_id"])
