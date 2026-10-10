"""Date engine -> Freya workflow pieces: the code-node snippet, the extraction field, and the graph wiring.

code_source(policy)       the exact string that goes into the code node (engine + policy literal + call)
extraction_field(policy)  the one normalized field the extraction model fills, anchored to the call variable now
wire(workflow, host, policy)
    adds to the conversation node `host`: the extraction field and a first transition to `date_resolve` (code);
    `date_resolve` routes  route_date == 'say' -> <host>_date_say  (tts speaks say_next verbatim)
                           otherwise           -> <host>_cont      (the dialogue model continues, with the date facts)
    Both copies keep the host's prompt, tools, extraction and transitions.
"""
import copy

from builder.engine.codegen import code_source

DATE_PATTERN = r"^([0-9]{4}-[0-9]{2}-[0-9]{2}|vague: .+)$"


def _weekday_rule(policy):
    """How the brief defines words like 'next Friday'; without a sourced rule the extractor uses the usual meaning."""
    return (policy.get("weekday_words") or {}).get("rule") or "Interpret weekday words in their usual sense."


def extraction_field(policy):
    now = "{{" + policy["now"]["var"] + "}}"
    task = (f"Today is {now}. Ignore any other notion of today's date. Fill this value only from what the CUSTOMER said "
            f"about a payment date in their last message (a date said in two parts across turns counts as one); never from "
            f"dates only the agent said. {_weekday_rule(policy)} If the customer corrected themselves, use the corrected "
            f"day. Write the exact calendar day as YYYY-MM-DD. If they named only a period or an event (next week, end "
            f"of the month, when my salary comes), write 'vague: ' followed by their words. If they named no date, "
            f"leave it empty.")
    return {"name": policy["inputs"].get("date_var", "date_said"), "type": "string", "min_confidence": 0.3,
            "validation_pattern": DATE_PATTERN, "description": "Payment date the customer named, normalized",
            "extraction_prompt": task + "\n{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n"
                                        "{{extractor.conversation.last-10}}\nLast message: {{extractor.speech}}"}


def wire(workflow, host, policy, facts_note=None):
    """Mutates and returns workflow. `host` must be a conversation node. Does not save anything."""
    nodes, field = workflow["nodes"], extraction_field(policy)
    h = nodes[host]
    say, cont = host + "_date_say", host + "_cont"
    h["extraction_schema"] = [f for f in h.get("extraction_schema") or [] if f["name"] != field["name"]] + [field]
    to_resolve = {"target_node": "date_resolve", "description": "The customer named a payment date or period",
                  "condition": {"logic": "or", "conditions": [{"variable": field["name"], "operator": "is_set"}]}}
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
