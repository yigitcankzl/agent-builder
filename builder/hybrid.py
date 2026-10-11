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
- A missing confirmation is never a failure: if create_promise says the terms were not confirmed, or returns an error naming not-confirmed-read-back-and-ask-again, read the terms back with confirm (gate_action=readback) and ask again. An error naming wrong-product-use-... means call create_promise again with one of those product ids. Neither is a failure: do not close the call and do not say it could not be saved. service_error only when the bank itself answered ok false twice.
- An error naming already-recorded-... means that promise IS recorded: do not call create_promise for it again; continue as after a recorded promise. An error naming outcome-unknown-treat-as-recorded-... means the same: treat the promise as recorded, never say it failed. An error naming bank-failed-again-... means the bank refused it twice: say you could not record the promise; the outcome is no_promise / service_error.
- If the customer changes the terms and then goes back to the earlier ones, call confirm with gate_action=readback and those terms; the system reads them back and the customer confirms again.
Latest gate result: status {{gate_status}}, ok {{gate_ok}}, date {{gate_out_date}}, amount {{gate_out_amount}}, sentence: {{gate_say}}, error: {{gate_error}}

MODEL-OWNED RULES: everything else in this prompt (opening, identity, third parties, callbacks, hardship, disputes, transfers, the closing outcome and reason) is yours to follow exactly as written; the gates cover only dates, amounts, offers and the read-back."""

# min_confidence 0.35: a clear "Yes, I confirm." came back as yes at 0.593 once a second field shared the node's
# extraction (live v6 PUB-07 d8f32d92), and a discarded yes blocks the write.
RB = {"name": "rb_answer", "type": "string", "enum_values": ["yes", "no", "other"], "min_confidence": 0.35,
      "description": "The customer's answer to the agent's last read-back question (Do you confirm?). yes ONLY for an explicit "
                     "yes, I confirm, or correct to that read-back. no for a no. other for everything else, including OK, fine, "
                     "bye, a question, or an answer to anything that is not the read-back."}

# PAYLOAD BUDGET. Every code_exec and every api_call hook prints __CODE_EXEC_RESULT__ + the whole var table (+ the
# hook's config / result); the platform cuts that near 10,000 chars, the cut JSON is unparseable and from then on every
# hook of the call fails (live v6 PUB-06 8c4f0608: the table was 7.1k at the write; the bank recorded the promise, the
# hook failed, the model said it could not be saved). HYB_budget keeps the print <= 9,000 in reducer.enforce_budget's
# order: headers / old messages and errors / clock strings, then spent tool data and args, then the largest others.
# Never trimmed: gate_* (but gate_account), rb_answer, np_topic, *_count, *_status_code, the write-state auto vars of
# create_promise, the account data until gate_st holds the products, and every {{var}} the workflow reads (keep).
BUDGET = """
def HYB_budget(vars, keep, extra=0, limit=9000):
    import json as J
    def size():
        return 21 + len(J.dumps(dict(vars=vars), default=str)) + extra
    loaded = '"products":[{' in str(vars.get('gate_st') or '').replace(' ', '')
    def prot(k):
        return (k in keep or (k.startswith('gate_') and k != 'gate_account') or k in ('rb_answer', 'np_topic')
                or k.endswith('_count') or k.endswith('_status_code') or k.startswith('create_promise_args.')
                or k in ('create_promise_response.data.ok', 'create_promise_response.status', 'create_promise_response.error')
                or (not loaded and (k.startswith('get_account_response.data') or k.startswith('t_get_account_response.') or k == 'gate_account')))
    for k in list(vars):
        sk = str(k)
        if not prot(sk) and ('.header.' in sk or sk.endswith('_response.message') or sk.endswith('_response.error') or sk.startswith('system.')):
            vars.pop(k, None)
    if size() <= limit:
        return
    for k in list(vars):
        sk = str(k)
        if not prot(sk) and ('_response.' in sk or '_args.' in sk or sk.startswith('t_get_account_response.') or sk == 'gate_account'):
            vars.pop(k, None)
    for k in sorted([k for k in vars if not prot(str(k))], key=lambda k: -len(J.dumps(vars.get(k), default=str))):
        if size() <= limit:
            return
        vars.pop(k, None)
