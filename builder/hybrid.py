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
            "    import json as _json\n"
            "    _P = globals().get('params')\n"
            "    _P = _P if isinstance(_P, dict) else dict()\n"
            f"    for _k in {names!r}:\n"
            "        _v = _P.get(_k)\n"
            "        vars[_k] = '' if _v is None else str(_v)\n"
            "    vars['gate_bad_product'] = ''\n"
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
            + PRODUCT_FIX +
            "except Exception as _e:\n"
            "    vars['gate_prefix_error'] = str(_e)[:150]\n")


# The model sometimes invents a product id (credit_card_4821, cc_4821, prod_123: live proof 1). _fix maps a reference
# to a real product_id: exact id, then a card_last4 inside it, then a unique product type word, then a position, then
# the only product. An unknown one is kept (the gate rejects it) and gate_bad_product names the valid ids; the suffix
# puts that into gate_error, which the next turn's prompt shows.
PRODUCT_FIX = (
    "    _rows = dict()\n"
    "    for _k in list(vars.keys()):\n"
    "        _s = str(_k)\n"
    "        if _s.startswith('get_account_response.data.products.'):\n"
    "            _p = _s[len('get_account_response.data.products.'):].split('.')\n"
    "            if len(_p) == 2 and _p[0].isdigit():\n"
    "                _rows.setdefault(int(_p[0]), dict())[_p[1]] = str(vars.get(_k))\n"
    "    if not _rows:\n"
    "        try:\n"
    "            _a = vars.get('gate_account')\n"
    "            _a = _json.loads(_a) if isinstance(_a, str) else _a\n"
    "            _a = _a.get('data', _a) if isinstance(_a, dict) and 'products' not in _a else _a\n"
    "            for _i, _r in enumerate((_a or dict()).get('products') or []):\n"
    "                _rows[_i] = dict((str(_x), str(_y)) for _x, _y in _r.items())\n"
    "        except Exception:\n"
    "            pass\n"
    "    _rows = [_rows[_i] for _i in sorted(_rows)]\n"
    "    _ids = [_r.get('product_id', '') for _r in _rows]\n"
    "    _words = dict(credit_card=('credit', 'card'), personal_loan=('personal',), car_loan=('car',))\n"
    "    def _fix(ref):\n"
    "        ref = str(ref or '').strip()\n"
    "        if not _rows or ref in _ids:\n"
    "            return ref\n"
    "        low = ref.lower()\n"
    "        for pick in ([r for r in _rows if r.get('card_last4') and r['card_last4'] in low],\n"
    "                     [r for r in _rows if any(w in low for w in _words.get(r.get('type', ''), (r.get('type') or '#',)))]):\n"
    "            if len(pick) == 1:\n"
    "                return pick[0].get('product_id', '')\n"
    "        if ref.isdigit() and 0 < int(ref) <= len(_rows):\n"
    "            return _rows[int(ref) - 1].get('product_id', '')\n"
    "        if len(_rows) == 1:\n"
    "            return _rows[0].get('product_id', '')\n"
    "        vars['gate_bad_product'] = 'product ' + ref + ' is not a product_id; use one of: ' + ', '.join(_ids)\n"
    "        return ref\n"
    "    if vars.get('gate_product'):\n"
    "        vars['gate_product'] = _fix(vars.get('gate_product'))\n"
    "    if vars.get('gate_terms'):\n"
    "        _t = []\n"
    "        for _x in str(vars.get('gate_terms')).split('|'):\n"
    "            _f = _x.strip().split(':')\n"
    "            if len(_f) == 3:\n"
    "                _f[0] = _fix(_f[0])\n"
    "            _t.append(':'.join(_f))\n"
    "        vars['gate_terms'] = '|'.join(_t)\n")


