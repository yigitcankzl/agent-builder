"""Reducer, contract v3.2 (design/REDUCER-CONTRACT.md). step(policy, st, event, tool_event, now) -> (st2, action).

Pure, stdlib only (json, re, datetime), 3.8-safe, never two actions, no double braces anywhere in this source (it is
concatenated into a Freya code node by hub_source). The policy is the bridge's to_reducer() output (policy-extract).
Every brief-specific value comes from the policy; the only literals are contract defaults (marked DEFAULT).

Action shapes:
  dict(type='say_exact', text=...)                     exact tts, never empty
  dict(type='speak_free', node='talk_pre'|'talk_post', hint=...)
  dict(type='call_tool', tool=..., args=dict(...))     canonical arg names; the generator maps them to the OAS body
  dict(type='close', outcome=..., reason=..., farewell=...)
"""
import copy
import datetime
import json
import re

try:  # local runs; in the code node the date core is concatenated above this file
    from builder.engine.dates import date_from_spec, parse_spec, decide, deadline_for, add_business_days, \
        is_business_day, say_date
except Exception:
    pass

# ---------------------------------------------------------------- contract defaults (DEFAULT, not brief values)
D_FAREWELL = 'Thank you, goodbye.'
D_RECORDED = 'Your promise is recorded.'
D_SAFE = 'Sorry, could you say that again?'
D_CONTINUE = 'Go on, please.'
D_NO_TERMS = 'I am sorry, there are no other terms.'
D_CHANGE = 'You can change it in the mobile app.'
D_WHAT_CHANGE = 'What would you like to change?'
D_CLARIFY = 'Sorry, which exact date do you mean?'
D_HINT_MONTH = 'Could you say the month as a word, please?'
D_HELP_FIRST = 'Can I help you with this first?'
D_ASK_TIME = 'At what time could I reach them?'
D_ALL_TODAY = 'Can you pay all of them today?'
D_OVERDUE = 'The rest stays overdue.'
COUNTERS = ['confirm_name', 'clarify', 'vague', 'stop_talking', 'human_asks', 'decline_explain', 'support_offered']
TOOL_NODE = dict(verify_identity='t_verify_identity', get_account='t_get_account', create_promise='t_create_promise',
                 add_note='t_add_note', schedule_callback='t_schedule_callback',
                 transfer_to_agent='t_transfer_to_agent', close_call='t_close_call')
OP_TOOL = dict(verify='verify_identity', account='get_account', promise='create_promise', note='add_note',
               callback='schedule_callback', transfer='transfer_to_agent')
WD_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
MISDIAL = 'wrong_number'    # contract event vocabulary (ev payload who.party), not a brief outcome or reason


# ---------------------------------------------------------------- small helpers
def _none(x):
    return None if x in (None, '', 'none', 'null', 'None') else x


def money(x):
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return str(int(round(x)))
    s = ('%.2f' % x).rstrip('0').rstrip('.')
    return s


def iso(d):
    return d.isoformat() if d else None


def _d(s):
    return datetime.date.fromisoformat(str(s)[:10])


def sentence(policy, key, default=''):
    s = (policy.get('sentences') or dict()).get(key)
    if isinstance(s, dict):
        return s.get('text') or default
    return s or default


def fill_names(text, vars_):
    out = str(text or '')
    for k, v in (vars_ or dict()).items():
        out = out.replace('{' + k + '}', str(v))
    return out


def name_question(policy, cv):
    """The name question: sentences.confirm_who (contract key), its run-to-run variant ask_identity, or the who rule
    for an unclear speaker."""
    q = sentence(policy, 'confirm_who') or sentence(policy, 'ask_identity')
    if not q:
        q = next((w.get('say') for w in policy.get('who_rules') or [] if w.get('who') == 'unclear' and w.get('say')), '')
    return fill_names(q, cv)


def pay_today_question(policy):
    return sentence(policy, 'pay_today') or sentence(policy, 'ask_today') or 'Can you make this payment today?'


def unmapped_say(policy, pattern, transform):
    """A 'say' rule the bridge left unmapped, turned into a sentence (e.g. 'Tell the customer to X.' -> 'Please X.')."""
    for u in policy.get('unmapped_rules') or []:
        q = str(u.get('quote') or '')
        if re.search(pattern, q, re.I):
            return transform(q)
    return ''


def debt_intro(policy):
    s = sentence(policy, 'debt_intro')
    if s:
        return s
    return unmapped_say(policy, r'^Say that you are calling from', lambda q: re.sub(r'^Say that you are', 'I am', q))


def id_fail_line(policy):
    s = sentence(policy, 'id_fail') or (policy.get('identity') or dict()).get('fail_say') or ''
    if s:
        return s
    return unmapped_say(policy, r'^Tell the customer to use', lambda q: re.sub(r'^Tell the customer to', 'Please', q))


def event_row(policy, topic, outcome=None):
    """events[] row for a contract topic; when a topic has several rows, pick by outcome."""
    rows = [e for e in policy.get('events') or [] if e.get('topic') == topic]
    if outcome is not None:
        exact = [e for e in rows if _none(e.get('outcome')) == outcome]
        if exact:
            return exact[0]
    return rows[0] if rows else None


def who_row(policy, who, reason=None):
    rows = [w for w in policy.get('who_rules') or [] if w.get('who') == who]
    if reason is not None:
        exact = [w for w in rows if _none(w.get('reason')) == reason]
        if exact:
            return exact[0]
    return rows[0] if rows else None


def slot(policy, name):
    s = ((policy.get('closing') or dict()).get('slots') or dict()).get(name)
    if isinstance(s, dict):
        return _none(s.get('outcome')), _none(s.get('reason'))
    return None, None


def vocab(policy):
    """Every outcome / reason / note reason the reducer can send, derived from the policy (closing.slots, events[],
    who_rules, closing.table). No brief literal: a missing value falls back to another policy value and is logged."""
    log = []
    ev = policy.get('events') or []
    rows = lambda t: [e for e in ev if e.get('topic') == t]
    pair = lambda r: (_none(r.get('outcome')), _none(r.get('reason'))) if r else (None, None)
    unclear = slot(policy, 'unclear')
    if not unclear[0]:
        hb = (policy.get('hangup_default') or dict()).get('before_who') or dict()
        unclear = (_none(hb.get('outcome')), _none(hb.get('reason')))
        log.append('slot unclear missing: hangup_default.before_who')
    declined = slot(policy, 'declined')

    def pick(label, value):
        if value and value[0]:
            return value
        log.append(label + ' missing: unclear slot used')
        return unclear
    hard = rows('hardship')
    hard_accept = next((r for r in hard if not _none(r.get('note_reason'))), hard[0] if hard else None)
    hard_decline = next((r for r in hard if _none(r.get('note_reason'))), hard[-1] if hard else None)
    stops = rows('stop')
    stop_after = next((r for r in stops if pair(r) != declined), stops[0] if stops else None)
    paid_row = (rows('paid') or [None])[0]
    dispute_row = (rows('dispute') or [None])[0]
    out = dict(log=log, unclear=unclear, declined=pick('slot declined', declined),
               id_failed=pick('slot id_failed', slot(policy, 'id_failed')),
               callback_failed=pick('slot callback_failed', slot(policy, 'callback_failed')),
               write_failed=pick('slot write_failed', slot(policy, 'write_failed')),
               refused=pick('events stop (after verification)', pair(stop_after)),
               hardship=pick('events hardship (declined)', pair(hard_decline)),
               dispute=pick('events dispute', pair(dispute_row)),
               paid=pick('events paid', (pair(paid_row)[0], None)))
    out['xfer'] = dict(restructuring=pick('events restructure', pair((rows('restructure') or [None])[0])),
                       human=pick('events human', pair((rows('human') or [None])[0])),
                       hardship=pick('events hardship (accepted)', pair(hard_accept)))
    out['note'] = dict(refused=_none((stop_after or dict()).get('note_reason')) or out['refused'][1],
                       hardship=_none((hard_decline or dict()).get('note_reason')) or out['hardship'][1],
                       dispute=_none((dispute_row or dict()).get('note_reason')) or out['dispute'][1],
                       paid=_none((paid_row or dict()).get('note_reason')),
                       write_error=out['write_failed'][1])
    # the promise outcome: the closing-table row that no event, who rule or slot uses and whose "when" names a promise
    used = set(x[0] for x in (out['refused'], out['hardship'], out['dispute'], out['paid'], unclear, out['declined'],
                              out['id_failed']) if x[0]) | set(v[0] for v in out['xfer'].values() if v[0])
    prom = None
    for r in (policy.get('closing') or dict()).get('table') or []:
        if _none(r.get('outcome')) not in used and re.search(r'promise', str(r.get('when') or ''), re.I):
            prom = _none(r.get('outcome'))
            break
    if not prom:
        log.append('promise outcome missing: unclear slot used')
        prom = unclear[0]
    out['promise'] = (prom, None)
    others = [w for w in policy.get('who_rules') or [] if w.get('who') == 'other']
    cb_ok = next((w for w in others if pair(w) != out['callback_failed']), others[0] if others else None)
    out['callback'] = pick('who_rules other (callback)', pair(cb_ok))
    out['callback_say'] = (cb_ok or dict()).get('say') or ''
    cb_no = next((w for w in policy.get('who_rules') or [] if pair(w) == out['callback_failed']), None)
    out['callback_retry_say'] = (cb_no or dict()).get('say') or ''
    return out