"""


def budget_call(keep, what=None):
    """The budget snippet + its call; what: 'config' (pre hook) or 'result' (post hook) is printed with the vars."""
    extra = f"len(__import__('json').dumps({what}, default=str)) + 20" if what else "0"
    return (BUDGET + "try:\n"
            f"    HYB_budget(vars, set({json.dumps(sorted(keep))}), {extra})\n"
            "except Exception:\n"
            "    pass\n")


# THE WRITE. Permission at the moment of the write: a standing (not voided) read-back from confirm and a yes the
# extraction heard after it (rb_answer, which every read-back resets; the last utterance as a fallback). The body takes
# the read-back's terms. Three outcomes of a write:
#   ok:true          -> the product is written: gate_written (post hook) and, independent of hook persistence, the
#                       platform's own auto vars (create_promise_args.product_id + create_promise_response.data.ok).
#                       A further create_promise for it is blocked: already-recorded (not a failure).
#   ok:false (bank)  -> a definite failure: retried with the same terms up to the brief's retries; then
#                       bank-failed-twice (service_error).
#   transport error  -> uncertain (no parseable answer): never retried blindly, never "could not be saved": blocked as
#                       outcome-unknown-treat-as-recorded. The tools have no ledger read.
# A blocked write is a transport error, so post_process never runs on it: the url host carries the instruction.
CP_PRE = """try:
    import json as _json
    import re as _re2
    st = vars.get('gate_st')
    st = _json.loads(st) if isinstance(st, str) and st else (st if isinstance(st, dict) else dict())
    rb = st.get('_rb') or dict()
    terms = rb.get('terms') or []
    b = config.get('body')
    pid = str(b.get('product_id') or '').strip()
    pick = [t for t in terms if str(t[0]) == pid] or (terms if len(terms) == 1 else [])
    target = str(pick[0][0]) if pick else pid
    written = [x for x in str(vars.get('gate_written') or '').split(',') if x]
    failed = dict(x.split(':', 1) for x in str(vars.get('gate_failed') or '').split(',') if x.count(':') == 1)
    last = str(vars.get('create_promise_args.product_id') or '')
    lok = str(vars.get('create_promise_response.data.ok')).lower()
    lerr = str(vars.get('create_promise_response.error') or '')
    if last and lok == 'true' and last not in written:
        written.append(last)
    # A non-2xx answer from the bank arrives as a transport error too ("API request failed: {'ok': False, 'error':
    # 'service unavailable, nothing was recorded'}", live v8 raw-4 PUB-10 12706780): the bank ANSWERED, so it is a
    # definite failure. Uncertain is only an error with no bank answer in it (timeout, connection, unparseable).
    answered = bool(_re2.search(r"api request failed|'ok': ?false|\\"ok\\": ?false|nothing was recorded|status code [45]\\d\\d", lerr.lower()))
    uncertain = bool(last) and lok not in ('true', 'false') and bool(lerr) and '.invalid' not in lerr and not answered
    if len(terms) == 1 and last == target and (lok == 'false' or answered):   # the platform's own counts (no hook needed)
        derived = int(vars.get('create_promise_success_count') or 0) - (1 if target in written else 0) if lok == 'false' else 0
        own = int(vars.get('gate_blocked') or 0)       # our own .invalid blocks are transport errors too: not the bank's
        derived = max(derived, int(vars.get('create_promise_failure_count') or 0) - own if answered else 0)
        failed[target] = str(max(1, derived, int(failed.get(target) or 0)))
    heard = vars.get('rb_answer') == 'yes'
    if not heard and vars.get('rb_answer') in (None, '', 'other'):
        sp = str(vars.get('extractor.speech') or '').lower()
        heard = bool(_re2.search(r"\\b(yes|yeah|yep|i confirm|confirmed|correct|that's right|that is right)\\b", sp)) and not _re2.search(r"\\b(no|not|change|wait)\\b", sp)
    if target and target in written:
        config['url'] = 'https://already-recorded-not-a-failure-do-not-call-again.invalid/'
    elif target and uncertain and target == last:
        written.append(target)
        config['url'] = 'https://outcome-unknown-treat-as-recorded-never-say-failed.invalid/'
    elif target and int(failed.get(target) or 0) > HYB_RETRIES:
        config['url'] = 'https://bank-failed-again-say-not-recorded-close-service-error.invalid/'
    elif not terms or rb.get('voided') or not heard:
        config['url'] = 'https://not-confirmed-read-back-and-ask-again.invalid/'
    elif not pick:
        config['url'] = 'https://wrong-product-use-' + '-or-'.join(_re2.sub('[^a-z0-9]', '', str(t[0]).lower()) for t in terms) + '.invalid/'
    else:
        b['product_id'], b['amount'], b['date'] = str(pick[0][0]), float(pick[0][1]), str(pick[0][2])
        vars['gate_writing'] = target
    vars['gate_written'] = ','.join(written)
    vars['gate_failed'] = ','.join(k + ':' + v for k, v in failed.items())
    if '.invalid' in str(config.get('url')):
        vars['gate_blocked'] = str(int(vars.get('gate_blocked') or 0) + 1)
