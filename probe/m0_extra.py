"""M0 extras (chat API + direct mock calls, no simulation):
  a) a ~60 KB code node saves and runs (same hub, padded);
  b) '}}' inside a variable value substituted into a PROMPT (the tts case is in m0_probe.py);
  c) what a second close_call does on the mock bank.
    python3 probe/m0_extra.py
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "probe"))
import m0_probe as P
from m0_probe import freya, http, chat, evidence, STATE, MOCK

if __name__ == "__main__":
    # a) 60 KB code node
    pad = "".join(f"# padding line {i:05d} " + "x" * 50 + "\n" for i in range(900))
    big = P.HUB.replace("import json, datetime\n", "import json, datetime\n" + pad, 1)
    print("code size", len(big))
    wf = P.workflow(big)
    # b) prompt substitution of a value with braces: talk_llm repeats the value it is given
    wf["nodes"]["talk_llm"]["task_message"] = "Reply in one short sentence. Then quote this text exactly: [[{{say_next}}]]. No tool call is allowed."
    print("dry run:", freya.validate_workflow("m0-big", wf))
    ids = freya.save_workflow("m0-big", wf, state_file=STATE)
    stored = freya.api("GET", f"/api/v2/workflow/{ids['workflow_id']}", workspaceId=freya.workspace_id())["workflow"]["workflow"]
    sc = stored["nodes"]["hub"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    print("stored code size", len(sc), "identical", sc == big)
    call, out = chat(ids["workflow_id"], ["Hi", "No.", "Do the brace test.", "No."], {"customer_id": "c_m0", "now": "2026-10-14T11:00"})
    c, vt = evidence(call, "m0_big")
    print("CALL", call, "hub_runs", vt.get("hub_runs"), "refusals", vt.get("refusals"), "error", vt.get("m0_error"))
    # c) close_call twice on a fresh practice session
    sess = http("/v1/practice/sessions", {"case": "PUB-02"})["variables"]
    r1 = http("/v1/close_call", {"customer_id": sess["customer_id"], "outcome": "not_reached", "reason": "unclear"})
    r2 = http("/v1/close_call", {"customer_id": sess["customer_id"], "outcome": "no_promise", "reason": "refused"})
    led = http("/v1/practice/ledger/" + sess["customer_id"])
    print("close 1:", r1, "\nclose 2:", r2, "\nledger outcome:", led.get("outcome"), led.get("reason"), "calls:", [x["tool"] for x in led.get("calls", [])])
    json.dump({"close1": r1, "close2": r2, "ledger": led}, open(os.path.join(P.OUT, "m0_close_twice.json"), "w"), indent=1)