_VC = dict()


def V(policy):
    k = id(policy)
    if k not in _VC:
        _VC[k] = vocab(policy)
    return _VC[k]


def close_action(outcome, reason, farewell):
    return dict(type='close', outcome=outcome, reason=_none(reason), farewell=(farewell or D_FAREWELL).strip())


# ---------------------------------------------------------------- state
def init_state(policy, call_vars=None):
    order = [q.get('field') for q in (policy.get('identity') or dict()).get('questions') or []]
    hb = (policy.get('hangup_default') or dict()).get('before_who') or dict()
    st = dict(phase='opening', verified='no', who='unknown', q='confirm_name',
              identity=dict(order=order, idx=0, wrong=0, refusals=0),
              products=[], cur=None, all_today_asked=False, offer=None, readback=None, pending=None,
              counters=dict((c, 0) for c in COUNTERS), notes=[], callbacks=[], transfers=[],
              outcome=None, reason=None,
              hangup=dict(slot='unclear', outcome=_none(hb.get('outcome')), reason=_none(hb.get('reason'))),
              tok='kstart', last_tok='kstart', runs=0,
              _pd=[], _tc=dict(), _last_ask='', _queue=[], _cb_out=0, _ask_time=0, _xfer_pre='no',
              _wrapup_said=False, _what_change=0, _id_hint=0, _id_retry=0)
    st['counters']['confirm_name'] = 1          # the greet speaks the name question (§12 choice 2)
    st['_last_ask'] = name_question(policy, call_vars or dict())
    return st


# ---------------------------------------------------------------- products
def _floor(policy, row):
    fb = ((policy.get('products') or dict()).get('floor_by_type') or dict()).get(str(row.get('type')))
    if isinstance(fb, dict) and fb.get('field') and row.get(fb['field']) is not None:
        return float(row.get(fb['field']))
    return float(row.get('past_due') or 0)      # no floor rule for this type in the policy: the full amount


def _name(policy, row):
    tpl = ((policy.get('products') or dict()).get('naming_by_type') or dict()).get(str(row.get('type')))
    if not tpl:
        tpl = str(row.get('type') or 'account').replace('_', ' ')
    out = str(tpl)
    for k, v in row.items():
        out = out.replace('{' + str(k) + '}', str(v))
    return out


def _band(policy, days_late):
    bands = (policy.get('deadline') or dict()).get('bands') or []
    for b in bands:
        lo = b.get('min_days_late', 0) or 0
        if lo <= days_late <= b.get('max_days_late', 9999):
            return b
    return bands[-1] if bands else dict(name='default', days=7)


def _plan(policy, band):
    plan = ((policy.get('attempts') or dict()).get('plan') or dict()).get(band.get('name'))
    if plan is None:
        n = band.get('attempts')
        return [dict(date_rule='last_business_day_this_week', amount_rule='floor_if_too_much_else_full')] * int(n or 0)
    return plan


def _account_rows(tool_event):
    data = (tool_event or dict()).get('data')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None
    if isinstance(data, dict):
        data = data.get('products', data.get('data'))
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None
    if isinstance(data, dict):
        data = data.get('products')
    return [r for r in (data or []) if isinstance(r, dict)]


def load_products(policy, st, rows, today):
    st['products'], st['_pd'] = [], []
    for r in rows:
        dl = int(float(r.get('days_late') or 0))
        band = _band(policy, dl)
        dline = deadline_for(today, dl, policy)
        st['products'].append(dict(id=str(r.get('product_id')), status='open', attempts=0, floor_offered=False,
                                   write_failures=0, offer=None, note=None))
        st['_pd'].append(dict(id=str(r.get('product_id')), name=_name(policy, r), past_due=float(r.get('past_due') or 0),
                              days_late=dl, floor=_floor(policy, r), band=band.get('name'), deadline=iso(dline),
                              plan=_plan(policy, band), too_much=False, note_reason=None, refused_offers=[]))


def _p(st, i):
    return st['products'][i], st['_pd'][i]


def _index(st, pid):
    for i, p in enumerate(st['products']):
        if p['id'] == pid:
            return i
    return None


def _valid_prod(st, ev, default):
    """prod=<1-based position>; an out-of-range or non-numeric ref falls back to the current product."""
    try:
        i = int(ev.get('prod')) - 1
    except Exception:
        return default
    return i if 0 <= i < len(st['products']) else default


def _open_products(st):
    return [i for i, p in enumerate(st['products']) if p['status'] in ('open', 'proposed')]


# ---------------------------------------------------------------- sentences built from facts
def product_line(pd):
    return 'Your ' + pd['name'] + ' has ' + money(pd['past_due']) + ' past due and is ' + str(pd['days_late']) + ' days late.'


def offer_line(pd, amount, date, floor_clause=False):
    s = 'Could you pay ' + money(amount) + ' for your ' + pd['name'] + ' on ' + say_date(_d(date)) + '?'
    if floor_clause:
        s += ' ' + D_OVERDUE
    return s


def readback_line(policy, st, items, clamped):
    parts = []
    for it in items:
        i = _index(st, it['product_id'])
        pd = st['_pd'][i]
        s = pd['name'] + ': ' + money(it['amount']) + ' on ' + say_date(_d(it['date']))
        if it['product_id'] in clamped:
            s += ', the latest date I can record for it'
        parts.append(s)
    return 'To confirm, ' + '; '.join(parts) + '. ' + sentence(policy, 'confirm', 'Do you confirm?')


def ask(st, text, q):
    st['q'] = q
    st['_last_ask'] = text
    return dict(type='say_exact', text=text)


def resay(st, prefix=''):
    text = ((prefix + ' ') if prefix else '') + (st.get('_last_ask') or D_SAFE)
    return dict(type='say_exact', text=text.strip())