except Exception:
    config['url'] = 'https://not-confirmed-read-back-and-ask-again.invalid/'
"""
CP_POST = """
try:
    d = result.get('data') if isinstance(result, dict) else None
    w = str(vars.get('gate_writing') or '')
    written = [x for x in str(vars.get('gate_written') or '').split(',') if x]
    failed = dict(x.split(':', 1) for x in str(vars.get('gate_failed') or '').split(',') if x.count(':') == 1)
    code = int((result or dict()).get('status_code') or 0) if isinstance(result, dict) else 0
    if isinstance(d, dict) and d.get('ok') is True:
        if w and w not in written:
            written.append(w)
    elif (isinstance(d, dict) and d.get('ok') is False) or code >= 500:
        n = int(failed.get(w) or 0) + 1
        failed[w] = str(n)
        result['what_to_do_next'] = ('NOT saved by the bank. Call create_promise once more for the same product.' if n <= HYB_RETRIES
                                     else 'The bank failed again: say you could not record the promise; the outcome is no_promise / service_error.')
    vars['gate_written'] = ','.join(written)
    vars['gate_failed'] = ','.join(k + ':' + v for k, v in failed.items())
    vars['gate_writing'] = ''
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


def once_tool(lines, keep=()):
    """say_once(line): the first call allows the line (the model says it); a repeat is refused, with what to do instead
    in gate_error (shown in the prompt). A no-persuasion line also sets gate_np, which blocks next_offer."""
    cat = {k: {"after": v["after"], "np": v["np"]} for k, v in lines.items()}
    code = ("import json as _json\n"
            f"_L = _json.loads({json.dumps(json.dumps(cat))})\n"
            "try:\n"
            "    _P = globals().get('params')\n"
            "    _line = str((_P if isinstance(_P, dict) else dict()).get('line') or '').strip()\n"
            "    _used = [x for x in str(vars.get('gate_once') or '').split(',') if x]\n"
            "    vars['gate_say'], vars['gate_new'], vars['gate_ok'] = '', 'no', 'no'\n"
            "    if _line not in _L:\n"
            "        vars['gate_status'], vars['gate_error'] = 'unknown_line', 'say_once line must be one of: ' + ', '.join(_L)\n"
            "    elif _line in _used:\n"
            "        vars['gate_status'] = 'already_said'\n"
            "        vars['gate_error'] = ('ALREADY SAID ONCE (' + _line + '): do not say or offer it again. Instead: ' + _L[_line]['after'])\n"
            "    else:\n"
            "        _used.append(_line)\n"
            "        vars['gate_once'] = ','.join(_used)\n"
            "        vars['gate_status'], vars['gate_ok'], vars['gate_error'] = 'once_ok', 'yes', ''\n"
            "    if _line in _L and _L[_line]['np']:\n"
            "        vars['gate_np'] = _line\n"
            "except Exception as _e:\n"
            "    vars['gate_status'], vars['gate_error'] = 'error', str(_e)[:150]\n") + budget_call(keep)
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
# Scratch values live in Python names (HYB_*), never in vars: after v6's next_offer wrote vars named _np_block and
# _st_backup, every later api_call hook in the call failed with "Sandbox did not return a parseable result" (live v6
# PUB-06 8c4f0608: the bank recorded the promise, the hook failed, the model said it could not be saved). The counter
# is a plain "p1:2,p2:1" string, not JSON.
def offer_guard(lines):
    np = {k: v["after"] for k, v in lines.items() if v["np"]}
    pre = ("HYB_NP_BLOCK, HYB_ST_BACKUP = '', vars.get('gate_st') or ''\n"
           "try:\n"
           f"    HYB_NP = _json.loads({json.dumps(json.dumps(np))})\n"
           "    if vars.get('np_topic') == 'yes' and HYB_NP and not vars.get('gate_np'):\n"
           "        vars['gate_np'] = list(HYB_NP)[0]\n"
           "    if vars.get('gate_np') in HYB_NP:\n"
           "        HYB_NP_BLOCK = HYB_NP[vars['gate_np']]\n"
           "    HYB_EV = str(vars.get('gate_event') or 'first')\n"
           "    HYB_FN = dict(x.split(':', 1) for x in str(vars.get('gate_first_n') or '').split(',') if x.count(':') == 1)\n"
           "    HYB_PK = str(vars.get('gate_product') or '').replace(':', '').replace(',', '')\n"
           "    HYB_N = int(HYB_FN.get(HYB_PK) or 0)\n"
           "    if HYB_EV == 'first':\n"
           "        HYB_N += 1\n"
           "        if HYB_N > 2:\n"
           "            vars['gate_event'], HYB_N = 'flat', 1\n"
           "    else:\n"
           "        HYB_N = 1\n"
           "    HYB_FN[HYB_PK] = str(HYB_N)\n"
           "    vars['gate_first_n'] = ','.join(k + ':' + v for k, v in HYB_FN.items())\n"
           "except Exception:\n"
           "    pass\n")
    post = ("try:\n"
            "    if HYB_NP_BLOCK:\n"
            "        vars['gate_st'] = HYB_ST_BACKUP or vars.get('gate_st')\n"
            "        vars['gate_status'], vars['gate_ok'], vars['gate_say'], vars['gate_new'] = 'no_persuasion', 'no', '', 'no'\n"
            "        vars['gate_error'] = 'NO OFFER: ' + str(vars.get('gate_np')) + ' was raised, the brief allows no persuasion. Instead: ' + HYB_NP_BLOCK\n"
            "except Exception:\n"
            "    pass\n")
    return pre, post


