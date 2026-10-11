"""Hybrid L3: an L3 workflow (the LLM converses with the whole brief) plus Fork 3's gates (builder/engine/gates.py) as
code_exec tools the dialogue model must call, and a create_promise that the platform blocks unless confirm_gate granted it.

Platform facts this relies on (live probe tests/hybrid/probe.py, 2026-10-11):
- a model-called code_exec tool gets the CURRENT call's arguments in the global dict `params` (vars['<tool>_args.<name>']
  is written after the code ran: it holds the previous call's); the model sees only "Code executed successfully";
- an api_call pre_process_code runs on a model-called tool: it blocks the call by a url rewrite (nothing reaches the
  bank) and rewrites the body (probe2);
- routing is evaluated right after the tool call, on the vars the code wrote: a gate with a sentence routes to a say
  node that speaks {{gate_say}} (tts), and the customer's next turn routes back to the host node;
- a {{var}} written by code resolves in task_message from the next turn on.

    from builder import hybrid
    wf2 = hybrid.wire(l3_workflow, reducer_policy)
    python3 -m builder.hybrid <l3.workflow.json> <policy.json> <out.json>
"""
import copy, json

# The inputs of each gate tool. The prefix copies them from the call's arguments into vars and clears the ones the
# call did not give, so an old gate_date never leaks into a new check.
GATE_IN = {
    "check_terms": ("gate_product", "gate_date", "gate_amount"),
    "next_offer": ("gate_product", "gate_event"),
    "confirm": ("gate_action", "gate_terms"),
}
GATE_NAME = {"check_terms": "date_amount_gate", "next_offer": "attempt_gate", "confirm": "confirm_gate"}


def prefix(tool):
    names = GATE_IN[tool]
    return ("try:\n"
            "    _P = globals().get('params')\n"
            "    _P = _P if isinstance(_P, dict) else dict()\n"
            f"    for _k in {names!r}:\n"
            "        _v = _P.get(_k)\n"
            "        vars[_k] = '' if _v is None else str(_v)\n"
            "    if not vars.get('gate_account'):\n"
            "        for _p in ('get_account_response.data', 'get_account_data', 'get_account_response'):\n"
            "            if vars.get(_p):\n"
            "                vars['gate_account'] = vars.get(_p)\n"
            "                break\n"
            "        else:\n"
            "            _d = dict()\n"
            "            for _k in list(vars.keys()):\n"
            "                if str(_k).startswith('get_account_response.data.'):\n"
            "                    _d['t_' + str(_k)] = vars.get(_k)\n"
            "            vars.update(_d)\n"
            "except Exception as _e:\n"
            "    vars['gate_prefix_error'] = str(_e)[:150]\n")


# confirm(yes) counts only when the extraction model heard a yes after the read-back (rb_answer, reset by the read-back)
HEARD = ("try:\n"
         "    if str(vars.get('gate_action') or '').strip().lower() == 'yes' and vars.get('rb_answer') != 'yes':\n"
         "        vars['gate_action'], vars['gate_unheard'] = 'unheard', 'yes'\n"
         "except Exception:\n"
         "    pass\n")


def suffix():
    """After the gate: gate_new=yes when there is a sentence to speak (the host routes to its say node); a fresh
    read-back resets rb_answer so only a yes said AFTER it counts."""
    return ("\ntry:\n"
            "    if vars.get('gate_unheard') == 'yes':\n"
            "        vars['gate_status'], vars['gate_error'], vars['gate_unheard'] = 'stale', 'no yes heard after the read-back', 'no'\n"
            "    vars['gate_new'] = 'yes' if vars.get('gate_say') else 'no'\n"
            "    if vars.get('gate_status') in ('readback', 'repeat'):\n"
            "        vars['rb_answer'] = 'other'\n"
            "except Exception:\n"
            "    pass\n")