# ---------------------------------------------------------------- closing
def precedence(policy, st):
    v = V(policy)
    if st['transfers']:
        return tuple(st.get('_xfer_close') or v['xfer']['human'])
    if any(p['status'] == 'persisted' for p in st['products']):
        return v['promise']
    paid_note = v['note']['paid']
    if st['products'] and all(p['status'] == 'paid' or (paid_note and p['note'] == paid_note) for p in st['products']):
        return v['paid']
    for p, pd in zip(st['products'], st['_pd']):
        r = p['note'] or pd.get('note_reason') or (v['note']['refused'] if p['status'] == 'refused' else None)
        if r and r != paid_note:
            return v['refused'][0], r
    return None, None


def update_hangup(policy, st):
    if st['phase'] == 'closed':
        st['hangup'] = dict(slot='closed', outcome=st['outcome'], reason=st['reason'])
        return
    hd = policy.get('hangup_default') or dict()
    if st['verified'] != 'yes':
        if st['who'] == 'self':
            r = hd.get('before_verified') or dict()
            st['hangup'] = dict(slot='declined', outcome=_none(r.get('outcome')), reason=_none(r.get('reason')))
        else:
            r = hd.get('before_who') or dict()
            st['hangup'] = dict(slot='unclear', outcome=_none(r.get('outcome')), reason=_none(r.get('reason')))
        return
    o, r = precedence(policy, st)
    v = V(policy)
    final = set([v['promise'][0], v['paid'][0]] + [x[0] for x in v['xfer'].values()])
    if o not in final:
        o, r = None, None
    st['hangup'] = dict(slot='products', outcome=o, reason=r)


def fallback_outcome(policy):
    """Last resort when precedence finds nothing: the table's refused row, else the unclear slot."""
    v = V(policy)
    return v['refused'] if v['refused'][0] else v['unclear']


def do_close(policy, st, outcome, reason, farewell):
    if not outcome:
        outcome, reason = fallback_outcome(policy)
    st['phase'], st['q'], st['outcome'], st['reason'] = 'closed', 'none', outcome, _none(reason)
    st['offer'] = None
    return close_action(outcome, reason, farewell)


# ---------------------------------------------------------------- tools
def call(st, op, tool, args, product_id=None, attempt=1):
    node = TOOL_NODE[tool]
    s, f = st['_tc'].get(node, [0, 0])
    st['pending'] = dict(op=op, node=node, product_id=product_id, snap_success=s, snap_failure=f, attempt=attempt)
    st['q'] = 'none'
    return dict(type='call_tool', tool=tool, args=args)


def cid(call_vars):
    return (call_vars or dict()).get('customer_id')


# ---------------------------------------------------------------- normalisation (§14.1)
def normalise(ev, st):
    if ev is None:
        return None
    e = dict(ev)
    k = e.get('kind')
    if k == 'accept' and st['q'] != 'none':          # §11.1 maps yes and accept identically for every open q
        e['kind'] = 'yes'
    if k == 'other' and e.get('st') == 'none' and st['q'] == 'help_first':
        e['kind'], e['st'] = 'yes', 'complete'
    if e.get('st') == 'none' and e.get('kind') != 'other':
        e['st'] = 'complete'
    if e.get('kind') in ('date', 'date_amount') and st['phase'] == 'third_party':
        e['kind'] = 'callback'
    if e.get('kind') == 'other' and st['q'] == 'confirm_name':
        e['kind'], e['who'] = 'who', 'unclear'
    return e


# ---------------------------------------------------------------- the step
def step(policy, st, event, tool_event, now, call_vars=None):
    st = copy.deepcopy(st)
    st['runs'] = st.get('runs', 0) + 1
    today = _d(now)
    cv = dict(call_vars or dict())
    if tool_event and st.get('pending'):
        node = tool_event.get('node') or st['pending']['node']
        st['_tc'][node] = [int(tool_event.get('success') or 0), int(tool_event.get('failure') or 0)]
        act = on_tool(policy, st, tool_event, today, cv)
    elif st.get('pending'):
        # a pending call whose counters never moved: a failure, never silently re-issued (§11.5)
        act = on_tool(policy, st, dict(node=st['pending']['node'], success=st['pending']['snap_success'],
                                       failure=st['pending']['snap_failure'], status_code=None, ok=None, data=None,
                                       no_delta=True), today, cv)
    else:
        ev = normalise(event, st)
        act = on_user(policy, st, ev, today, cv) if ev else resay(st)
    if act.get('type') == 'say_exact' and not str(act.get('text') or '').strip():
        act = dict(type='say_exact', text=sentence(policy, 'safe_repeat', D_SAFE))
    update_hangup(policy, st)
    return st, act


# ---------------------------------------------------------------- tool results
def on_tool(policy, st, te, today, cv):
    pend = st['pending']
    ds = int(te.get('success') or 0) - int(pend['snap_success'])
    df = int(te.get('failure') or 0) - int(pend['snap_failure'])
    sc = te.get('status_code')
    try:
        sc = int(sc) if sc not in (None, '') else None
    except Exception:
        sc = None
    ok = str(te.get('ok')).lower() == 'true'
    success = (not te.get('no_delta')) and ds > 0 and df <= 0 and (sc is None or sc < 400) and ok
    op = pend['op']
    data = te.get('data') if isinstance(te.get('data'), dict) else dict()
    if not success:
        return tool_failed(policy, st, te, today, cv)
    st['pending'] = None
    if op == 'verify':
        return verify_result(policy, st, data, cv)
    if op == 'account':
        load_products(policy, st, _account_rows(te), today)
        return account_statement(policy, st, today)
    if op == 'promise':
        i = _index(st, pend['product_id'])
        st['products'][i]['status'] = 'persisted'
        return next_write(policy, st, cv)
    if op == 'note':
        i = _index(st, pend['product_id'])
        p, pd = _p(st, i)
        p['status'], p['note'] = 'noted', pd['note_reason']
        st['notes'].append(dict(product_id=p['id'], reason=pd['note_reason']))
        return next_write(policy, st, cv)
    if op == 'callback':
        st['callbacks'].append(dict(date=st['_cb'][0], time=st['_cb'][1]))
        o, r = V(policy)['callback']
        return do_close(policy, st, o, r, D_FAREWELL)
    if op == 'transfer':
        st['transfers'].append(dict(queue=st['_xfer_queue']))
        o, r = st['_xfer_close']
        return do_close(policy, st, o, r, D_FAREWELL)
    return resay(st)


def tool_failed(policy, st, te, today, cv):
    pend = st['pending']
    tool = OP_TOOL[pend['op']]
    tp = (policy.get('tools') or dict()).get(tool) or dict()
    retries = int(tp.get('retries', 1))
    if pend['op'] == 'promise':
        i = _index(st, pend['product_id'])
        st['products'][i]['write_failures'] += 1
    if pend['attempt'] <= retries:   # retry with the same args, no speech
        pend['attempt'] += 1
        pend['snap_failure'] = int(te.get('failure') or pend['snap_failure'])
        pend['snap_success'] = int(te.get('success') or pend['snap_success'])
        return dict(type='call_tool', tool=tool, args=st['_last_args'])
    st['pending'] = None
    on_fail = str(tp.get('on_fail') or '')
    fail_say = tp.get('fail_say') or ''
    if pend['op'] == 'promise':
        i = _index(st, pend['product_id'])
        p, pd = _p(st, i)
        if on_fail.startswith('close'):
            o, r = V(policy)['write_failed']
            p['status'] = 'failed'
            return do_close(policy, st, o, r, (fail_say + ' ' + D_FAREWELL).strip())
        p['status'], pd['note_reason'] = 'failed', V(policy)['note']['write_error']
        return next_write(policy, st, cv)
    if pend['op'] == 'note':
        i = _index(st, pend['product_id'])
        st['products'][i]['status'] = 'noted'
        return next_write(policy, st, cv)
    if pend['op'] == 'transfer':   # continue the call, never claim the transfer happened
        return resay(st)
    if pend['op'] == 'callback':
        o, r = V(policy)['callback_failed']
        return do_close(policy, st, o, r, D_FAREWELL)
    o, r = V(policy)['unclear']
    return do_close(policy, st, o, r, D_FAREWELL)


