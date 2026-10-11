"""Code-node gates for an LLM-written workflow (hybrid L3): the parts LLMs get wrong (dates, counting, confirmation)
decided by the reducer's own functions. Each gate is a code node: gate_source(policy, name) -> the node's code string
(stdlib only, no double braces, never raises: an error sets gate_status=error).

Shared state: the var gate_st (JSON, written back by every gate; the LLM never edits it). It holds the reducer state
with the products loaded from get_account on the first gate run.

INPUTS read by every gate
  <policy.now.var> (default now)   the call's now, ISO date or datetime
  gate_account     the get_account response data (JSON or dict); else get_account_data, else the flattened
                   t_get_account_response.data.* vars. Read once, on the first gate run.
  gate_product     the product: its product_id, or its 1-based position in get_account order

date_amount_gate(vars, policy)   is this date / amount recordable for gate_product?
  in:  gate_date (YYYY-MM-DD) or gate_spec (rel=;d=;m=;wd=;wk=, labels only) or neither; gate_amount (number or empty)
  out: gate_status  ok | non_business | after_deadline | past | below_floor | not_allowed_amount | unclear_date | route
       gate_ok      yes only for ok
       gate_out_date    the recordable date (the shifted day, the deadline) or empty when none can be recorded
       gate_out_amount  the recordable amount (the stated one, the floor, the full amount)
       gate_say     the exact sentence (the brief's lines, naming the customer's day), empty for ok
       gate_deadline, gate_floor, gate_full, gate_queue (route only)
  A different date / amount for a product that is in the standing read-back voids that read-back.

attempt_gate(vars, policy)   the next persuasion offer for gate_product (attempts.plan, floor rules)
  in:  gate_event  first (the first offer) | flat (a flat no to the open offer) | too_much (the amount is the problem)
  out: gate_status  offer | exhausted | route
       gate_out_amount, gate_out_date, gate_say (the offer sentence)        for offer
       gate_note_reason (notes enabled, else empty), gate_close_outcome, gate_close_reason   for exhausted
       gate_attempts (used), gate_attempts_max
  The too-much floor offer does not use an attempt; an offer refused once is never proposed again.

confirm_gate(vars, policy)   the read-back and the permission to write
  in:  gate_action  readback | yes | change | next
       gate_terms   for readback: <product>:<amount>:<YYYY-MM-DD>|... (product id or position)
  readback -> each term is checked as date_amount_gate does (invalid: gate_status=invalid, gate_say why);
              valid: gate_status=readback, gate_say = the read-back sentence ending with the confirm question,
              gate_rb_id (a new id). The same terms again: gate_status=repeat (the same sentence).
  yes      -> gate_ok=yes and gate_status=granted only when a read-back stands, was not voided, and was not already
              granted; gate_promises = JSON list of product_id, amount, date. Else gate_ok=no, gate_status=stale.
  change   -> voids the standing read-back (gate_status=voided).
  next     -> the next granted promise to write: gate_write_product_id, gate_write_amount, gate_write_date,
              gate_ok=yes; none left: gate_ok=no, gate_status=done.
"""
import datetime, json, re

try:  # local runs; in the code node the date core and the reducer are concatenated above this file
    from builder.engine.dates import date_from_spec, parse_spec
    from builder.engine.reducer import init_state, load_products, _account_rows, _flat_data, _jsonish, _d, iso, _num, \
        _p, date_verdict, fill_date, accept_rule, amount_fits, offer_line, money, say_date, start_attempt, reject_event, \
        sentence, V, _dump
except Exception:
    pass

GATE_OUT = ('gate_status', 'gate_ok', 'gate_say', 'gate_out_date', 'gate_out_amount', 'gate_deadline', 'gate_floor', 'gate_full',
            'gate_queue', 'gate_note_reason', 'gate_close_outcome', 'gate_close_reason', 'gate_attempts',
            'gate_attempts_max', 'gate_rb_id', 'gate_promises', 'gate_write_product_id', 'gate_write_amount',
            'gate_write_date', 'gate_error')
D_CLARIFY_DATE = 'Sorry, which exact date do you mean?'


def _gate_today(vars, policy):
    return _d(str(vars.get((policy.get('now') or dict()).get('var', 'now')) or vars.get('now') or '')[:10] or
              datetime.date.today().isoformat())