def gate_tool(tool, rp, lines=None, keep=()):
    from builder.engine.gates import gate_source
    pre, post = offer_guard(lines or {}) if tool == "next_offer" else ("", "")
    code = (budget_call(keep) + prefix(tool) + (HEARD if tool == "confirm" else "") + pre + gate_source(rp, GATE_NAME[tool])
            + post + suffix() + "try:\n    HYB_budget(vars, set(" + json.dumps(sorted(keep)) + "))\nexcept Exception:\n    pass\n")
    props = {"code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 15000}}
    props.update({k: PARAMS[k] for k in GATE_IN[tool]})
    return {"type": "function", "config": {"timeoutMs": 20000},
            "function": {"name": tool, "handler": "__function__:code_exec", "description": DESC[tool],
                         "parameters": {"type": "object", "properties": props, "required": REQUIRED[tool]}}}


def gate_create_promise(t, keep=(), retries=1):
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
    r = f"HYB_RETRIES = {int(retries)}\n"
    t["pre_process_code"] = r + CP_PRE + budget_call(keep, "config")
    t["post_process_code"] = r + (t.get("post_process_code") or "") + CP_POST + budget_call(keep, "result")
    return t


def budget_hooks(t, keep):
    """Every other api_call tool: the budget in its pre and post hooks (an L3 close_call / get_account hook prints the
    same var table and failed the same way in 8c4f0608)."""
    t = copy.deepcopy(t)
    t["pre_process_code"] = budget_call(keep, "config") + (t.get("pre_process_code") or "")
    t["post_process_code"] = (t.get("post_process_code") or "") + budget_call(keep, "result")
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
    # every {{var}} the workflow or the gate prompts read, and the call variables: never trimmed by the budget
    keep = set(_re.findall(r"\{\{\s*([\w.]+)\s*\}\}", json.dumps(wf) + PROMPT + ONCE_PROMPT))
    keep |= set(((rp.get("meta") or {}).get("call_vars") or {}).values()) | {"customer_id", "now"}
    retries = int(((rp.get("writes") or {}).get("promise") or {}).get("retries", 1) or 0)
    gates = [gate_tool(t, rp, lines, keep) for t in GATE_IN] + ([once_tool(lines, keep)] if lines else [])
    for n in nodes.values():
        n["tools"] = [budget_hooks(t, keep) if (t.get("function") or {}).get("handler") == "__function__:api_call"
                      and (t.get("function") or {}).get("name") != "create_promise" else t for t in n.get("tools") or []]
    wf["tools"] = [budget_hooks(t, keep) if (t.get("function") or {}).get("handler") == "__function__:api_call" else t
                   for t in wf.get("tools") or []]
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
        n["tools"] = [gate_create_promise(t, keep, retries) if (t.get("function") or {}).get("name") == "create_promise" else t
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
                    "type": "object", "properties": {"code": {"type": "string", "default": "vars['gate_new'] = 'no'\n" + budget_call(keep)},
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