def verify_result(policy, st, data, cv):
    idt = st['identity']
    qs = (policy.get('identity') or dict()).get('questions') or []
    if str(data.get('hint') or '') == 'day_month_swapped' and st['_id_hint'] < 1:
        st['_id_hint'] += 1
        return ask(st, D_HINT_MONTH, 'id_' + idt['order'][idt['idx']])
    verified = str(data.get('verified')).lower() == 'true'
    if verified:
        if str(data.get('all_verified')).lower() == 'true' or idt['idx'] + 1 >= len(idt['order']):
            st['verified'], st['phase'] = 'yes', 'account'
            return call(st, 'account', 'get_account', dict(customer_id=cid(cv)))
        idt['idx'] += 1
        return ask(st, qs[idt['idx']].get('ask') or D_SAFE, 'id_' + idt['order'][idt['idx']])
    max_wrong = int((policy.get('identity') or dict()).get('max_wrong') or 3)
    left = data.get('wrong_answers_left')
    try:
        idt['wrong'] = max_wrong - int(left) if left is not None else idt['wrong'] + 1
    except Exception:
        idt['wrong'] += 1
    if idt['wrong'] >= max_wrong:
        o, r = V(policy)['id_failed']
        return do_close(policy, st, o, r, (id_fail_line(policy) + ' ' + D_FAREWELL).strip())
    return ask(st, qs[idt['idx']].get('ask') or D_SAFE, 'id_' + idt['order'][idt['idx']])


def account_statement(policy, st, today):
    lines = [debt_intro(policy)] + [product_line(pd) for pd in st['_pd']]
    if len(st['products']) == 1:
        p, pd = _p(st, 0)
        p['status'], p['offer'] = 'proposed', dict(amount=pd['past_due'], date=iso(today))
        st['cur'] = 0
        st['offer'] = dict(product_ids=[p['id']], amount=pd['past_due'], date=iso(today), kind='full')
        text = ' '.join(x for x in lines + [pay_today_question(policy)] if x)
    else:
        st['all_today_asked'] = True
        text = ' '.join(x for x in lines + [D_ALL_TODAY] if x)
    st['phase'] = 'negotiation'
    return ask(st, text, 'pay_today')


# ---------------------------------------------------------------- writes and wrap-up
def next_write(policy, st, cv):
    while st['_queue']:
        pid = st['_queue'].pop(0)
        i = _index(st, pid)
        p = st['products'][i]
        if p['status'] == 'confirmed':
            st['_last_args'] = dict(customer_id=cid(cv), product_id=pid, amount=p['offer']['amount'], date=p['offer']['date'])
            return call(st, 'promise', 'create_promise', dict(st['_last_args']), product_id=pid)
    st['phase'] = 'wrapup'
    notes = (policy.get('writes') or dict()).get('notes') or dict()
    if notes.get('enabled') and not st['transfers']:
        for i, (p, pd) in enumerate(zip(st['products'], st['_pd'])):
            if p['status'] in ('refused', 'failed', 'open', 'proposed') and pd.get('note_reason') is None:
                pd['note_reason'] = V(policy)['note']['refused' if p['status'] != 'failed' else 'write_error']
            if p['status'] not in ('persisted', 'noted') and pd.get('note_reason') and not pd.get('_noted_try'):
                pd['_noted_try'] = True
                st['_last_args'] = dict(customer_id=cid(cv), product_id=p['id'], reason=pd['note_reason'])
                return call(st, 'note', 'add_note', dict(st['_last_args']), product_id=p['id'])
    if any(p['status'] == 'persisted' for p in st['products']):
        st['_wrapup_said'] = True
        st['q'] = 'none'
        text = D_RECORDED + ' ' + sentence(policy, 'sms_confirmation')
        st['_last_ask'] = text
        return dict(type='say_exact', text=text.strip())
    o, r = precedence(policy, st)
    return do_close(policy, st, o, r, D_FAREWELL)


def start_readback(policy, st):
    items, clamped = [], st.get('_clamped') or []
    for p in st['products']:
        if p['status'] == 'agreed':
            items.append(dict(product_id=p['id'], amount=p['offer']['amount'], date=p['offer']['date']))
    if not items:
        return None
    st['offer'] = None
    st['phase'] = 'readback'
    st['readback'] = dict(items=items, asked=((st.get('readback') or dict()).get('asked') or 0) + 1)
    if len(st['products']) > 1:
        st['cur'] = _index(st, items[0]['product_id']) if st['cur'] is not None else None
    return ask(st, readback_line(policy, st, items, clamped), 'readback')


def after_resolved(policy, st, today, cv):
    """A product was resolved (agreed, refused, noted, paid): move to the next open product, else read back or wrap up."""
    nxt = _open_products(st)
    if nxt and len(st['products']) > 1:
        return start_attempt(policy, st, nxt[0], today, from_today_ask=False)
    rb = start_readback(policy, st)
    if rb:
        return rb
    return next_write(policy, st, cv)


# ---------------------------------------------------------------- negotiation
def _last_bd_of_week(today, policy, weeks=0):
    monday = today - datetime.timedelta(days=today.weekday())
    d = monday + datetime.timedelta(days=7 * weeks + 6)
    while not is_business_day(d, policy) and d > monday:
        d = d - datetime.timedelta(days=1)
    return d


def plan_date(rule, today, pd, policy):
    if rule == 'deadline':
        return _d(pd['deadline'])
    if rule == 'last_business_day_next_week':
        return _last_bd_of_week(today, policy, 1)
    d = _last_bd_of_week(today, policy, 0)       # last_business_day_this_week; if today is that day: next week's
    if d <= today:
        d = _last_bd_of_week(today, policy, 1)
    return min(d, _d(pd['deadline']))


def plan_amount(rule, pd):
    if rule in ('floor', 'floor_again'):
        return pd['floor'], True
    if rule == 'full':
        return pd['past_due'], False
    return (pd['floor'], True) if pd['too_much'] else (pd['past_due'], False)


def start_attempt(policy, st, i, today, from_today_ask=True):
    p, pd = _p(st, i)
    st['cur'] = i
    if p['attempts'] >= len(pd['plan']):
        return refuse_product(policy, st, i, today)
    rule = pd['plan'][p['attempts']]
    date = plan_date(rule.get('date_rule'), today, pd, policy)
    amount, is_floor = plan_amount(rule.get('amount_rule'), pd)
    p['attempts'] += 1
    if is_floor:
        p['floor_offered'] = True
    p['status'], p['offer'] = 'proposed', dict(amount=amount, date=iso(date))
    st['offer'] = dict(product_ids=[p['id']], amount=amount, date=iso(date), kind='attempt_n')
    text = offer_line(pd, amount, iso(date), floor_clause=is_floor)
    return ask(st, text, 'offer')


def refuse_product(policy, st, i, today, cv=None):
    p, pd = _p(st, i)
    p['status'] = 'refused'
    pd['note_reason'] = pd.get('note_reason') or V(policy)['note']['refused']
    st['offer'] = None
    if len(st['products']) == 1:
        o, r = V(policy)['refused']
        return do_close(policy, st, o, r, D_FAREWELL)
    return after_resolved(policy, st, today, cv)


