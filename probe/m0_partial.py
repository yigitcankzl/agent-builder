"""M0 items 8 and 9 (chat API only, few turns).
 8) partial utterance with ONE composite event field (n, act, date labels, part flag): "the twenty-" then "seventh".
 9) silence: can a transition into on_enter llm give an empty turn; does on_enter tts with an EMPTY say_next speak?
    python3 probe/m0_partial.py
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "probe"))
import m0_probe as P
from m0_probe import freya, chat, evidence, STATE

EV = dict(P.EV)
EV["validation_pattern"] = (r"^n=[a-z0-9]{1,8};act=(yes|no|refuse|propose|empty_say|llm_say|other);"
                            r"d=([0-9]{1,2})?;m=([0-9]{1,2})?;part=(yes|no)$")
EV["description"] = "A code label n=<code>;act=<label>;d=<day>;m=<month>;part=<yes|no>, for example n=kqwrtz;act=propose;d=27;m=;part=no."
EV["extraction_prompt"] = (
    "Code: {{ev_tok}}. Label ONLY the customer's last message (use earlier customer messages only to complete a number "
    "or date they split across turns). Write exactly n=<copy the code above>;act=<propose if they name or complete a "
    "payment day, no, yes, empty_say (they ask for the empty test), llm_say (they ask for the free test), other>;"
    "d=<day of month or empty>;m=<month number or empty>;part=<yes if the day is cut off and not complete yet, else no>. "
    "Never compute dates. If the day is cut off, leave d empty and write part=yes. Examples: code kbmtpq, 'on the "
    "twenty-' -> n=kbmtpq;act=other;d=;m=;part=yes. Code kxzrwa, after 'the twenty-' the customer says 'seventh' -> "
    "n=kxzrwa;act=propose;d=27;m=;part=no.\n{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n"
    "{{extractor.conversation.last-10}}\nLast message: {{extractor.speech}}")

HUB = P.HUB.replace("""        elif act == 'brace':""", """        elif act == 'propose':
            say = 'PROBE day ' + parts.get('d', '') + ' month ' + parts.get('m', '') + ' part ' + parts.get('part', '')
        elif act == 'empty_say':
            say = ''
            route = 'say_forced'
        elif act == 'llm_say':
            route = 'talk'
        elif act == 'brace':""").replace("""    if route == 'talk' and say:
        route = 'say'""", """    if route == 'talk' and say:
        route = 'say'
    if route == 'say_forced':
        route = 'say'""").replace("""            say = 'PROBE nothing to count. Refusals still ' + str(refusals) + '.'""",
                                  """            say = 'PROBE other: part ' + parts.get('part', '') + ' d ' + parts.get('d', '')""")

if __name__ == "__main__":
    wf = P.workflow(HUB)
    for k in ("talk", "talk_llm", "exact_say"):
        wf["nodes"][k]["extraction_schema"] = [EV]
    print("dry run:", freya.validate_workflow("m0-partial", wf))
    ids = freya.save_workflow("m0-partial", wf, state_file=STATE)
    msgs = ["Hi", "I can't pay today.", "I can pay on the twenty-", "seventh", "Run the empty test.", "Do the free test.", "Do the free test."]
    call, out = chat(ids["workflow_id"], msgs, {"customer_id": "c_m0", "now": "2026-10-14T11:00"})
    c, vt = evidence(call, "m0_partial")
    print("CALL", call)
    for m in c["messages"]:
        t = str(m.get("message"))
        if m.get("role") in ("user", "assistant"):
            print("   ", m["role"], m.get("nodeId"), "|", repr(t[:90]))
        elif m.get("role") == "system":
            try: e = json.loads(t)
            except Exception: continue
            if e.get("event") in ("variable_extracted", "extraction_failed", "error") or "speak" in t:
                print("      ", e.get("event"), repr(str(e.get("value") or e.get("message") or e)[:120]))
    for row in json.loads(vt.get("m0_log") or "[]"):
        print("  hub", row)