def _gate_st(vars, policy, today):
    st = _jsonish(vars.get('gate_st'))
    if isinstance(st, dict) and st.get('products'):
        return st
    st = init_state(policy, dict())
    data = _jsonish(vars.get('gate_account') or vars.get('get_account_data'))
    if not isinstance(data, (dict, list)):
        data = _flat_data(vars, 't_get_account_response.data.')
    load_products(policy, st, _account_rows(dict(data=data), policy), today)
    st['_rb'], st['_rb_n'], st['_granted'] = None, 0, []
    return st


def _gate_prod(st, ref):
    ref = str(ref or '').strip()
    for i, p in enumerate(st['products']):
        if p['id'] == ref:
            return i
    return int(ref) - 1 if ref.isdigit() and 0 < int(ref) <= len(st['products']) else (0 if len(st['products']) == 1 else None)


def _gate_run(vars, policy, body):
    """Clear the outputs, run the gate, write gate_st back; an exception becomes gate_status=error (never raises)."""
    for k in GATE_OUT:
        vars[k] = ''
    vars['gate_ok'] = 'no'
    try:
        today = _gate_today(vars, policy)
        st = _gate_st(vars, policy, today)
        if not st['products']:
            vars['gate_status'], vars['gate_error'] = 'error', 'no products from get_account'
            return
        body(vars, policy, st, today)
        vars['gate_st'] = _dump(st, (',', ':'))
    except Exception as e:
        vars['gate_status'], vars['gate_error'] = 'error', (type(e).__name__ + ': ' + str(e))[:150]


def _check(policy, st, i, today, date_raw, spec, amt):
    """The date and amount for product i -> dict(status, date, amount, say) (the reducer's date_verdict, amount rule)."""
    p, pd = _p(st, i)
    out = dict(status='ok', date='', amount=pd['floor'] if pd['too_much'] else pd['past_due'], say='')
    if pd.get('route'):
        return dict(out, status='route', amount='')
    says = []
    if date_raw or spec:
        named, kind = None, None
        if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', str(date_raw or '')):
            try:
                named, kind = _d(date_raw), 'exact'
            except Exception:
                named = None
        if named is None and spec:
            named, kind = date_from_spec(today, parse_spec(spec), policy)
        if named is None or kind != 'exact':
            return dict(out, status='unclear_date', say=D_CLARIFY_DATE)
        r = date_verdict(policy, today, pd, named)
        out['date'] = iso(r['accepted']) if r['accepted'] else ''
        if r['reason'] != 'ok':
            out['status'] = dict(non_business_day='non_business', after_deadline='after_deadline').get(r['reason']) or \
                ('non_business' if r['sit'] in ('weekend', 'holiday') else 'after_deadline' if r['sit'] == 'after_deadline' else 'past')
            says.append(fill_date(r['say'], r))
    a = _num(amt) if str(amt or '').strip() else None
    if a is not None:
        kind, x = accept_rule(policy)
        full = pd['past_due']
        low = x if kind == 'min_x' and x is not None else pd['floor']
        when = out['date'] or pd['deadline']
        if amount_fits(policy, pd, a):
            out['amount'] = a
        elif a > full + 0.005:
            out['amount'] = full
            says.append('The amount due is ' + money(full) + '.')
        else:
            ofr = min(max(low, pd['floor']) if kind == 'min_x' else pd['floor'], full)
            out['amount'] = ofr
            says.append('I cannot record ' + money(a) + '.')
            if out['status'] == 'ok':
                out['status'] = 'below_floor' if a < min(low, full) - 0.005 else 'not_allowed_amount'
            if out['status'] in ('below_floor', 'not_allowed_amount'):
                says.append(offer_line(pd, ofr, when, ofr < full - 0.005))
        if out['status'] == 'ok' and a > full + 0.005:
            out['status'] = 'not_allowed_amount'
            says.append(offer_line(pd, full, when))
    out['say'] = ' '.join(x for x in says if x).strip()
    return out


def _void_if_changed(st, pid, amount, date):
    rb = st.get('_rb')
    if rb and not rb.get('voided'):
        for t in rb['terms']:
            if t[0] == pid and (abs(float(t[1]) - float(amount or 0)) > 0.005 or (date and t[2] != date)):
                rb['voided'] = True


