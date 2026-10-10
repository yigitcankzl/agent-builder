"""Probe: how well does Freya's extraction (experimental-5) turn spoken dates into ISO, anchored to the call variable
`now` instead of the real clock? Compares a string field anchored with {{now}}, structured component fields, and the
built-in `type: date` (real-clock anchored). Chat API only, one fresh call per utterance.

    source env.sh && python3 probe/date_extraction_probe.py
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import freya

NOW = "2026-10-14T11:00"   # a Wednesday; the real clock today is different, on purpose
CASES = [  # utterance, expected iso ('' = vague), note
    ("I can pay on the 26th", "2026-10-26", "day only"),
    ("Monday the 26th", "2026-10-26", "weekday+day"),
    ("Next Friday", "2026-10-23", "next = following calendar week"),
    ("This Friday", "2026-10-16", "this = current week"),
    ("Friday", "2026-10-16", "bare weekday"),
    ("Tomorrow", "2026-10-15", "relative"),
    ("The week after next", "", "vague"),
    ("When my salary comes", "", "vague"),
    ("The twenty-second of October", "2026-10-22", "in words"),
    ("On the 21st, sorry, I mean the 20th", "2026-10-20", "correction"),
    ("6 November", "2026-11-06", "other month"),
    ("End of the month", "", "vague"),
    ("Today", "2026-10-14", "today"),
]
S = lambda **k: {"min_confidence": 0.3, **k}
SCHEMA = [
    S(name="date_iso", type="string", validation_pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
      description="The exact calendar date the customer just named for paying, as YYYY-MM-DD. Today is {{now}} (ignore the real clock). 'Next <weekday>' means that weekday in the following calendar week; 'this <weekday>' or a bare weekday means the current week. If the customer corrects themselves, use the corrected date. Leave empty if the customer named no exact day (e.g. 'next week', 'when my salary comes', 'end of the month')."),
    S(name="date_iso_custom", type="string", validation_pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$", description="Exact payment date as YYYY-MM-DD",
      extraction_prompt="Today is {{now}}. Ignore any other notion of today's date. 'Next <weekday>' means that weekday in the following calendar week; 'this <weekday>' or a bare weekday means the current week (Monday to Sunday). If the customer corrects themselves, use the corrected date. Leave the value empty if no exact day was named.\n{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n{{extractor.conversation.last-10}}\nLast message: {{extractor.speech}}"),
    S(name="date_vague", type="string", enum_values=["yes", "no"], description="yes if the customer named only a period or event, not an exact day"),
    S(name="day_of_month", type="integer", description="Day of the month the customer named, if any"),
    S(name="month", type="integer", description="Month number (1-12) the customer named, if any"),
    S(name="weekday", type="string", enum_values=["mon", "tue", "wed", "thu", "fri", "sat", "sun"], description="Weekday the customer named, if any"),
    S(name="week_ref", type="string", enum_values=["this", "next", "after_next", "none"], description="Which week the customer referred to"),
    S(name="relative_day", type="string", enum_values=["today", "tomorrow", "none"], description="today or tomorrow if said"),
    S(name="date_builtin", type="date", description="The payment date the customer named"),
]
WF = {"initial_node": "talk", "system_prompt": "Test assistant. English. One short sentence.",
      "test_variables": {"now": NOW},
      "nodes": {"talk": {"name": "talk", "node_type": "conversation", "task_message": "Ask when the customer can pay. No tool call is allowed.",
                         "extraction_schema": SCHEMA, "max_node_turns": 30, "transitions": []}}}

if __name__ == "__main__":
    print("dry run:", freya.validate_workflow("dateprobe", WF))
    ids = freya.save_workflow("dateprobe", WF, state_file=os.path.join(os.path.dirname(__file__), ".freya-agents.json"))
    rows = []
    for utt, exp, note in CASES:
        call = None
        for msg in ["Hello, who is this?", utt]:
            body = {"workflowId": ids["workflow_id"], "message": msg, "customerVariables": {"now": NOW, "customer_id": "c_probe"}}
            if call: body["callId"] = call
            call = freya.api("POST", "/api/v2/chat/message", body).get("callId", call)
        try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception: pass
        time.sleep(2)
        msgs = freya.get_call(call)["messages"]
        ex = {}
        for m in msgs:
            if m.get("role") == "system" and '"variable_extracted"' in str(m.get("message")):
                e = json.loads(m["message"]); ex[e["name"]] = e.get("value")
        rows.append({"utt": utt, "expected": exp, "note": note, "extracted": ex})
        ok = (ex.get("date_iso") or "") == exp
        print(("OK  " if ok else "BAD ") + f"{utt!r:42} exp={exp or 'vague':10} iso={ex.get('date_iso')!s:10} vague={ex.get('date_vague')} "
              f"d={ex.get('day_of_month')} m={ex.get('month')} wd={ex.get('weekday')} wk={ex.get('week_ref')} rel={ex.get('relative_day')} builtin={ex.get('date_builtin')} custom={ex.get('date_iso_custom')}")
    json.dump(rows, open(os.path.join(os.path.dirname(__file__), "date_extraction_results.json"), "w"), indent=1)