DESC = {
    "check_terms": "Date/amount gate. CALL it before you propose, accept or read back any date or amount. It checks business "
                   "days, holidays, the deadline and the allowed amounts. If the terms are not recordable, the system speaks the "
                   "right sentence to the customer itself.",
    "next_offer": "Offer gate. CALL it before every persuasion offer: gate_event=first for the first ask, flat after a flat no "
                  "to the open offer, too_much when the customer says the amount is too much. The system speaks the offer itself; "
                  "when no offer is left it speaks nothing and you close as refused.",
    "confirm": "Read-back gate. gate_action=readback with gate_terms=<product_id>:<amount>:<YYYY-MM-DD> (several joined with |): "
               "the system speaks the read-back with the confirm question. gate_action=yes right after the customer said yes to it. "
               "gate_action=next before each create_promise. gate_action=change when the customer changes the terms.",
}
PARAMS = {
    "gate_product": {"type": "string", "description": "the product_id exactly as get_account returned it (for example p1), or the product's position 1, 2, ..."},
    "gate_date": {"type": "string", "description": "the date as YYYY-MM-DD, or empty"},
    "gate_amount": {"type": "string", "description": "the amount, digits only, or empty"},
    "gate_event": {"type": "string", "enum": ["first", "flat", "too_much"], "description": "first | flat | too_much"},
    "gate_action": {"type": "string", "enum": ["readback", "yes", "next", "change"], "description": "readback | yes | next | change"},
    "gate_terms": {"type": "string", "description": "for readback: <product_id>:<amount>:<YYYY-MM-DD>, several joined with |"},
}
REQUIRED = {"check_terms": ["gate_product", "gate_date", "gate_amount"], "next_offer": ["gate_product", "gate_event"],
            "confirm": ["gate_action"]}

PROMPT = """

GATES (code decides these; never compute them yourself):
- Dates and amounts: EVERY time the customer names a date or an amount, call check_terms with it BEFORE you answer, even when you think it is fine or not allowed; also before you propose, accept or read back one. If it is not recordable, the system says the right sentence to the customer for you; then go on from the customer's answer.
- Offers: before every persuasion offer call next_offer (first, flat, too_much). The system says the offer. When no offer is left it says nothing: close as refused.
- Read-back: call confirm with gate_action=readback and the exact terms; the system says the read-back and the confirm question. After the customer says yes, call confirm with gate_action=yes, then confirm with gate_action=next, then create_promise (it takes the granted terms itself). Repeat next + create_promise until nothing is left. If the customer changes anything, call confirm with gate_action=change and start again with check_terms.
- A route status means this product goes to a person: transfer with the queue {{gate_queue}}, no offer, no read-back.
- Never say recorded, scheduled, booked or transferred before the tool returned ok true.
Latest gate result: status {{gate_status}}, ok {{gate_ok}}, date {{gate_out_date}}, amount {{gate_out_amount}}, sentence: {{gate_say}}

MODEL-OWNED RULES: everything else in this prompt (opening, identity, third parties, callbacks, hardship, disputes, transfers, the closing outcome and reason) is yours to follow exactly as written; the gates cover only dates, amounts, offers and the read-back."""

RB = {"name": "rb_answer", "type": "string", "enum_values": ["yes", "no", "other"], "min_confidence": 0.6,
      "description": "The customer's answer to the agent's last read-back question (Do you confirm?): yes, no, or other."}

CP_PRE = """try:
    if vars.get('gate_ok') != 'yes' or vars.get('gate_status') != 'write' or not vars.get('gate_write_date'):
        config['url'] = 'https://blocked.invalid/create_promise'
    else:
        b = config.get('body')
        b['product_id'] = vars.get('gate_write_product_id')
        b['amount'] = float(vars.get('gate_write_amount'))
        b['date'] = vars.get('gate_write_date')
except Exception:
    config['url'] = 'https://blocked.invalid/create_promise'
"""
CP_POST = """
try:
    if isinstance(result, dict):
        d = result.get('data')
        if not (isinstance(d, dict) and d.get('ok') is True):
            result['what_to_do_next'] = ('NOT saved. Do not say it is recorded. If the customer has not said yes to a read-back '
                                         'from confirm, read back again with confirm; else call create_promise once more.')
except Exception:
    pass
"""