# confirm takes only readback | change. The permission to write is checked by create_promise's own pre hook at the
# moment of the write (CP_PRE: a standing read-back + a yes heard after it). The earlier confirm(yes) + confirm(next)
# were called IN PARALLEL by the model (live brief-a pieces PUB-04 efb148d6, PUB-07 c0f77eb4, PUB-10 eb3138d7): both gate
# runs raced on gate_st, nothing was granted, create_promise was never called, the call closed as service_error.
# A stray yes / next is a no-op.
HEARD = ("try:\n"
         "    if str(vars.get('gate_action') or '').strip().lower() in ('yes', 'next'):\n"
         "        vars['gate_action'], vars['gate_noop'] = 'noop', 'yes'\n"
         "except Exception:\n"
         "    pass\n")


def suffix():
    """After the gate: gate_new=yes when there is a sentence to speak (the host routes to its say node); a fresh
    read-back resets rb_answer so only a yes said AFTER it counts."""
    return ("\ntry:\n"
            "    if vars.get('gate_noop') == 'yes':\n"
            "        vars['gate_status'], vars['gate_error'], vars['gate_noop'] = 'noop', '', 'no'\n"
            "    if vars.get('gate_bad_product'):\n"
            "        vars['gate_error'] = vars.get('gate_bad_product')\n"
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
               "the system speaks the read-back with the confirm question. gate_action=change when the customer changes the terms. "
               "After the customer's yes, call create_promise directly (no confirm call).",
}
PARAMS = {
    "gate_product": {"type": "string", "description": "the product_id exactly as get_account returned it (for example p1), or the product's position 1, 2, ..."},
    "gate_date": {"type": "string", "description": "the date as YYYY-MM-DD, or empty"},
    "gate_amount": {"type": "string", "description": "the amount, digits only, or empty"},
    "gate_event": {"type": "string", "enum": ["first", "flat", "too_much"], "description": "first | flat | too_much"},
    "gate_action": {"type": "string", "enum": ["readback", "change"], "description": "readback | change"},
    "gate_terms": {"type": "string", "description": "for readback: <product_id>:<amount>:<YYYY-MM-DD>, several joined with |"},
}
REQUIRED = {"check_terms": ["gate_product", "gate_date", "gate_amount"], "next_offer": ["gate_product", "gate_event"],
            "confirm": ["gate_action"]}

PROMPT = """

GATES (code decides these; never compute them yourself):
- Dates and amounts: EVERY time the customer names a date or an amount, call check_terms with it BEFORE you answer, even when you think it is fine or not allowed; also before you propose, accept or read back one. If it is not recordable, the system says the right sentence to the customer for you; then go on from the customer's answer.
- Offers: before every persuasion offer call next_offer (first, flat, too_much). The system says the offer. When no offer is left it says nothing: close as refused.
- Read-back: call confirm with gate_action=readback and the exact terms; the system says the read-back and the confirm question. After the customer says yes, call create_promise with the product_id, once per product in the read-back, one call at a time (it takes the confirmed amount and date itself). If the customer changes anything, call confirm with gate_action=change and start again with check_terms.
- Products: gate_product and the product in gate_terms are the product_id EXACTLY as get_account returned it (for example p1), never a name, type or card number. If the gate error names the valid ids, call the gate again with one of them.
- A route status means this product goes to a person: transfer with the queue {{gate_queue}}, no offer, no read-back.
- Never say recorded, scheduled, booked or transferred before the tool returned ok true.
- One tool call at a time: wait for each result before the next call.
- A missing confirmation is never a failure: if create_promise says the terms were not confirmed, read the terms back with confirm (gate_action=readback) and ask again. Do not close the call and do not say it could not be saved. service_error only when the bank itself failed twice.
- If the customer changes the terms and then goes back to the earlier ones, call confirm with gate_action=readback and those terms; the system reads them back and the customer confirms again.
Latest gate result: status {{gate_status}}, ok {{gate_ok}}, date {{gate_out_date}}, amount {{gate_out_amount}}, sentence: {{gate_say}}, error: {{gate_error}}

MODEL-OWNED RULES: everything else in this prompt (opening, identity, third parties, callbacks, hardship, disputes, transfers, the closing outcome and reason) is yours to follow exactly as written; the gates cover only dates, amounts, offers and the read-back."""