def agree(policy, st, i, amount, date, today, cv):
    p, pd = _p(st, i)
    p['status'], p['offer'] = 'agreed', dict(amount=amount, date=date)
    st['offer'] = None
    return after_resolved(policy, st, today, cv)


def date_event(policy, st, ev, today, cv):
    spec = dict((k, ev.get(k, '')) for k in ('rel', 'd', 'm', 'wd', 'wk', 'vague'))
    if spec.get('vague') == 'yes' or (not any(spec.get(k) for k in ('rel', 'd', 'm', 'wd')) and spec.get('wk') in ('next', 'after_next')):
        return vague_event(policy, st, today)
    named, kind = date_from_spec(today, parse_spec(';'.join(k + '=' + str(v) for k, v in spec.items())), policy)
    if kind != 'exact' or named is None:
        if st['counters']['clarify'] < 1:
            st['counters']['clarify'] += 1
            return ask(st, D_CLARIFY, 'exact_day')
        return resay(st)
    amt = ev.get('amt')
    multi = len(st['products']) > 1
    targets = list(range(len(st['products']))) if (ev.get('prod') == 'all' or (multi and st['cur'] is None and not ev.get('prod'))) else None
    if targets is None:
        idx = st['cur'] if st['cur'] is not None else 0
        if ev.get('prod') and str(ev.get('prod')).isdigit():
            idx = _valid_prod(st, ev, idx)
        targets = [idx]
    if len(targets) > 1:   # one date for all: per-product decision, clamp without separate acceptance
        st['_clamped'] = []
        for i in targets:
            p, pd = _p(st, i)
            if p['status'] not in ('open', 'proposed'):
                continue
            r = decide(today, pd['days_late'], 'exact', named, 0, policy)
            d = r['accepted'] or _d(pd['deadline'])
            if r['reason'] == 'after_deadline':
                st['_clamped'].append(p['id'])
            p['status'], p['offer'] = 'agreed', dict(amount=float(amt) if amt else pd['past_due'], date=iso(d))
        st['offer'] = None
        return after_resolved(policy, st, today, cv)
    i = targets[0]
    p, pd = _p(st, i)
    amount = float(amt) if amt else ((st['offer'] or dict()).get('amount') or (pd['floor'] if pd['too_much'] else pd['past_due']))
    r = decide(today, pd['days_late'], 'exact', named, 0, policy)
    reason = r['reason']
    if reason == 'ok':
        if multi and st['cur'] is not None and i != st['cur'] or (multi and st['cur'] is None):
            p['status'], p['offer'] = 'agreed', dict(amount=amount, date=iso(r['accepted']))
            return after_resolved(policy, st, today, cv)
        return agree(policy, st, i, amount, iso(r['accepted']), today, cv)
    if reason in ('non_business_day', 'after_deadline') and r['accepted']:
        d = iso(r['accepted'])
        p['status'], p['offer'] = 'proposed', dict(amount=amount, date=d)
        st['cur'] = i
        st['offer'] = dict(product_ids=[p['id']], amount=amount, date=d,
                           kind='customer' if reason == 'non_business_day' else 'deadline')
        sec = policy.get('on_non_business_day' if reason == 'non_business_day' else 'on_after_deadline') or dict()
        tpl = str(sec.get('say') or '')
        for token, val in (('<NAMED>', r['named']), ('<DATE>', r['accepted']), ('<DEADLINE>', r['deadline'])):
            tpl = tpl.replace(token, say_date(val) if val else '')
        text = (tpl + ' ' + 'That is ' + money(amount) + ' for your ' + pd['name'] + '.').strip()
        return ask(st, text, 'offer')
    return ask(st, 'That date has passed. ' + (st.get('_last_ask') or D_SAFE), st['q'])


def vague_event(policy, st, today):
    v = policy.get('on_vague') or dict()
    st['counters']['vague'] += 1
    i = st['cur'] if st['cur'] is not None else 0
    if st['q'] == 'pay_today':
        st['all_today_asked'] = True
    if st['counters']['vague'] > int(v.get('asks', 1)) and v.get('then') == 'offer_deadline' and st['products']:
        p, pd = _p(st, i)
        amount = pd['floor'] if pd['too_much'] else pd['past_due']
        p['status'], p['offer'] = 'proposed', dict(amount=amount, date=pd['deadline'])
        st['offer'] = dict(product_ids=[p['id']], amount=amount, date=pd['deadline'], kind='deadline')
        tpl = str(v.get('say_final') or '').replace('<DEADLINE>', say_date(_d(pd['deadline'])))
        return ask(st, tpl + ' That is ' + money(amount) + ' for your ' + pd['name'] + '.', 'offer')
    if st['products']:
        p, _ = _p(st, i)
        if p['status'] == 'proposed':
            p['status'], p['offer'] = 'open', None
    st['offer'] = None
    return ask(st, v.get('say_ask') or 'Which exact day can you make the payment?', 'exact_day')


def reject_event(policy, st, ev, today, cv):
    if not st['products']:
        return resay(st)
    multi = len(st['products']) > 1
    if multi and st['cur'] is None:    # "no" to the all-today ask: attempt 1 for the first open product
        nxt = _open_products(st)
        return start_attempt(policy, st, nxt[0], today) if nxt else after_resolved(policy, st, today, cv)
    i = st['cur'] if st['cur'] is not None else 0
    p, pd = _p(st, i)
    if st['q'] == 'pay_today' and ev.get('why') != 'too_much':   # a "not today" answers the today ask
        st['all_today_asked'] = True
    if ev.get('why') == 'too_much' and not p['floor_offered']:
        pd['too_much'] = True
        p['floor_offered'] = True
        date = (st['offer'] or dict()).get('date') or iso(today)
        p['status'], p['offer'] = 'proposed', dict(amount=pd['floor'], date=date)
        st['offer'] = dict(product_ids=[p['id']], amount=pd['floor'], date=date, kind='floor')
        return ask(st, offer_line(pd, pd['floor'], date, floor_clause=True), 'offer')
    if ev.get('why') == 'too_much':
        pd['too_much'] = True
    return start_attempt(policy, st, i, today)


def amount_event(policy, st, ev, today, cv):
    if not st['products']:
        return resay(st)
    i = st['cur'] if st['cur'] is not None else 0
    p, pd = _p(st, i)
    try:
        amt = float(ev.get('amt'))
    except Exception:
        return resay(st)
    date = (st['offer'] or dict()).get('date') or iso(today)
    if amt < pd['floor'] - 0.005:
        if p['floor_offered']:
            return start_attempt(policy, st, i, today)
        p['floor_offered'] = True
        p['status'], p['offer'] = 'proposed', dict(amount=pd['floor'], date=date)
        st['offer'] = dict(product_ids=[p['id']], amount=pd['floor'], date=date, kind='floor')
        return ask(st, 'I cannot record ' + money(amt) + '. ' + offer_line(pd, pd['floor'], date, True), 'offer')
    amt = min(amt, pd['past_due'])
    p['status'], p['offer'] = 'proposed', dict(amount=amt, date=date)
    st['offer'] = dict(product_ids=[p['id']], amount=amt, date=date, kind='customer')
    return ask(st, offer_line(pd, amt, date), 'offer')


