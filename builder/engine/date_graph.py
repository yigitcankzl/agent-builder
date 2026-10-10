"""Emit the date engine into a Freya workflow: extraction fields, the code node, and the say/continue node copies.

wire(workflow, host, policy) adds to the conversation node `host`:
  - two extraction fields (date_iso, date_spec) with custom extraction prompts anchored to the call variable `now`;
  - a first transition to `date_resolve` (code) whenever a date field is set;
  - `date_resolve` runs builder/engine/dates.py with the policy and routes:
        a new decision to announce -> <host>_date_say  (tts speaks the code's sentence, no model choice)
        otherwise (same as before, ok date, error) -> <host>_cont  (LLM answers, with the date facts)
  - the two copies keep the host's prompt, tools, extraction and transitions.
"""
import copy, json, os

ENGINE_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dates.py")
SPEC_PATTERN = r"^rel=(today|tomorrow|none);d=([0-9]{1,2})?;m=([0-9]{1,2})?;wd=(mon|tue|wed|thu|fri|sat|sun)?;wk=(this|next|after_next|none);vague=(yes|no);corr=(yes|no)$"


def _weekday_rule(policy):
    if policy.get("next_weekday") == "following_week":
        return ("'Next <weekday>' means that weekday in the following calendar week (Monday to Sunday), even if it is "
                "sooner; 'this <weekday>' or a bare weekday means the current calendar week, or the coming one if that "
                "day has passed.")
    return "'Next <weekday>' means the next occurrence after today; 'this <weekday>' or a bare weekday means the coming one."


def _prompt(task):
    return (task + "\n{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n"
            "{{extractor.conversation.last-10}}\nLast message: {{extractor.speech}}")


def extraction_fields(policy):
    now = "{{" + policy.get("now_var", "now") + "}}"
    common = (f"Today is {now}. Ignore any other notion of today's date. Only use a payment date that the CUSTOMER "
              f"named or chose in their last message (a number or date said in two parts across turns counts as one). "
              f"Do not use dates that only the agent said. If the customer corrects themselves, use the corrected value. ")
    return [
        {"name": "date_iso", "type": "string", "min_confidence": 0.3, "validation_pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
         "description": "Exact payment date the customer named, YYYY-MM-DD",
         "extraction_prompt": _prompt(common + _weekday_rule(policy) + " Write the exact calendar date as YYYY-MM-DD. "
                                      "Leave it empty if the customer named only a period or an event (next week, end of "
                                      "the month, when my salary comes) or no date at all.")},
        {"name": "date_spec", "type": "string", "min_confidence": 0.3, "validation_pattern": SPEC_PATTERN,
         "description": "Labels of the payment date the customer named",
         "extraction_prompt": _prompt(common + "Do NOT compute a date. Only label what the customer said, in exactly this "
                                      "format: rel=<today|tomorrow|none>;d=<day of month or empty>;m=<month number or "
                                      "empty>;wd=<mon|tue|wed|thu|fri|sat|sun or empty>;wk=<this|next|after_next|none>;"
                                      "vague=<yes if only a period or event was named, else no>;corr=<yes if they "
                                      "corrected themselves, else no>. Example: 'Monday the 26th' -> rel=none;d=26;m=;"
                                      "wd=mon;wk=none;vague=no;corr=no. Leave it empty if no date or period was named.")},
    ]


def _break_braces(s):
    while "{{" in s or "}}" in s:
        s = s.replace("{{", "{ {").replace("}}", "} }")
    return s


def code_source(policy):
    """The code-node snippet: engine source, the policy as a JSON literal, and the call. Contains no double braces."""
    src = open(ENGINE_SRC).read()
    lit = json.dumps(_break_braces(json.dumps(policy, ensure_ascii=True)))
    code = src + "\n\nPOLICY = json.loads(" + lit + ")\nrun_safe(vars, POLICY)\n"
    if "{{" in code or "}}" in code:
        raise ValueError("code node source contains double braces")
    return code


def _var_cond(var, op, operand=None):
    c = {"variable": var, "operator": op}
    if operand is not None:
        c["operand"] = operand
    return c


def wire(workflow, host, policy, facts_note=None):
    """Mutates and returns workflow. `host` must be a conversation node."""
    nodes = workflow["nodes"]
    h = nodes[host]
    say, cont = host + "_date_say", host + "_cont"
    h["extraction_schema"] = list(h.get("extraction_schema") or []) + extraction_fields(policy)
    to_resolve = {"target_node": "date_resolve", "description": "The customer named a payment date or period",
                  "condition": {"logic": "or", "conditions": [_var_cond("date_iso", "is_set"), _var_cond("date_spec", "is_set")]}}
    h["transitions"] = [to_resolve] + [t for t in h.get("transitions") or [] if t.get("target_node") != "date_resolve"]
    note = facts_note or ("DATE CHECK (computed by the system, trust it): {{date_facts}}. Dates are checked for you: never "
                          "decide yourself whether a date is allowed. If the customer agrees to a date, the date to record "
                          "is {{date_record}} (YYYY-MM-DD) when it is set.")
    for key, on_enter in ((say, {"type": "tts", "text": "{{say_next}}"}), (cont, {"type": "llm"})):
        n = copy.deepcopy(h)
        n["name"] = key
        n["on_enter"] = on_enter
        n.pop("on_enter_first_entry_only", None)
        n["task_message"] = h.get("task_message", "") + "\n\n" + note
        nodes[key] = n
    h["on_enter_first_entry_only"] = True
    nodes["date_resolve"] = {
        "name": "date_resolve", "node_type": "code", "passthrough": True, "passthrough_default_transition": cont,
        "on_enter": {"type": "silent"},
        "pre_actions": [{"type": "function", "function": {
            "name": "code_exec", "handler": "__function__:code_exec",
            "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code_source(policy)},
                                                            "timeout_ms": {"type": "number", "default": 10000}}}}}],
        # one transition per target: the engine merges same-target transitions, and an `always` would swallow the rest
        "transitions": [
            {"target_node": say, "description": "announce the date decision",
             "condition": {"logic": "or", "conditions": [_var_cond("date_route", "equals", "say")]}},
            {"target_node": cont, "description": "always", "condition": {"operator": "always"}}]}
    return workflow