RB = {"name": "rb_answer", "type": "string", "enum_values": ["yes", "no", "other"], "min_confidence": 0.6,
      "description": "The customer's answer to the agent's last read-back question (Do you confirm?). yes ONLY for an explicit "
                     "yes, I confirm, or correct to that read-back. no for a no. other for everything else, including OK, fine, "
                     "bye, a question, or an answer to anything that is not the read-back."}

# The write permission, checked at the moment of the write: a standing (not voided) read-back from confirm, and a yes
# the extraction heard after it (rb_answer, which every read-back resets). The body takes the read-back's terms for
# the product the model names (or the only one); nothing else the model sends is used.
CP_PRE = """try:
    import json as _json
    st = vars.get('gate_st')
    st = _json.loads(st) if isinstance(st, str) and st else (st if isinstance(st, dict) else dict())
    rb = st.get('_rb') or dict()
    terms = rb.get('terms') or []
    b = config.get('body')
    pid = str(b.get('product_id') or '').strip()
    pick = [t for t in terms if str(t[0]) == pid] or (terms if len(terms) == 1 else [])
    if not terms or rb.get('voided') or vars.get('rb_answer') != 'yes':
        config['url'] = 'https://blocked.invalid/create_promise'
    elif not pick:
        config['url'] = 'https://blocked.invalid/product/' + ','.join(str(t[0]) for t in terms)
    else:
        b['product_id'], b['amount'], b['date'] = str(pick[0][0]), float(pick[0][1]), str(pick[0][2])
except Exception:
    config['url'] = 'https://blocked.invalid/create_promise'
"""
CP_POST = """
try:
    if isinstance(result, dict):
        d = result.get('data')
        if 'blocked.invalid/product/' in str(result):
            ids = str(result).split('blocked.invalid/product/')[1].split("'")[0].split('"')[0]
            result.pop('error', None)
            result['status'] = 'wrong_product'
            result['what_to_do_next'] = 'NOT saved, NOT a failure: call create_promise again with product_id one of: ' + ids
        elif 'blocked.invalid' in str(result):
            result.pop('error', None)
            result['status'] = 'not_confirmed'
            result['message'] = 'Not sent to the bank: these terms have no confirmed read-back. This is NOT a service error.'
            if isinstance(d, dict):
                d.pop('what_to_do_next', None)
            result['what_to_do_next'] = ('NOT saved, and NOT a failure: call confirm with gate_action=readback and the current '
                                         'terms, and ask the customer to confirm. Do not close the call and do not use service_error.')
        elif not (isinstance(d, dict) and d.get('ok') is True):
            result['what_to_do_next'] = ('NOT saved by the bank. Do not say it is recorded. Call create_promise once more; if '
                                         'the bank fails again, the outcome is service_error.')
except Exception:
    pass
"""


def once_lines(rp):
    """The lines the brief allows once, from the policy's events (their effect says once / one sentence / no
    persuasion / no attempts): {topic: {after, close, np, quote}}. np: after it, no persuasion offer is allowed."""
    import re
    out = {}
    for e in rp.get("events") or []:
        eff = str(e.get("effect") or "")
        if not e.get("topic") or not re.search(r"\bonce\b|one (short )?sentence|no persuasion|no attempts", eff, re.I):
            continue
        close = "/".join(x for x in (e.get("outcome"), e.get("reason")) if x)
        out[e["topic"]] = {"after": eff + (f"; close as {close}" if close else ""), "close": close,
                           "np": bool(re.search(r"no persuasion|no attempts", eff, re.I)),
                           "quote": ((e.get("source") or [{}])[0] or {}).get("quote") or ""}
    return out