def yes_event(policy, st, today, cv):
    q = st['q']
    if q in ('pay_today', 'offer') and st['offer']:
        o = st['offer']
        i = _index(st, o['product_ids'][0])
        return agree(policy, st, i, o['amount'], o['date'], today, cv)
    if q == 'pay_today' and len(st['products']) > 1:   # yes to all today
        for p, pd in zip(st['products'], st['_pd']):
            if p['status'] in ('open', 'proposed'):
                p['status'], p['offer'] = 'agreed', dict(amount=pd['past_due'], date=iso(today))
        return after_resolved(policy, st, today, cv)
    if q == 'readback' and st['readback']:
        st['_queue'] = []
        for it in st['readback']['items']:
            i = _index(st, it['product_id'])
            st['products'][i]['status'] = 'confirmed'
            st['_queue'].append(it['product_id'])
        return next_write(policy, st, cv)
    if q == 'support_offer':
        return transfer(policy, st, 'hardship', cv)
    if q == 'help_first':
        return dict(type='speak_free', node=_talk_node(st), hint='The customer agreed to continue with you.')
    return resay(st)


def no_event(policy, st, ev, today, cv):
    q = st['q']
    if q in ('pay_today', 'offer'):
        return reject_event(policy, st, dict(why='flat'), today, cv)
    if q == 'readback':
        if st['_what_change'] < 1:
            st['_what_change'] += 1
            return ask(st, D_WHAT_CHANGE, 'what_to_change')
    if q in ('readback', 'what_to_change'):
        for it in (st['readback'] or dict()).get('items') or []:
            i = _index(st, it['product_id'])
            st['products'][i]['status'] = 'refused'
            st['_pd'][i]['note_reason'] = V(policy)['note']['refused']
        if len(st['products']) == 1:
            o, r = V(policy)['refused']
            return do_close(policy, st, o, r, D_FAREWELL)
        return next_write(policy, st, cv)
    if q == 'support_offer':
        row = next((e for e in policy.get('events') or [] if e.get('topic') == 'hardship' and _none(e.get('note_reason'))), None)
        for i, (p, pd) in enumerate(zip(st['products'], st['_pd'])):
            if p['status'] in ('open', 'proposed'):
                p['status'], pd['note_reason'] = 'refused', V(policy)['note']['hardship']
                p['status'] = 'open'
        notes = (policy.get('writes') or dict()).get('notes') or dict()
        if len(st['products']) > 1 and notes.get('enabled'):
            for p, pd in zip(st['products'], st['_pd']):
                if p['status'] in ('open', 'proposed'):
                    p['status'] = 'refused'
            return next_write(policy, st, cv)
        o, r = V(policy)['hardship']
        return do_close(policy, st, o, r, ((row or dict()).get('say', '') + ' ' + D_FAREWELL).strip()
                        if row and row.get('say') and row.get('say') != 'I understand.' else D_FAREWELL)
    if q == 'help_first':
        return transfer(policy, st, 'human', cv)
    return resay(st)


def transfer(policy, st, key, cv):
    qmap = (policy.get('transfer') or dict()).get('queue_map') or dict()
    queue = qmap.get(key) or key
    pre = (policy.get('transfer') or dict()).get('pre_verification_queues') or []
    if st['verified'] != 'yes' and queue not in pre:
        return resay(st)
    st['_xfer_pre'] = 'yes' if (st['verified'] != 'yes' and queue in pre) else 'no'
    st['_xfer_queue'] = queue
    st['_xfer_close'] = list(V(policy)['xfer'].get(key) or V(policy)['unclear'])
    st['offer'] = None
    if st['cur'] is not None and st['products']:
        p = st['products'][st['cur']]
        if p['status'] == 'proposed':
            p['status'], p['offer'] = 'open', None
    st['_last_args'] = dict(customer_id=cid(cv), queue=queue)
    return call(st, 'transfer', 'transfer_to_agent', dict(st['_last_args']))


def _talk_node(st):
    return 'talk_post' if st['verified'] == 'yes' else 'talk_pre'


def topic_event(policy, st, ev, today, cv):
    t = ev.get('t')
    multi = len(st['products']) > 1
    if t == 'injection':
        return resay(st)
    if t == 'human':
        if st['q'] == 'help_first' or st['counters']['human_asks'] >= 1:
            return transfer(policy, st, 'human', cv)
        st['counters']['human_asks'] += 1
        row = event_row(policy, 'human')
        st['_q_prev'], st['_ask_prev'] = st['q'], st.get('_last_ask') or ''
        return ask(st, (row or dict()).get('say') or D_HELP_FIRST, 'help_first')
    if t in ('scam', 'robot', 'unknown_info'):
        row = event_row(policy, t)
        if st['phase'] == 'opening':
            return reask_name(policy, st, cv, (row or dict()).get('say') or '')
        return resay(st, (row or dict()).get('say') or '')
    if t == 'change_promise':
        row = event_row(policy, 'change_promise')
        return dict(type='say_exact', text=(row or dict()).get('say') or D_CHANGE)
    if t == 'terms':
        return resay(st, sentence(policy, 'no_other_terms', D_NO_TERMS))
    if t in ('decline', 'purpose') and st['phase'] == 'opening':
        return reask_name(policy, st, cv)        # rule 3: a question first, the ask that follows is counted
    if t in ('decline', 'purpose'):
        if st['phase'] == 'identity':
            st['identity']['refusals'] += 1
            if st['identity']['refusals'] >= 2:
                o, r = slot(policy, 'declined')
                return do_close(policy, st, o, r, D_FAREWELL)
            st['counters']['decline_explain'] += 1
            row = event_row(policy, t)
            return resay(st, (row or dict()).get('say') or '')
        return resay(st)
    if t == 'stop':
        st['counters']['stop_talking'] += 1
        if st['counters']['stop_talking'] < 2:
            return dict(type='speak_free', node=_talk_node(st), hint='The customer does not want to talk; acknowledge briefly.')
        if st['verified'] != 'yes':
            o, r = slot(policy, 'declined') if st['who'] == 'self' else slot(policy, 'unclear')
            return do_close(policy, st, o, r, D_FAREWELL)
        for i, p in enumerate(st['products']):      # every product not yet written or settled is refused
            if p['status'] in ('open', 'proposed', 'agreed', 'confirmed'):
                p['status'] = 'refused'
                st['_pd'][i]['note_reason'] = st['_pd'][i].get('note_reason') or V(policy)['note']['refused']
        if multi:
            return next_write(policy, st, cv)
        o, r = V(policy)['refused']
        return do_close(policy, st, o, r, D_FAREWELL)
    if st['verified'] != 'yes' or not st['products']:
        return resay(st)
    i = st['cur'] if st['cur'] is not None else 0
    if ev.get('prod') and str(ev.get('prod')).isdigit():
        i = _valid_prod(st, ev, i)
    if t == 'hardship':
        row = next((e for e in policy.get('events') or [] if e.get('topic') == 'hardship' and not _none(e.get('note_reason'))), None)
        st['counters']['support_offered'] += 1
        st['offer'] = None
        p = st['products'][i]
        if p['status'] == 'proposed':
            p['status'], p['offer'] = 'open', None
        return ask(st, (row or dict()).get('say') or 'I am sorry to hear that. Would you like me to connect you with our customer support team?',
                   'support_offer')
    if t == 'restructure':
        return transfer(policy, st, 'restructuring', cv)
    if t == 'dispute' and st['q'] in ('readback', 'what_to_change') and st.get('_rb_dispute', 0) < 1:
        st['_rb_dispute'] = st.get('_rb_dispute', 0) + 1     # "that's not what I agreed": ask what to change first
        return no_event(policy, st, dict(ev, kind='no'), today, cv)
    if t in ('paid', 'dispute'):
        row = event_row(policy, t)
        say = (row or dict()).get('say') or ''
        p, pd = _p(st, i)
        st['offer'] = None
        if not multi:
            p['status'] = 'paid' if t == 'paid' else 'open'
            if t == 'paid':
                p['offer'] = None
            o, r = V(policy)[t]
            return do_close(policy, st, o, r, (say + ' ' + D_FAREWELL).strip())
        p['status'] = 'paid' if t == 'paid' else 'refused'
        pd['note_reason'] = V(policy)['note'][t] or V(policy)['note']['refused']
        return after_resolved(policy, st, today, cv)
    return resay(st)


