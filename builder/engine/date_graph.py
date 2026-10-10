"""Date engine -> Freya workflow pieces: the extraction fields and the graph wiring (code string: codegen.py).

extraction_fields(policy)  date_iso + date_spec, the two-field contract validated live (13/13, 6/6), with prompts
                           anchored to the call variable now and the brief's weekday-word rule from the policy
wire(workflow, host, policy)
    adds to the conversation node `host`: both fields and a first transition to `date_resolve` (code);
    `date_resolve` routes  route_date == 'say' -> <host>_date_say  (tts speaks say_next verbatim)
                           otherwise           -> <host>_cont      (the dialogue model continues, with the date facts)
    Both copies keep the host's prompt, tools, extraction and transitions. Nothing is saved to Freya here.
"""
import copy

from builder.engine.codegen import code_source

ISO_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
SPEC_PATTERN = (r"^rel=(today|tomorrow|none);d=([0-9]{1,2})?;m=([0-9]{1,2})?;wd=(mon|tue|wed|thu|fri|sat|sun)?;"
                r"wk=(this|next|after_next|none);vague=(yes|no);corr=(yes|no)$")


def _weekday_rule(policy):
    """The brief's meaning of 'next Friday' (sourced policy); without one, the usual meaning."""
    return (policy.get("weekday_words") or {}).get("rule") or "Interpret weekday words in their usual sense."


def _prompt(task):
    return (task + "\n{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n"
            "{{extractor.conversation.last-10}}\nLast message: {{extractor.speech}}")


def extraction_fields(policy):
    inp, now = policy["inputs"], "{{" + policy["now"]["var"] + "}}"
    common = (f"Today is {now}. Ignore any other notion of today's date. Only use a payment date that the CUSTOMER "
              f"named or chose in their last message (a number or date said in two parts across turns counts as one). "
              f"Do not use dates that only the agent said. If the customer corrects themselves, use the corrected value. ")
    return [
        {"name": inp.get("iso_var", "date_iso"), "type": "string", "min_confidence": 0.3, "validation_pattern": ISO_PATTERN,
         "description": "Exact payment date the customer named, YYYY-MM-DD",
         "extraction_prompt": _prompt(common + _weekday_rule(policy) + " Write the exact calendar date as YYYY-MM-DD. "
                                      "Leave it empty if the customer named only a period or an event (next week, end of "
                                      "the month, when my salary comes) or no date at all.")},
        {"name": inp.get("spec_var", "date_spec"), "type": "string", "min_confidence": 0.3, "validation_pattern": SPEC_PATTERN,
         "description": "Labels of the payment date the customer named",
         "extraction_prompt": _prompt(common + "Do NOT compute a date. Only label what the customer said, in exactly this "
                                      "format: rel=<today|tomorrow|none>;d=<day of month or empty>;m=<month number or "
                                      "empty>;wd=<mon|tue|wed|thu|fri|sat|sun or empty>;wk=<this|next|after_next|none>;"
                                      "vague=<yes if only a period or event was named, else no>;corr=<yes if they "
                                      "corrected themselves, else no>. Example: 'Monday the 26th' -> rel=none;d=26;m=;"
                                      "wd=mon;wk=none;vague=no;corr=no. Leave it empty if no date or period was named.")},
    ]


def wire(workflow, host, policy, facts_note=None):
    """Mutates and returns workflow. `host` must be a conversation node."""
    nodes, fields = workflow["nodes"], extraction_fields(policy)
    names = [f["name"] for f in fields]
    h = nodes[host]
    say, cont = host + "_date_say", host + "_cont"
    h["extraction_schema"] = [f for f in h.get("extraction_schema") or [] if f["name"] not in names] + fields
    to_resolve = {"target_node": "date_resolve", "description": "The customer named a payment date or period",
                  "condition": {"logic": "or", "conditions": [{"variable": n, "operator": "is_set"} for n in names]}}
    h["transitions"] = [to_resolve] + [t for t in h.get("transitions") or [] if t.get("target_node") != "date_resolve"]
    note = facts_note or ("DATE CHECK (computed by the system; never judge a date yourself): reason {{date_reason}}, "
                          "date that may be recorded {{accepted_date}}, deadline {{date_deadline}}.")
    for key, on_enter in ((say, {"type": "tts", "text": "{{say_next}}"}), (cont, {"type": "llm"})):
        n = copy.deepcopy(h)
        n.update(name=key, on_enter=on_enter, task_message=h.get("task_message", "") + "\n\n" + note)
        n.pop("on_enter_first_entry_only", None)
        nodes[key] = n
    h["on_enter_first_entry_only"] = True
    # one transition per target: the engine merges same-target transitions, and an `always` would swallow the rest
    nodes["date_resolve"] = {
        "name": "date_resolve", "node_type": "code", "passthrough": True, "passthrough_default_transition": cont,
        "on_enter": {"type": "silent"},
        "pre_actions": [{"type": "function", "function": {
            "name": "code_exec", "handler": "__function__:code_exec",
            "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code_source(policy)},
                                                            "timeout_ms": {"type": "number", "default": 10000}}}}}],
        "transitions": [
            {"target_node": say, "description": "speak the date decision",
             "condition": {"logic": "or", "conditions": [{"variable": "route_date", "operator": "equals", "operand": "say"}]}},
            {"target_node": cont, "description": "always", "condition": {"operator": "always"}}]}
    return workflow