def once_tool(lines):
    """say_once(line): the first call allows the line (the model says it); a repeat is refused, with what to do instead
    in gate_error (shown in the prompt). A no-persuasion line also sets gate_np, which blocks next_offer."""
    cat = {k: {"after": v["after"], "np": v["np"]} for k, v in lines.items()}
    code = ("import json as _json\n"
            f"_L = _json.loads({json.dumps(json.dumps(cat))})\n"
            "try:\n"
            "    _P = globals().get('params')\n"
            "    _line = str((_P if isinstance(_P, dict) else dict()).get('line') or '').strip()\n"
            "    _used = _json.loads(vars.get('gate_once') or '[]')\n"
            "    vars['gate_say'], vars['gate_new'], vars['gate_ok'] = '', 'no', 'no'\n"
            "    if _line not in _L:\n"
            "        vars['gate_status'], vars['gate_error'] = 'unknown_line', 'say_once line must be one of: ' + ', '.join(_L)\n"
            "    elif _line in _used:\n"
            "        vars['gate_status'] = 'already_said'\n"
            "        vars['gate_error'] = ('ALREADY SAID ONCE (' + _line + '): do not say or offer it again. Instead: ' + _L[_line]['after'])\n"
            "    else:\n"
            "        _used.append(_line)\n"
            "        vars['gate_once'] = _json.dumps(_used)\n"
            "        vars['gate_status'], vars['gate_ok'], vars['gate_error'] = 'once_ok', 'yes', ''\n"
            "    if _line in _L and _L[_line]['np']:\n"
            "        vars['gate_np'] = _line\n"
            "except Exception as _e:\n"
            "    vars['gate_status'], vars['gate_error'] = 'error', str(_e)[:150]\n")
    return {"type": "function", "config": {"timeoutMs": 10000},
            "function": {"name": "say_once", "handler": "__function__:code_exec",
                         "description": ("Lines the brief allows ONCE per call: " + "; ".join(f"{k}: {v['after']}" for k, v in lines.items()) +
                                         ". CALL say_once with the line BEFORE you say it (sympathy, the support offer, ...). "
                                         "If the latest gate result says ALREADY SAID, do not say it again; do what it says instead."),
                         "parameters": {"type": "object", "properties": {
                             "code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 5000},
                             "line": {"type": "string", "enum": list(lines), "description": "one of: " + ", ".join(lines)}},
                             "required": ["line"]}}}


# next_offer only: (1) after a no-persuasion line (hardship ...) no offer is made at all: the gate state is restored and
# the model is told the close instead; (2) an open offer is re-said at most once: a further 'first' becomes 'flat' (the
# next attempt), so a talkative customer's non-answers move the call on instead of looping (live PUB-06 89957a2d).
def offer_guard(lines):
    np = {k: v["after"] for k, v in lines.items() if v["np"]}
    pre = ("try:\n"
           "    vars['_np_block'], vars['_st_backup'] = '', vars.get('gate_st') or ''\n"
           f"    _NP = _json.loads({json.dumps(json.dumps(np))})\n"
           "    if vars.get('np_topic') == 'yes' and _NP and not vars.get('gate_np'):\n"
           "        vars['gate_np'] = list(_NP)[0]\n"
           "    if vars.get('gate_np') in _NP:\n"
           "        vars['_np_block'] = _NP[vars['gate_np']]\n"
           "    _ev = str(vars.get('gate_event') or 'first')\n"
           "    _fn = vars.get('gate_first_n')\n"
           "    _fn = _json.loads(_fn) if isinstance(_fn, str) and _fn.startswith('{') else dict()\n"
           "    _pk = str(vars.get('gate_product') or '')\n"
           "    _n = int(_fn.get(_pk) or 0)\n"
           "    if _ev == 'first':\n"
           "        _n += 1\n"
           "        if _n > 2:\n"
           "            vars['gate_event'], _n = 'flat', 1\n"
           "    else:\n"
           "        _n = 1\n"
           "    _fn[_pk] = _n\n"
           "    vars['gate_first_n'] = _json.dumps(_fn)\n"
           "except Exception:\n"
           "    pass\n")
    post = ("try:\n"
            "    if vars.get('_np_block'):\n"
            "        vars['gate_st'] = vars.get('_st_backup') or vars.get('gate_st')\n"
            "        vars['gate_status'], vars['gate_ok'], vars['gate_say'], vars['gate_new'] = 'no_persuasion', 'no', '', 'no'\n"
            "        vars['gate_error'] = 'NO OFFER: ' + str(vars.get('gate_np')) + ' was raised, the brief allows no persuasion. Instead: ' + vars['_np_block']\n"
            "except Exception:\n"
            "    pass\n")
    return pre, post