# ---------------------------------------------------------------- per-phase user handling
def on_user(policy, st, ev, today, cv):
    if ev.get('st') == 'partial':
        return dict(type='say_exact', text=sentence(policy, 'continue_line', D_CONTINUE))
    k = ev.get('kind')
    ph = st['phase']
    if ph == 'closed':
        return resay(st)
    if st['q'] == 'help_first':          # answers to "can I help you first?" mean the same in every phase
        if k == 'yes':
            st['q'], st['_last_ask'] = st.get('_q_prev') or 'none', st.get('_ask_prev') or st.get('_last_ask')
            return dict(type='speak_free', node=_talk_node(st), hint='The customer agreed to continue with you.')
        if k in ('no', 'reject') or (k == 'topic' and ev.get('t') == 'human'):
            return transfer(policy, st, 'human', cv)
    if k == 'topic' and ev.get('t') == 'injection':
        return resay(st)
    if ph == 'opening':
        return opening(policy, st, ev, today, cv)
    if ph == 'third_party':
        return third_party(policy, st, ev, today, cv)
    if ph == 'identity':
        return identity(policy, st, ev, today, cv)
    if ph == 'wrapup':
        if k == 'topic' and ev.get('t') == 'change_promise' or k in ('date', 'amount', 'date_amount'):
            row = event_row(policy, 'change_promise')
            return dict(type='say_exact', text=(row or dict()).get('say') or D_CHANGE)
        if st['_wrapup_said']:
            o, r = precedence(policy, st)
            return do_close(policy, st, o, r, D_FAREWELL)
        return resay(st)
    # negotiation / readback / account
    if k == 'topic':
        return topic_event(policy, st, ev, today, cv)
    if k in ('yes', 'accept'):
        return yes_event(policy, st, today, cv)
    if k == 'no':
        return no_event(policy, st, ev, today, cv)
    if k == 'reject':
        if st['q'] in ('readback', 'what_to_change', 'support_offer', 'help_first'):
            return no_event(policy, st, ev, today, cv)
        return reject_event(policy, st, ev, today, cv)
    if k in ('date', 'date_amount'):
        return date_event(policy, st, ev, today, cv)
    if k == 'amount':
        return amount_event(policy, st, ev, today, cv)
    return dict(type='speak_free', node=_talk_node(st), hint=st.get('_last_ask') or '')


def opening(policy, st, ev, today, cv):
    k, who = ev.get('kind'), ev.get('who')
    if k == 'yes':
        who = 'self'
    if k == 'no':
        who = 'other'
    if k == 'topic':
        return topic_event(policy, st, ev, today, cv)
    if k != 'who' and who is None:
        return reask_name(policy, st, cv)    # an identity answer or anything else never confirms the name (rule 3)
    party = ev.get('party') or ''
    if who == 'self':
        st['who'], st['phase'] = 'self', 'identity'
        qs = (policy.get('identity') or dict()).get('questions') or []
        if not qs:
            o, r = slot(policy, 'declined')
            return do_close(policy, st, o, r, D_FAREWELL)
        return ask(st, qs[0].get('ask') or D_SAFE, 'id_' + qs[0].get('field'))
    if who in ('other', 'misdialled', 'deceased') or party in ('relative', MISDIAL, 'deceased'):
        if party == MISDIAL or who == 'misdialled':
            row = who_row(policy, 'misdialled')
            o, r = (_none(row.get('outcome')), _none(row.get('reason'))) if row else V(policy)['unclear']
            return do_close(policy, st, o or V(policy)['unclear'][0], r, D_FAREWELL)
        if party == 'deceased' or who == 'deceased':
            row = who_row(policy, 'deceased')
            say = (row or dict()).get('say') or sentence(policy, 'condolence')
            o, r = (_none(row.get('outcome')), _none(row.get('reason'))) if row else V(policy)['unclear']
            return do_close(policy, st, o or V(policy)['unclear'][0], r, (say + ' Goodbye.').strip())
        st['who'], st['phase'] = 'other', 'third_party'
        return ask(st, fill_names(V(policy)['callback_say'] or 'When can I reach them?', cv), 'callback_time')
    return reask_name(policy, st, cv)      # unclear, handoff


def reask_name(policy, st, cv, prefix=''):
    """Re-ask the name question, counted against its cap (rule 3); at the cap close on the unclear slot."""
    sq = (policy.get('sentences') or dict())
    cap = int((sq.get('confirm_who') or sq.get('ask_identity') or dict()).get('max_times') or 2)
    if st['counters']['confirm_name'] >= cap:
        o, r = V(policy)['unclear']
        return do_close(policy, st, o, r, D_FAREWELL)
    st['counters']['confirm_name'] += 1
    q = name_question(policy, cv) or st.get('_last_ask') or D_SAFE
    st['phase'] = 'opening'
    out = ask(st, q, 'confirm_name')
    if prefix:
        out['text'] = (prefix + ' ' + out['text']).strip()
    return out


def _callback_ok(policy, st, d, tm, today, now_time):
    cb = (policy.get('writes') or dict()).get('callback') or dict()
    nb = add_business_days(today, 1, policy)
    days = [today, nb] if cb.get('days', 'today_or_next_business_day') else [today, nb]
    if d not in days or not is_business_day(d, policy) and d != today:
        return False
    start, end = cb.get('start', '00:00'), cb.get('end', '23:59')
    if not (start <= tm <= end):
        return False
    if cb.get('after_now', True) and d == today and tm <= now_time:
        return False
    return True


def third_party(policy, st, ev, today, cv):
    k = ev.get('kind')
    if k == 'who':
        if ev.get('who') == 'handoff':
            st['phase'] = 'opening'
            st['counters']['confirm_name'] += 1
            return ask(st, name_question(policy, cv), 'confirm_name')
        if ev.get('party') in (MISDIAL, 'deceased'):
            return opening(policy, st, ev, today, cv)
        return resay(st)
    if k != 'callback':
        return resay(st)     # a relative is told nothing; identity/amount/accept/topics are not acted on
    spec = dict((x, ev.get(x, '')) for x in ('rel', 'd', 'm', 'wd', 'wk', 'vague'))
    tm = str(ev.get('tm') or '')
    has_day = any(spec.get(x) for x in ('rel', 'd', 'wd'))
    d = None
    if has_day:
        d, kind = date_from_spec(today, parse_spec(';'.join(a + '=' + str(b) for a, b in spec.items())), policy)
    if not tm:
        if st['_ask_time'] < 1:
            st['_ask_time'] += 1
            return ask(st, D_ASK_TIME, 'callback_time')
        return resay(st)
    if d is None:
        d = today
    now_time = str(cv.get('now') or '')[11:16]
    if not re.match(r'^[0-9]{2}:[0-9]{2}$', tm):
        tm = ('0' + tm)[-5:] if re.match(r'^[0-9]:[0-9]{2}$', tm) else tm
    if _callback_ok(policy, st, d, tm, today, now_time):
        st['_cb'] = [iso(d), tm]
        st['_last_args'] = dict(customer_id=cid(cv), date=iso(d), time=tm)
        return call(st, 'callback', 'schedule_callback', dict(st['_last_args']))
    st['_cb_out'] += 1
    if st['_cb_out'] >= 2:
        o, r = V(policy)['callback_failed']
        return do_close(policy, st, o, r, D_FAREWELL)
    return ask(st, V(policy)['callback_retry_say'] or 'Could you suggest another time?', 'callback_time')