def gate_tool(tool, rp):
    from builder.engine.gates import gate_source
    code = prefix(tool) + (HEARD if tool == "confirm" else "") + gate_source(rp, GATE_NAME[tool]) + suffix()
    props = {"code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 15000}}
    props.update({k: PARAMS[k] for k in GATE_IN[tool]})
    return {"type": "function", "config": {"timeoutMs": 20000},
            "function": {"name": tool, "handler": "__function__:code_exec", "description": DESC[tool],
                         "parameters": {"type": "object", "properties": props, "required": REQUIRED[tool]}}}


def gate_create_promise(t):
    t = copy.deepcopy(t)
    body = t["function"]["parameters"]["properties"]["body"]["properties"]
    for f, v in (("product_id", "gate_write_product_id"), ("amount", "gate_write_amount"), ("date", "gate_write_date")):
        if f in body:
            body[f]["default"] = "{{" + v + "}}"
            body[f]["description"] = "filled by the gate (confirm next); do not change"
    t["function"]["description"] = ("Records the promise that confirm granted. Call confirm with gate_action=next first; the terms "
                                    "are filled in for you. If it fails, call it once more.")
    t["pre_process_code"] = CP_PRE
    t["post_process_code"] = (t.get("post_process_code") or "") + CP_POST
    return t


def _cond(var, val):
    return {"logic": "and", "conditions": [{"variable": var, "operator": "equals", "operand": val}]}


def wire(wf, rp):
    """L3 workflow + reducer policy -> the hybrid workflow. Every node that has create_promise gets the three gate
    tools, the gated create_promise, the GATES prompt and the rb_answer extraction. The gate's sentence is spoken by
    routing, in the same turn as the tool call:
        host --(gate_new=yes)--> ack1 (code: gate_new=no) --> host_g1 (a full copy of host whose on_enter speaks {{gate_say}})
        host_g1 --(gate_new=yes)--> ack2 --> host_g2 --(gate_new=yes)--> ack1 --> host_g1 ...
    The copies converse on their own, so no turn starts with a transition back: the platform evaluates the routing
    after a tool call only when no transition was taken earlier in the turn (live proof 2), and a say node that routes
    back to the host on the next turn made every later gate sentence one turn late."""
    wf = copy.deepcopy(wf)
    nodes = wf["nodes"]
    hosts = [k for k, n in nodes.items() if any((t.get("function") or {}).get("name") == "create_promise" for t in n.get("tools") or [])]
    if not hosts:
        raise ValueError("no node with create_promise")
    gates = [gate_tool(t, rp) for t in GATE_IN]
    wf["test_variables"] = dict(wf.get("test_variables") or {}, gate_say="", gate_new="no", gate_status="none", gate_ok="no",
                                gate_out_date="", gate_out_amount="", gate_queue="")
    for h in hosts:
        n = nodes[h]
        n["tools"] = [gate_create_promise(t) if (t.get("function") or {}).get("name") == "create_promise" else t
                      for t in n["tools"]] + gates
        n["task_message"] = (n.get("task_message") or "") + PROMPT
        n["extraction_schema"] = (n.get("extraction_schema") or []) + [RB]
        orig = n.get("transitions") or []
        g1, g2, a1, a2 = h + "_g1", h + "_g2", h + "_gate_ack1", h + "_gate_ack2"
        for name in (g1, g2):
            c = copy.deepcopy(n)
            c.update(name=name, on_enter={"type": "tts", "text": "{{gate_say}}"}, on_enter_first_entry_only=False)
            nodes[name] = c
        for node, ack, to in ((h, a1, g1), (g1, a2, g2), (g2, a1, g1)):
            nodes[node]["transitions"] = [{"target_node": ack, "description": "a gate has a sentence to say",
                                           "condition": _cond("gate_new", "yes")}] + copy.deepcopy(orig)
        for ack, to in ((a1, g1), (a2, g2)):
            nodes[ack] = {
                "name": ack, "node_type": "code", "passthrough": True, "passthrough_default_transition": to, "on_enter": {"type": "silent"},
                "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec", "parameters": {
                    "type": "object", "properties": {"code": {"type": "string", "default": "vars['gate_new'] = 'no'\n"},
                                                     "timeout_ms": {"type": "number", "default": 5000}}}}}],
                "transitions": [{"target_node": to, "description": "always", "condition": {"operator": "always"}}]}
    return wf


if __name__ == "__main__":
    import sys
    w = json.load(open(sys.argv[1]))
    w = w.get("workflow", w)
    out = wire(w, json.load(open(sys.argv[2])))
    json.dump(out, open(sys.argv[3], "w"), indent=1)
    print(sys.argv[3], len(json.dumps(out)) // 1024, "KB", len(out["nodes"]), "nodes")