def date_amount_gate(vars, policy):
    def body(vars, policy, st, today):
        i = _gate_prod(st, vars.get('gate_product'))
        if i is None:
            vars['gate_status'], vars['gate_error'] = 'error', 'unknown gate_product'
            return
        p, pd = _p(st, i)
        r = _check(policy, st, i, today, vars.get('gate_date'), vars.get('gate_spec'), vars.get('gate_amount'))
        vars['gate_status'], vars['gate_say'], vars['gate_out_date'] = r['status'], r['say'], r['date']
        vars['gate_out_amount'] = '' if r['amount'] == '' else '%.2f' % float(r['amount'])
        vars['gate_ok'] = 'yes' if r['status'] == 'ok' else 'no'
        vars['gate_deadline'], vars['gate_floor'], vars['gate_full'] = pd['deadline'], '%.2f' % pd['floor'], '%.2f' % pd['past_due']
        if pd.get('route'):
            vars['gate_queue'] = str(pd['route'].get('queue') or '')
        if r['status'] != 'route' and (str(vars.get('gate_amount') or '').strip() or r['date']):
            _void_if_changed(st, p['id'], r['amount'], r['date'])
    _gate_run(vars, policy, body)


def attempt_gate(vars, policy):
    def body(vars, policy, st, today):
        i = _gate_prod(st, vars.get('gate_product'))
        if i is None:
            vars['gate_status'], vars['gate_error'] = 'error', 'unknown gate_product'
            return
        p, pd = _p(st, i)
        vars['gate_attempts_max'] = str(len(pd['plan']))
        if pd.get('route'):
            vars['gate_status'], vars['gate_queue'] = 'route', str(pd['route'].get('queue') or '')
            return
        ev = str(vars.get('gate_event') or 'first')
        o = p.get('offer') if p['status'] == 'proposed' else None
        # one product seen alone: the reducer's attempt rules never move on to another product here
        sub = dict(st, products=[p], _pd=[pd], cur=0, q='offer', readback=None, pending=None, _queue=[], notes=[],
                   transfers=[], counters=dict(st['counters']),
                   offer=dict(product_ids=[p['id']], amount=o['amount'], date=o['date'], kind='attempt_n') if o else None)
        if p['status'] in ('open', 'proposed'):
            if ev == 'first' and o:
                a = dict(type='say_exact', text=offer_line(pd, o['amount'], o['date']))
            elif ev == 'first':
                a = start_attempt(policy, sub, 0, today)
            else:
                a = reject_event(policy, sub, dict(why='too_much' if ev == 'too_much' else 'flat'), today, dict(customer_id=st.get('_cid')))
        vars['gate_attempts'] = str(p['attempts'])
        if p['status'] == 'proposed' and p.get('offer'):
            vars['gate_status'], vars['gate_ok'] = 'offer', 'yes'
            vars['gate_out_amount'], vars['gate_out_date'] = '%.2f' % float(p['offer']['amount']), p['offer']['date']
            vars['gate_say'] = a.get('text') if a.get('type') == 'say_exact' else offer_line(pd, p['offer']['amount'], p['offer']['date'])
            _void_if_changed(st, p['id'], p['offer']['amount'], p['offer']['date'])
            return
        if p['status'] in ('open', 'proposed', 'refused'):
            p['status'], p['offer'] = 'refused', None
            pd['note_reason'] = pd.get('note_reason') or V(policy)['note']['refused']
        notes_on = bool(((policy.get('writes') or dict()).get('notes') or dict()).get('enabled'))
        o_, r_ = V(policy)['refused']
        vars['gate_status'] = 'exhausted'
        vars['gate_note_reason'] = str(pd['note_reason'] or '') if notes_on else ''
        vars['gate_close_outcome'], vars['gate_close_reason'] = o_ or '', r_ or ''
    _gate_run(vars, policy, body)


def _terms(st, raw):
    out = []
    for part in str(raw or '').split('|'):
        m = re.fullmatch(r'\s*([A-Za-z0-9_.-]+)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*', part)
        i = _gate_prod(st, m.group(1)) if m else None
        if i is None:
            return None
        out.append([i, float(m.group(2)), m.group(3)])
    return sorted(out) or None