def identity(policy, st, ev, today, cv):
    k = ev.get('kind')
    idt = st['identity']
    qs = (policy.get('identity') or dict()).get('questions') or []
    if k == 'identity':
        field = idt['order'][idt['idx']]
        ans = str(ev.get('ans') or '').strip()
        fmt = str(qs[idt['idx']].get('format') or '') if idt['idx'] < len(qs) else ''
        if ('YYYY-MM-DD' in fmt and not re.match(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$', ans)) or \
                (re.search(r'\b4 digits\b', fmt) and not re.match(r'^[0-9]{4}$', ans)) or not ans:
            return resay(st)
        st['_last_args'] = dict(customer_id=cid(cv), field=field, answer=ans)
        return call(st, 'verify', 'verify_identity', dict(st['_last_args']))
    if k == 'topic':
        return topic_event(policy, st, ev, today, cv)
    if k == 'no':
        return topic_event(policy, st, dict(ev, kind='topic', t='decline'), today, cv) if st['q'].startswith('id_') else resay(st)
    return resay(st)


# ---------------------------------------------------------------- event parsing (the hub reads `ev`)
def parse_event(raw, st, topics=()):
    """The ev grammar -> dict, or None when stale / unparseable (stale events change nothing)."""
    if not raw:
        return None
    out = dict()
    for part in str(raw).split(';'):
        k, _, v = part.partition('=')
        out[k.strip()] = v.strip()
    if out.get('n') != st.get('tok') or out.get('n') == st.get('last_tok') and st.get('tok') != 'kstart':
        return None
    if out.get('kind') in topics and out.get('kind') not in ('identity', 'who', 'date', 'amount', 'date_amount', 'accept',
                                                             'reject', 'yes', 'no', 'callback', 'topic', 'other'):
        out['t'], out['kind'] = out['kind'], 'topic'
    return out


# ---------------------------------------------------------------- code-node wrapper (runs inside Freya)
CONTRACT_TOPICS = ['injection', 'hardship', 'dispute', 'paid', 'restructure', 'human', 'stop', 'decline', 'purpose',
                   'change_promise', 'terms', 'scam', 'robot', 'unknown_info', 'other']


def _int(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def _jsonish(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


def _flat_data(vars, prefix):
    """Rebuild data from flattened keys like t_get_account_response.data.products.0.type."""
    out = dict()
    for k in list(vars.keys()):
        if not str(k).startswith(prefix):
            continue
        path = str(k)[len(prefix):].split('.')
        cur = out
        for j, part in enumerate(path):
            if j == len(path) - 1:
                cur[part] = _jsonish(vars.get(k))
            else:
                cur = cur.setdefault(part, dict())
    def fix(x):
        if isinstance(x, dict):
            if x and all(str(k).isdigit() for k in x):
                return [fix(x[k]) for k in sorted(x, key=lambda s: int(s))]
            return dict((k, fix(v)) for k, v in x.items())
        return x
    return fix(out)


def read_tool(vars, st):
    pend = st.get('pending')
    if not pend:
        return None
    node = pend['node']
    s, f = _int(vars.get(node + '_success_count')), _int(vars.get(node + '_failure_count'))
    if s == pend['snap_success'] and f == pend['snap_failure']:
        return None
    tool = node[2:] if node.startswith('t_') else node
    data = _jsonish(vars.get(tool + '_data'))
    if not isinstance(data, dict):
        data = _flat_data(vars, node + '_response.data.')
    sc = vars.get(node + '_response.status_code') or vars.get(node + '_status_code')
    ok = vars.get(node + '_response.data.ok')
    if ok is None and isinstance(data, dict):
        ok = data.get('ok')
    return dict(node=node, success=s, failure=f, status_code=sc, ok=str(ok).lower() if ok is not None else None, data=data)


def _token(runs):
    us = datetime.datetime.now().microsecond + runs * 7919
    letters = 'abcdefghjkmnpqrstuvwxyz'
    out = 'k'
    for _ in range(5):
        out = out + letters[us % 23]
        us = us // 23
    return out


def _dump(st):
    s = json.dumps(st)
    two_c, two_o = '}' * 2, '{' * 2      # built, so this source never contains the pair itself
    while two_c in s or two_o in s:
        s = s.replace(two_c, '} }').replace(two_o, '{ {')
    return s


def hub_main(vars, policy):
    cvmap = (policy.get('meta') or dict()).get('call_vars') or dict()
    cv = dict((role, vars.get(name)) for role, name in cvmap.items())
    now = str(vars.get((policy.get('now') or dict()).get('var', 'now')) or cv.get('now') or '')
    st = _jsonish(vars.get('st'))
    if not isinstance(st, dict):
        st = init_state(policy, cv)
    st['tok'] = str(vars.get('ev_tok') or st.get('tok') or 'kstart')
    try:
        te = read_tool(vars, st)
        ev = None if te else parse_event(vars.get('ev'), st, CONTRACT_TOPICS)
        st2, act = step(policy, st, ev, te, now, cv)
        if ev:
            st2['last_tok'] = ev.get('n')
    except Exception as e:
        st2, act = st, dict(type='say_exact', text=sentence(policy, 'safe_repeat', D_SAFE))
        vars['hub_error'] = str(e)[:200]
    t = act.get('type')
    if t == 'say_exact':
        vars['route'], vars['say_next'] = 'say', act['text']
    elif t == 'speak_free':
        vars['route'], vars['talk_hint'] = act.get('node') or 'talk_pre', act.get('hint') or ''
    elif t == 'call_tool':
        tool = act['tool']
        vars['route'], vars['w_go_' + tool] = TOOL_NODE[tool], 'go'
        for k, v in (act.get('args') or dict()).items():
            vars['w_' + tool + '_' + k] = v
    elif t == 'close':
        vars['route'], vars['farewell'] = 'close', act.get('farewell') or D_FAREWELL
    if t == 'close':
        o, r = act.get('outcome'), act.get('reason')
    else:
        h = st2.get('hangup') or dict()
        o, r = h.get('outcome'), h.get('reason')
        if not o:
            o, r = slot(policy, 'unclear')
    vars['close_outcome'], vars['close_reason'] = o or '', r or ''
    vars['route_ok'] = 'yes' if st2.get('verified') == 'yes' else 'no'
    vars['xfer_pre'] = st2.get('_xfer_pre') or 'no'
    new = _token(st2.get('runs', 0))
    st2['tok'] = new
    vars['ev_tok'] = new
    vars['st'] = _dump(st2)


def hub_source(policy):
    """The full code-node string: date core + reducer + policy literal + call. No double braces."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    dates_src = open(os.path.join(here, 'dates.py')).read()
    red_src = open(os.path.join(here, 'reducer.py')).read()
    def strip(x):   # source quotes are for the trace, not the runtime (keeps the node small)
        if isinstance(x, dict):
            return dict((k, strip(v)) for k, v in x.items() if k not in ('source', 'superseded'))
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    lit = json.dumps(_dump(strip(policy)))
    code = dates_src + '\n\n' + red_src + '\n\nPOLICY = json.loads(' + lit + ')\nhub_main(vars, POLICY)\n'
    if '{' * 2 in code or '}' * 2 in code:
        raise ValueError('hub source contains double braces')
    compile(code, 'hub', 'exec')
    return code