def gate_tool(tool, rp, lines=None):
    from builder.engine.gates import gate_source
    pre, post = offer_guard(lines or {}) if tool == "next_offer" else ("", "")
    code = prefix(tool) + (HEARD if tool == "confirm" else "") + pre + gate_source(rp, GATE_NAME[tool]) + post + suffix()
    props = {"code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 15000}}
    props.update({k: PARAMS[k] for k in GATE_IN[tool]})
    return {"type": "function", "config": {"timeoutMs": 20000},
            "function": {"name": tool, "handler": "__function__:code_exec", "description": DESC[tool],
                         "parameters": {"type": "object", "properties": props, "required": REQUIRED[tool]}}}


def gate_create_promise(t):
    t = copy.deepcopy(t)
    body = t["function"]["parameters"]["properties"]["body"]["properties"]
    for f in ("amount", "date"):
        if f in body:
            body[f]["description"] = "taken from the confirmed read-back; any value"
    if "product_id" in body:
        body["product_id"]["description"] = "the product_id exactly as get_account returned it (for example p1)"
    t["function"]["description"] = ("Records the promise the customer confirmed. Call it right after the customer said yes to the "
                                    "read-back from confirm, once per product, one call at a time; amount and date are taken from "
                                    "the confirmed read-back. If the bank fails, call it once more with the same product.")
    t["pre_process_code"] = CP_PRE
    t["post_process_code"] = (t.get("post_process_code") or "") + CP_POST
    return t


import re as _re
RECORDED = _re.compile(r"\b(this|the) call is (being )?recorded", _re.I)
CHATTER = ("\n\nTALKATIVE CUSTOMERS: off-topic talk or a cut-off sentence is never a refusal, a no or an answer. Reply in a few "
           "words if needed, then ask your last question again. Only an explicit refusal counts as declining or refusing. "
           "Never repeat or rephrase an offer, a sympathy sentence or a support offer yourself.")
ONCE_PROMPT = """
- Lines the brief allows once (say_once): call say_once with the line BEFORE you say it. If the latest gate result says ALREADY SAID, do not say it again and do what it says instead (usually the close).
- Never repeat an offer in your own words. If the customer gives no clear answer to an offer, call next_offer with first: it repeats the offer once, and after that it moves on to the next attempt. NO OFFER means no persuasion at all: follow the instruction in the gate error."""


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
    lines = once_lines(rp)
    gates = [gate_tool(t, rp, lines) for t in GATE_IN] + ([once_tool(lines)] if lines else [])
    extra = [RB]
    np_quotes = [v["quote"] for v in lines.values() if v["np"] and v["quote"]]
    if np_quotes:      # sticky in code: the first gate run after a yes sets gate_np, which blocks every later offer
        extra.append({"name": "np_topic", "type": "string", "enum_values": ["yes", "no"], "min_confidence": 0.6,
                      "description": "yes if the customer has said at any point in this call something this rule covers: "
                                     + " / ".join(np_quotes) + " Otherwise no."})
    wf["test_variables"] = dict(wf.get("test_variables") or {}, gate_say="", gate_new="no", gate_status="none", gate_ok="no",
                                gate_out_date="", gate_out_amount="", gate_queue="", gate_error="")
    wf["system_prompt"] = (wf.get("system_prompt") or "") + CHATTER
    for k, n in nodes.items():         # the main path says "we keep a recording of this call": "recorded" is an honesty word
        oe = n.get("on_enter") or {}
        if isinstance(oe.get("text"), str):
            oe["text"] = RECORDED.sub("we keep a recording of this call", oe["text"])
    for h in hosts:
        n = nodes[h]
        n["tools"] = [gate_create_promise(t) if (t.get("function") or {}).get("name") == "create_promise" else t
                      for t in n["tools"]] + gates
        n["task_message"] = (n.get("task_message") or "") + PROMPT + (ONCE_PROMPT if lines else "")
        n["extraction_schema"] = (n.get("extraction_schema") or []) + extra
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