def confirm_gate(vars, policy):
    def body(vars, policy, st, today):
        act = str(vars.get('gate_action') or '').strip().lower()
        rb = st.get('_rb')
        if act == 'readback':
            terms = _terms(st, vars.get('gate_terms'))
            if not terms:
                vars['gate_status'], vars['gate_error'] = 'invalid', 'gate_terms: <product>:<amount>:<YYYY-MM-DD>|...'
                return
            parts = []
            for i, a, d in terms:
                r = _check(policy, st, i, today, d, '', a)
                if r['status'] != 'ok' or abs(float(r['amount']) - a) > 0.005 or r['date'] != d:
                    vars['gate_status'], vars['gate_say'], vars['gate_product'] = 'invalid', r['say'], st['products'][i]['id']
                    return
                parts.append(st['_pd'][i]['name'] + ': ' + money(a) + ' on ' + say_date(_d(d)))
            conf = sentence(policy, 'confirm') or sentence(policy, 'readback_confirm') or sentence(policy, 'confirm_readback') or \
                sentence(policy, 'confirm_arrangement') or 'Do you confirm?'
            text = 'To confirm, ' + '; '.join(parts) + '. ' + conf
            key = [[st['products'][i]['id'], a, d] for i, a, d in terms]
            if rb and not rb.get('voided') and not rb.get('granted') and rb['terms'] == key:
                vars['gate_status'] = 'repeat'
            else:
                st['_rb_n'] = st.get('_rb_n', 0) + 1
                st['_rb'] = rb = dict(id=st['_rb_n'], terms=key, voided=False, granted=False)
                vars['gate_status'] = 'readback'
            vars['gate_say'], vars['gate_rb_id'] = text, str(rb['id'])
            return
        if act == 'yes':
            if not rb or rb.get('voided') or rb.get('granted'):
                vars['gate_status'] = 'stale'
                return
            rb['granted'] = True
            st['_granted'] = [list(t) for t in rb['terms']]
            vars['gate_status'], vars['gate_ok'], vars['gate_rb_id'] = 'granted', 'yes', str(rb['id'])
            vars['gate_promises'] = json.dumps([dict(product_id=t[0], amount=t[1], date=t[2]) for t in rb['terms']])
            return
        if act in ('change', 'no'):
            if rb:
                rb['voided'] = True
            vars['gate_status'] = 'voided'
            return
        if act == 'next':
            if not st.get('_granted'):
                vars['gate_status'] = 'done'
                return
            t = st['_granted'].pop(0)
            vars['gate_status'], vars['gate_ok'] = 'write', 'yes'
            vars['gate_write_product_id'], vars['gate_write_amount'], vars['gate_write_date'] = t[0], '%.2f' % t[1], t[2]
            return
        vars['gate_status'], vars['gate_error'] = 'error', 'gate_action: readback | yes | change | next'
    _gate_run(vars, policy, body)


GATES = ('date_amount_gate', 'attempt_gate', 'confirm_gate')


def gate_source(policy, name, pack=True):
    """The code-node string for one gate: date core + the reducer functions it reaches + this file, the policy
    literal, the call. pack: zlib + base64 loader (generator.pack_hub; PACK_HUB=0 keeps it plain)."""
    import os
    from builder.engine import reducer as R
    if name not in GATES:
        raise ValueError('unknown gate ' + str(name))
    here = os.path.dirname(os.path.abspath(__file__))
    src = ''
    for f in ('dates.py', 'reducer.py', 'gates.py'):
        with open(os.path.join(here, f)) as fh:
            src += fh.read() + '\n\n'
    pol = json.loads(json.dumps(policy))

    def strip(x):
        if isinstance(x, dict):
            return dict((k, strip(v)) for k, v in x.items() if k not in ('source', 'superseded'))
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    code = R.minify(src, roots=(name,)) + '\nPOLICY = json.loads(' + repr(R._dump(strip(pol), (',', ':'))) + ')\n' + name + '(vars, POLICY)\n'
    if '{' * 2 in code or '}' * 2 in code:
        raise ValueError('gate source contains double braces')
    compile(code, name, 'exec')
    if pack:
        from builder.generator import pack_hub
        code = pack_hub(code)
    return code
