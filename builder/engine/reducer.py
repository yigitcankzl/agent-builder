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
        is_business_day, say_date, shift_to_business_day
except Exception:
    pass

# ---------------------------------------------------------------- contract defaults (DEFAULT, not brief values)
D_FAREWELL = 'Thank you, goodbye.'
D_RECORDED = 'Your promise is recorded.'
D_SAFE = 'Sorry, could you say that again?'
D_CONTINUE = 'Go on, please.'
D_NO_TERMS = 'There are no other terms.'
D_CHANGE = 'You can change it in the mobile app.'
D_WHAT_CHANGE = 'What would you like to change?'
D_CLARIFY = 'Sorry, which exact date do you mean?'
D_HINT_MONTH = 'Could you say the month as a word, please?'
D_HELP_FIRST = 'Can I help you with this first?'
D_ASK_TIME = 'At what time could I reach them?'
D_ALL_TODAY = 'Can you pay all of them today?'
D_SUPPORT = 'I am sorry to hear that. Would you like me to connect you with our <DESK>?'
D_DESK = 'customer support team'


def desk_name(row):
    """The support desk's name in the brief's own words ("offer the hardship desk" -> hardship desk), read from the row's
    verbatim source quotes only (the effect is the bridge's paraphrase). Else the contract default."""
    if (row or dict()).get('desk'):
        return row['desk']
    quotes = ' '.join(str(q.get('quote') or '') for q in (row or dict()).get('source') or [] if isinstance(q, dict))
    m = re.search(r'\boffer (?:the |our |a )?([a-z][a-z ]{0,30}?\b(?:team|desk|unit|department|line))\b', quotes, re.I)
    return m.group(1).lower() if m else D_DESK


D_PROTECT = 'These questions protect your account.'
D_REACH = 'Could you tell me when I can reach {title} {last_name}?'   # the kit (PUB-02) checks 'when'
D_OVERDUE = 'The rest stays overdue.'
D_LOWEST = 'That was the lowest amount I can offer.'
D_WHICH_DAY = 'Which day would suit you?'
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
    return '%.2f' % float(x)


def iso(d):
    return d.isoformat() if d else None


def _d(s):
    return datetime.date.fromisoformat(str(s)[:10])


def sentence(policy, key, default=''):
    s = (policy.get('sentences') or dict()).get(key)
    if isinstance(s, dict):
        return s.get('text') or default
    return s or default


def brief_sentence(policy, key, default=''):
    """A sentence only when the brief words it (the bridge's own defaults, source file 'default', do not count)."""
    s = (policy.get('sentences') or dict()).get(key)
    if isinstance(s, dict) and (s.get('default') or (s.get('source') and all(
            isinstance(q, dict) and q.get('file') == 'default' for q in s.get('source')))):
        return default
    return sentence(policy, key, default)


def fill_names(text, vars_):
    out = str(text or '')
    for k, v in (vars_ or dict()).items():
        if v not in (None, ''):
            out = out.replace('{' + k + '}', str(v))
    out = re.sub(r'\{[a-z_]+\}', '', out)      # a call variable the session did not send (biz-1: no title) is left out
    return re.sub(r'\s+([?.,!])', r'\1', re.sub(r'\s{2,}', ' ', out)).strip()


def name_question(policy, cv):
    """The name question: sentences.confirm_who (contract key), its run-to-run variant ask_identity, or the who rule
    for an unclear speaker."""
    q = sentence(policy, 'confirm_who') or sentence(policy, 'ask_identity')
    if not q:
        q = next((w.get('say') for w in policy.get('who_rules') or [] if w.get('who') == 'unclear' and w.get('say')), '')
    return fill_names(q, cv)


def caller_line(policy):
    """The brief-backed opening identity, without a recording notice or any account detail."""
    for h in policy.get('hooks') or []:
        if h.get('point') != 'opening' or not h.get('text'):
            continue
        for part in re.split(r'(?<=[.!?])\s+', str(h['text']).strip()):
            if not re.search(r'\brecord(?:ed|ing)\b', part, re.I) and re.search(
                    r"\b(?:assistant|calling from|this is|I am|I'm)\b", part, re.I):
                return part
    desc = str((policy.get('meta') or dict()).get('agent_self_description') or '').strip().rstrip('.')
    if not desc:
        return ''
    return desc + '.' if desc.lower().startswith(('i am ', "i'm ", 'this is ')) else 'I am ' + desc + '.'


def pay_today_question(policy):
    return sentence(policy, 'pay_today') or sentence(policy, 'ask_today') or sentence(policy, 'first_ask') or \
        'Can you make this payment today?'


def farewell(policy):
    return sentence(policy, 'farewell') or sentence(policy, 'goodbye') or D_FAREWELL


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


def party_row(policy, party):
    return next((w for w in policy.get('who_rules') or [] if w.get('party') == party), None)


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

    table = (policy.get('closing') or dict()).get('table') or []

    xfer_out = set(pair(r)[0] for r in rows('restructure') + rows('human') if pair(r)[0])

    def pick(label, value, key=None):
        if value and value[0]:
            return value
        row = next((r for r in table if key and _none(r.get('reason')) == key and _none(r.get('outcome'))), None)
        if row:   # the closing-table row named by the contract key
            log.append(label + ' missing: closing row ' + key + ' used')
            return pair(row)
        rx = WHEN_RX.get(key)
        row = next((r for r in table if rx and _none(r.get('reason')) and re.search(rx, str(r.get('when') or ''), re.I)
                    and not (key == 'hardship' and _none(r.get('outcome')) in xfer_out)), None)
        if row:   # a renamed code (refused -> no_commitment): the closing row whose 'when' describes the situation
            log.append(label + ' missing: closing row by its when (' + str(row.get('reason')) + ') used')
            return pair(row)
        log.append(label + ' missing: unclear slot used')
        return unclear
    hard = [r for r in rows('hardship') if _none(r.get('outcome'))]
    # accepted = the transfer to the hardship queue (its closing reason is the queue name); declined = any other row
    hq = queue_for(policy, 'hardship')
    xfer_out = set(pair(r)[0] for r in rows('restructure') + rows('human') if pair(r)[0]) - set([pair(r)[0] for r in rows('paid')])
    if tool_absent(policy, 'transfer_to_agent'):
        xfer_out = set()
    # accepted = the transfer to the hardship queue: its reason names the queue, or its outcome is the transfer outcome
    is_acc = lambda r: bool(hq) and (_none(r.get('reason')) == hq or _none(r.get('outcome')) in xfer_out)
    acc_row = next((r for r in (policy.get('closing') or dict()).get('table') or [] if is_acc(r)), None)
    hard_accept = next((r for r in hard if is_acc(r)), acc_row)
    hard_decline = next((r for r in hard if not is_acc(r)), None)
    stops = rows('stop')
    stop_after = next((r for r in stops if pair(r) != declined), stops[0] if stops else None)
    paid_row = (rows('paid') or [None])[0]
    dispute_row = (rows('dispute') or [None])[0]
    out = dict(log=log, unclear=unclear, declined=pick('slot declined', declined),
               id_failed=pick('slot id_failed', slot(policy, 'id_failed')),
               callback_failed=pick('slot callback_failed', slot(policy, 'callback_failed')),
               write_failed=pick('slot write_failed', slot(policy, 'write_failed')),
               refused=pick('events stop (after verification)', pair(stop_after), 'refused'),
               hardship=pick('events hardship (declined)', pair(hard_decline), 'hardship'),
               dispute=pick('events dispute', pair(dispute_row), 'dispute'),
               paid=pick('events paid', pair(paid_row) if paid_row else slot(policy, 'paid')))
    out['xfer'] = dict(restructuring=pick('events restructure', pair((rows('restructure') or [None])[0])),
                       human=pick('events human', pair((rows('human') or [None])[0])),
                       hardship=pick('events hardship (accepted)', pair(hard_accept)))
    nr = (((policy.get('writes') or dict()).get('notes') or dict()).get('reasons') or dict())
    out['note'] = dict(refused=_none(nr.get('refused')) or _none((stop_after or dict()).get('note_reason')) or NOTE_REFUSED,
                       hardship=_none((hard_decline or dict()).get('note_reason')) or out['hardship'][1],
                       dispute=_none((dispute_row or dict()).get('note_reason')) or out['dispute'][1],
                       paid=_none((paid_row or dict()).get('note_reason')),
                       write_error=out['write_failed'][1])
    # the promise outcome: the closing-table row that no event, who rule or slot uses and whose "when" names a promise
    used = set(x[0] for x in (out['refused'], out['hardship'], out['dispute'], out['paid'], unclear, out['declined'],
                              out['id_failed']) if x[0]) | set(v[0] for v in out['xfer'].values() if v[0])
    prom = slot(policy, 'promise')
    if not prom[0]:   # the reason-less closing-table row that no event, who rule or slot uses
        for r in (policy.get('closing') or dict()).get('table') or []:
            if _none(r.get('outcome')) and _none(r.get('outcome')) not in used and not _none(r.get('reason')):
                prom = pair(r)
                break
    if not prom[0]:
        log.append('promise outcome missing: unclear slot used')
        prom = unclear
    out['promise'] = prom
    others = [w for w in policy.get('who_rules') or [] if w.get('who') == 'other' and w.get('party', 'relative') in ('relative', '', None)]
    cb_ok = next((w for w in others if pair(w) != out['callback_failed'] and pair(w)[0]), others[0] if others else None)
    if not cb_ok or not pair(cb_ok)[0]:
        cb_ok = next((w for w in policy.get('who_rules') or [] if w.get('who') == 'busy' and pair(w)[0]), cb_ok)
    if (not cb_ok or not pair(cb_ok)[0]) and next((r for r in table if _none(r.get('reason')) == 'callback'), None):
        cb_ok = next(r for r in table if _none(r.get('reason')) == 'callback')
    out['callback'] = pick('who_rules other (callback)', pair(cb_ok))
    if out['callback'][0] and not out['callback'][1]:    # a reason-less callback row: the closing row named callback
        row = next((r for r in table if _none(r.get('outcome')) == out['callback'][0] and _none(r.get('reason')) == 'callback'), None)
        if row:
            log.append('who_rules other (callback) has no reason: closing row callback used')
            out['callback'] = pair(row)
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


def close_action(outcome, reason, text):
    return dict(type='close', outcome=outcome, reason=_none(reason), farewell=(text or D_FAREWELL).strip())


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
              _wrapup_said=False, _what_change=0, _id_hint=0, _id_retry=0, _confirmed_readback=None,
              _readback_valid=False)
    st['counters']['confirm_name'] = 1          # the greet speaks the name question (§12 choice 2)
    st['_cid'] = cid(call_vars or dict())
    for h in policy.get('hooks') or []:
        if isinstance(h, dict) and h.get('expects_answer') and h.get('point') != 'on_no_promise':
            st.setdefault('_hook_skip', []).append(str(h.get('id')) + ':expects_answer')
        elif isinstance(h, dict) and h.get('point') == 'opening':
            st.setdefault('_hooks_said', []).append(h.get('id'))
    st['_last_ask'] = name_question(policy, call_vars or dict())
    return st


# ---------------------------------------------------------------- products
def _round(v, how, to):
    q = 1.0 if str(to or '').lower() in ('unit', 'units', 'whole', 'integer', '1') else (_num(to) or 0.01)
    x = v / q
    if abs(x - round(x)) <= 1e-6:
        x = round(x)                   # already whole (float noise)
    elif how == 'up':
        x = -int(-x // 1)
    elif how == 'down':
        x = int(x // 1)
    else:
        x = int((x + 0.5 + 1e-7) // 1)   # nearest = half up ('rounded half up to the penny': 531.275 -> 531.28)
    return round(x * q, 2)


def _num(x):
    try:
        return float(x)
    except Exception:
        return None


def _floor(policy, row):
    """floor_by_type[type] (or '*'): kind field|account_field (field), percent|percent_of_past_due (percent),
    fixed (amount), max_fixed_percent (amount, percent); round up|down|nearest to cents (default) or units. Never above
    the full amount; no rule -> the full amount. acceptance full_only keeps the floor (offered on 'too much')."""
    full = float(row.get('past_due') or 0)
    fbt = (policy.get('products') or dict()).get('floor_by_type') or dict()
    fb = fbt.get(str(row.get('type'))) or fbt.get('*') or fbt.get('default')
    if not isinstance(fb, dict):
        return full
    kind = str(fb.get('kind') or ('account_field' if fb.get('field') else '')).lower()
    pct, fix = _num(fb.get('percent')), _num(fb.get('amount') if fb.get('amount') is not None else fb.get('fixed'))
    how, to = str(fb.get('round') or fb.get('rounding') or 'nearest').lower(), fb.get('round_to') or fb.get('to') or fb.get('increment')
    if kind in ('field', 'account_field') and fb.get('field') and row.get(fb['field']) is not None:
        v = float(row.get(fb['field']))
    elif kind in ('percent', 'percent_of_past_due') and pct is not None:
        v = _round(full * pct / 100.0, how, to)
    elif kind == 'fixed' and fix is not None:
        v = fix
    elif kind in ('max_fixed_percent', 'max') and fix is not None and pct is not None:
        v = max(fix, _round(full * pct / 100.0, how, to))
    else:
        return full
    return min(v, full)


def too_much_on_deadline(policy):
    """Where the 'too much' floor offer goes: amounts.too_much_date (deadline | today | offer), else the brief's
    too_much rule naming the deadline (clean-1: 'offer the floor once, on the deadline'), else the offer's day."""
    a = policy.get('amounts') or dict()
    if a.get('too_much_date'):
        return str(a['too_much_date']) == 'deadline'
    return bool(re.search(r'\bon the deadline\b|\bat the deadline\b', str(a.get('too_much') or ''), re.I))


def amount_fits(policy, pd, amt):
    kind, x = accept_rule(policy)
    if kind == 'full_or_floor':      # only the full balance or exactly the floor
        return abs(amt - pd['past_due']) < 0.005 or abs(amt - pd['floor']) < 0.005
    if kind == 'full_only':          # a volunteered amount must be the full balance (the floor is still offered)
        return abs(amt - pd['past_due']) < 0.005
    low = x if kind == 'min_x' and x is not None else pd['floor']
    return min(low, pd['past_due']) - 0.005 <= amt and (amt <= pd['past_due'] + 0.005 or kind == 'above_full_allowed')


def accept_rule(policy):
    """amounts.acceptance: floor_to_full (default) | full_only | min_x (with min) | above_full_allowed; a string or
    dict(kind=, min=)."""
    a = (policy.get('amounts') or dict()).get('acceptance')
    if isinstance(a, dict):
        return str(a.get('kind') or 'floor_to_full'), _num(a.get('min') if a.get('min') is not None else a.get('x'))
    return (str(a), None) if a in ('floor_to_full', 'full_only', 'min_x', 'above_full_allowed', 'full_or_floor') else ('floor_to_full', None)


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


def get_path(obj, path):
    """'data.result.verified' / 'item.balance.past_due' -> the value, or None. The first segment names the root
    ('data' = the response data, 'item' = one product row) and is dropped; digits index lists."""
    parts = [x for x in str(path or '').split('.') if x]
    if parts and parts[0] in ('data', 'item'):
        parts = parts[1:]
    cur = obj
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def tr_path(policy, tool, key):
    return ((policy.get('tool_results') or dict()).get(tool) or dict()).get(key)


def tr_get(policy, tool, key, data, default_key):
    """A tool-result field through policy.tool_results[tool][key] (nested), else data[default_key]."""
    path = tr_path(policy, tool, key)
    v = get_path(data, path) if path and isinstance(data, dict) else None
    return v if v is not None else (data.get(default_key) if isinstance(data, dict) else None)


def _account_rows(tool_event, policy=None):
    data = (tool_event or dict()).get('data')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None
    path = tr_path(policy or dict(), 'get_account', 'products')
    if path and isinstance(data, dict) and isinstance(get_path(data, path), list):
        return [_scale_row(policy, _row_paths(policy, r)) for r in get_path(data, path) if isinstance(r, dict)]
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = data.get('products', data.get('data')) or (lists[0] if lists else data)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = None
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = data.get('products') or (lists[0] if lists else None)
    return [_scale_row(policy or dict(), _row_paths(policy or dict(), r)) for r in (data or []) if isinstance(r, dict)]


def amount_scale(policy):
    """tool_results.get_account.amount_scale: account amounts in minor units (e.g. 0.01 for cents); absent -> 1."""
    v = _num(((policy.get('tool_results') or dict()).get('get_account') or dict()).get('amount_scale'))
    return v if v and v > 0 else 1.0


def _scale_row(policy, r0):
    """Row amounts (past_due, the floor field of its type) to major units; policy amounts (fixed, min_x) are already
    major units and are never scaled."""
    k = amount_scale(policy)
    if k == 1.0:
        return r0
    r = dict(r0)
    fb = ((policy.get('products') or dict()).get('floor_by_type') or dict()).get(str(r.get(pfield(policy, 'type'))))
    names = [pfield(policy, 'past_due'), 'past_due'] + ([fb['field']] if isinstance(fb, dict) and fb.get('field') else [])
    for name in set(names):
        if _num(r.get(name)) is not None:
            r[name] = round(float(r[name]) * k, 2)
    return r


def api_amount(policy, amount):
    """A promise amount in the bank's unit: divided by the scale, a whole number for minor units."""
    k = amount_scale(policy)
    if k == 1.0:
        return amount
    v = float(amount) / k
    return int(round(v)) if k < 1 else round(v, 2)


def _row_paths(policy, r0):
    """A product row with its nested fields (tool_results.get_account item.* paths) copied to the names the reducer
    reads (products.fields roles, the floor field per type). A row without paths is unchanged."""
    paths = (policy.get('tool_results') or dict()).get('get_account') or dict()
    if not any(str(v).startswith('item.') for v in paths.values()):   # flat renames (item.age) too, not only nested
        return r0
    r = dict(r0)
    for role in ('id', 'type', 'past_due', 'days_late'):
        v = get_path(r0, paths.get(role))
        if v is not None:
            r[pfield(policy, role)] = v
    t = r.get(pfield(policy, 'type'))
    fb = ((policy.get('products') or dict()).get('floor_by_type') or dict()).get(str(t)) or dict()
    v = get_path(r0, paths.get('floor.' + str(t)))
    if v is not None and isinstance(fb, dict) and fb.get('field'):
        r[fb['field']] = v
    return r


def pfield(policy, role):
    """Account-row field name for a contract role (id, type, past_due, days_late) from policy.products.fields."""
    return ((policy.get('products') or dict()).get('fields') or dict()).get(role) or \
        dict(id='product_id').get(role, role)


def load_products(policy, st, rows, today):
    st['products'], st['_pd'] = [], []
    fid, ftype, fdue, flate = (pfield(policy, k) for k in ('id', 'type', 'past_due', 'days_late'))
    def get(row, name, role):
        if name in row:
            return row[name]
        default = dict(id='product_id').get(role, role)       # the bridge named a field the row does not have
        if default in row:
            return row[default]
        if role == 'id':
            ids = [k for k in row if str(k).endswith('_id')]
            return row[ids[0]] if len(ids) == 1 else None
        return None
    for r0 in rows:
        r = dict(r0)
        r['product_id'], r['type'] = get(r0, fid, 'id'), get(r0, ftype, 'type')
        r['past_due'], r['days_late'] = get(r0, fdue, 'past_due'), get(r0, flate, 'days_late')
        dl = int(float(r.get('days_late') or 0))
        band = _band(policy, dl)
        dline = deadline_for(today, dl, policy)
        route = ((policy.get('products') or dict()).get('route_by_type') or dict()).get(str(r.get('type')))
        st['products'].append(dict(id=str(r.get('product_id')), status='route_pending' if route else 'open', attempts=0, floor_offered=False,
                                   write_failures=0, offer=None, note=None))
        st['_pd'].append(dict(id=str(r.get('product_id')), type=str(r.get('type')), name=_name(policy, r), past_due=float(r.get('past_due') or 0),
                              days_late=dl, floor=_floor(policy, r), band=band.get('name'), deadline=iso(dline),
                              plan=_plan(policy, band), too_much=False, note_reason=None, refused_offers=[]))
        if route:
            st['_pd'][-1]['route'] = route
    distinct_names(st)


def distinct_names(st):
    """Products that share a spoken name ('loan', 'loan') are named by their type instead, then numbered."""
    names = [pd['name'] for pd in st['_pd']]
    for i, pd in enumerate(st['_pd']):
        if names.count(pd['name']) > 1:
            pd['name'] = str(pd.get('type') or pd['name']).replace('_', ' ')
    names = [pd['name'] for pd in st['_pd']]
    for i, pd in enumerate(st['_pd']):
        if names.count(pd['name']) > 1:
            pd['name'] = '%s %d' % (pd['name'], names[:i + 1].count(pd['name']))


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
    conf = sentence(policy, 'confirm') or sentence(policy, 'readback_confirm') or sentence(policy, 'confirm_readback') or \
        sentence(policy, 'confirm_arrangement') or 'Do you confirm?'
    return 'To confirm, ' + '; '.join(parts) + '. ' + conf


def ask(st, text, q):
    st['_resay_n'] = st.get('_resay_n', 0) + 1 if text == st.get('_last_ask') else 0   # the same words again count as a repeat
    st['q'] = q
    st['_last_ask'] = text
    return dict(type='say_exact', text=text)


OUR_OFFERS = ('floor', 'attempt_n')   # offers the agent proposed (PUB-06); a read-back of the customer's own date is re-said
RESAY_CAP = 3   # DEFAULT cap for every q: the same open question re-said this many times in a row, then loop_break()
D_OFFER_NUDGE = "Sorry, I didn't catch that. Can you manage that?"   # contract default: no amount, date, or floor clause
D_RB_CLARIFY = 'Do you confirm that exact read-back, yes or no?'


def offer_is_open(st):
    return st.get('q') == 'offer' and (st.get('offer') or dict()).get('kind') in OUR_OFFERS


def readback_item(st, product_id):
    return next((x for x in ((st.get('readback') or dict()).get('items') or []) if x['product_id'] == product_id), None)


def void_readback(st, rejected=False):
    """Invalidate the current terms; a change keeps them as the last restorable plan, an explicit no does not."""
    rb = st.get('readback')
    if not rb or not st.get('_readback_valid', True):
        return
    if not rejected:
        st['_rb_restore'] = dict(readback=copy.deepcopy(rb), products=copy.deepcopy(st['products']),
                                 note_reasons=[pd.get('note_reason') for pd in st['_pd']])
    st['_readback_valid'] = False
    st.pop('_confirmed_readback', None)


def offer_chatter(st):
    """Chatter (kind=other or a partial) while our offer is open: a short neutral line, never free talk.
    The offer itself is spoken in full only once per attempt. After the cap, the open question's on-cap path."""
    key = (st['offer'].get('amount'), st['offer'].get('date'), st['offer'].get('kind'))
    if st.get('_offer_chat_key') != key:
        st['_offer_chat'], st['_offer_chat_key'] = 0, key
    st['_offer_chat'] = st.get('_offer_chat', 0) + 1
    if st['_offer_chat'] > RESAY_CAP:
        st['_offer_chat'] = 0
        return dict(type='_loop')
    return ask(st, D_OFFER_NUDGE, 'offer')


def resay(st, prefix=''):
    if st.get('q') == 'offer' and (st.get('offer') or dict()).get('kind') in OUR_OFFERS:   # heard, not answered: only the day
        return ask(st, ((prefix + ' ') if prefix else '') + D_WHICH_DAY, 'exact_day')
    st['_resay_n'] = st.get('_resay_n', 0) + 1
    if st['_resay_n'] > RESAY_CAP:
        st['_resay_n'] = 0
        return dict(type='_loop')         # step() turns it into the stage's on-cap action (loop_break)
    text = ((prefix + ' ') if prefix else '') + reask_line(st)
    return dict(type='say_exact', text=text.strip())


def reask_line(st):
    """The open question again, without the statement before it (a debt intro is never re-said as if new); the
    read-back is re-said whole."""
    last = st.get('_last_ask') or D_SAFE
    if st.get('q') == 'readback':
        return last
    parts = re.split(r'(?<=[.?!])\s+', last.strip())
    if len(parts) > 1 and parts[-1].endswith('?'):
        return parts[-1]
    return last


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
    close_for = dict((v['note'][k], v[k]) for k in ('dispute', 'hardship', 'refused') if v['note'].get(k))
    for p, pd in zip(st['products'], st['_pd']):
        r = p['note'] or pd.get('note_reason') or (v['note']['refused'] if p['status'] == 'refused' else None)
        if r and r != paid_note:
            o, cr = close_for.get(r) or (v['refused'][0], r)    # the note reason's own close code (dispute -> account_dispute)
            return o or v['refused'][0], cr
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


def do_close(policy, st, outcome, reason, text):
    fw = farewell(policy)
    text = (text or D_FAREWELL).replace(D_FAREWELL, fw)      # the brief's goodbye wherever the contract default stood
    if not outcome:
        outcome, reason = fallback_outcome(policy)
    st['phase'], st['q'], st['outcome'], st['reason'] = 'closed', 'none', outcome, _none(reason)
    st['offer'] = None
    return close_action(outcome, reason, text)


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
    if k == 'accept' and st['q'] not in ('none', 'readback', 'what_to_change'):
        e['kind'] = 'yes'
    if k == 'other' and e.get('st') == 'none' and st['q'] == 'help_first':
        e['kind'], e['st'] = 'yes', 'complete'
    if e.get('st') == 'none' and e.get('kind') != 'other':
        e['st'] = 'complete'
    if e.get('kind') in ('date', 'date_amount') and (st['phase'] == 'third_party' or
                                                      (st['phase'] in ('opening', 'identity') and str(e.get('tm') or '').strip())):
        e['kind'] = 'callback'           # a day with a time before the account is discussed is a call-time preference
    if e.get('kind') == 'other' and st['q'] == 'confirm_name':
        e['kind'], e['who'] = 'who', 'unclear'
    # Live extractors sometimes preserve the secondary question in t= but omit also=topic.
    if e.get('kind') != 'topic' and e.get('t') in TOPIC_RANK and e.get('t') != 'other' and not e.get('also_t'):
        e['also_t'] = e['t']
    # §1.5: in the opening a stated speaker ranks above any topic but injection (PUB-02 live: 'No, I'm her husband.
    # What is this about?' came as t=purpose;also=who;who=other and was re-asked into an unclear close); in the security
    # questions an answer ranks above any topic but injection. The topic stays as also_t (an answer topic is answered).
    # While the authority question is open, that promotion must not turn a denial into who=self (PUB-03: t=purpose;who=self
    # opened the security questions). The gate reads the topic itself.
    if e.get('kind') == 'topic' and e.get('t') != 'injection' and st.get('q') != 'gate':
        if st['phase'] == 'opening' and e.get('who') in ('self', 'other', 'unclear', 'handoff', 'busy'):
            e['kind'], e['also_t'], e['also'] = 'who', e.get('t'), 'topic'
        elif st['phase'] == 'identity' and str(e.get('ans') or '').strip() and str(st.get('q') or '').startswith('id_'):
            e['kind'], e['also_t'], e['also'] = 'identity', e.get('t'), 'topic'
    a = e.get('also_t') or e.get('also')
    # only hardship (A32: before persuasion and restructuring) and injection outrank the primary event through also=;
    # any other also-topic never outranks a date / amount / accept / yes (a proposal is never a refusal, A29)
    if a in TOPIC_OVERRIDE and (st.get('verified') == 'yes' or a == 'injection') and e.get('t') != 'injection':
        if e.get('kind') == 'topic':
            e['t'], e['also'] = a, 'none'
        else:
            e['kind'], e['t'], e['also'] = 'topic', a, e.get('kind')
    return e


TOPIC_RANK = ['injection', 'hardship', 'dispute', 'paid', 'restructure', 'human', 'stop', 'decline', 'purpose',
              'change_promise', 'terms', 'scam', 'robot', 'unknown_info', 'other']   # contract §1.5 precedence
WHEN_RX = dict(refused=r'refus|attempts?\b.*\b(used|exhaust)|exhausted|no commitment|will not pay|declines? to pay',
               hardship=r'hardship|illness|job loss|bereave|financial difficult',
               dispute=r'disput|contest')
NOTE_REFUSED = 'refused'     # DEFAULT: the contract product status as the note reason when the brief names none
SELF_TOPICS = ('dispute', 'paid', 'hardship', 'restructure', 'change_promise', 'terms')   # imply the speaker is the customer
TOPIC_OVERRIDE = ('injection', 'hardship')   # the only topics that win from also=
TOPIC_INFO = ('scam', 'robot', 'unknown_info', 'terms')   # an answer line; a substantive also= is still handled
QUESTION_TOPICS = TOPIC_INFO + ('purpose',)   # questions answered first wherever they sit in the event
SUBSTANTIVE = ('date_amount', 'date', 'amount', 'accept', 'yes', 'reject', 'no', 'callback')


# ---------------------------------------------------------------- the step
def step(policy, st, event, tool_event, now, call_vars=None):
    st = copy.deepcopy(st)
    st['runs'] = st.get('runs', 0) + 1
    today = _d(now)
    cv = dict(call_vars or dict())
    partial_answer = False
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
        # ONE question rule (PUB-02 compound, PUB-04 kind=date;also=topic;t=robot, partial turns): a question topic anywhere in
        # the event (also=, t=, or kind=topic in a cut-off turn) is answered first, then the rest of the event is handled
        info = None
        if ev and ev.get('kind') != 'topic':
            info = next((x for x in (ev.get('also_t'), ev.get('t')) if x in QUESTION_TOPICS), None)
        elif ev and ev.get('st') == 'partial' and ev.get('t') in QUESTION_TOPICS:
            info = ev.get('t')
        if info and ev.get('st') == 'partial':
            partial_answer = True
            if ev.get('kind') in (None, '', 'other'):
                ev = dict(ev, kind='topic', t=info)   # a question is not cut-off offer chatter
        if info:       # PUB-04: a date (or any event) plus "are you a robot?": the event once, the answer line first
            ev = dict(ev, also='none', also_t='')
        act = on_user(policy, st, ev, today, cv) if ev else resay(st)
        if info:
            # 'what is this about?' before verification: the brief's own answer, else who is calling (951431e, PUB-02)
            line = caller_line(policy) if info == 'purpose' and st.get('verified') != 'yes' and not (
                event_row(policy, 'purpose') or dict()).get('say') else info_line(policy, st, info)
            if line:
                st['_info_next'] = ((st.get('_info_next') or '') + ' ' + line).strip()
    if st.get('_info_next') and act.get('type') in ('say_exact', 'close'):   # an answer line waits for a spoken line
        key = 'text' if act['type'] == 'say_exact' else 'farewell'
        act = dict(act, **dict([(key, (st.pop('_info_next') + ' ' + (act.get(key) or '')).strip())]))
    if act.get('type') == 'say_exact' and not str(act.get('text') or '').strip():
        act = dict(type='say_exact', text=sentence(policy, 'safe_repeat', D_SAFE))
    # never loop on one tts line: the same words more than RESAY_CAP + 1 times in a row break the loop by stage
    if act.get('type') == 'say_exact' and act['text'] != sentence(policy, 'continue_line', D_CONTINUE) and not partial_answer:
        st['_said_n'] = st.get('_said_n', 0) + 1 if act['text'] == st.get('_said_last') else 1
        st['_said_last'] = act['text']
        if st['_said_n'] > RESAY_CAP + 1:
            st['_said_n'], st['_said_last'] = 0, None
            act = dict(type='_loop')
    else:
        st['_said_n'], st['_said_last'] = 0, None
    if st.get('verified') == 'yes' and st.get('q') == 'offer' and act.get('type') in ('say_exact', 'speak_free'):
        act = no_restated_amount(st, act)
    if st.get('verified') == 'yes' and act.get('type') == 'say_exact':   # amounts already spoken (statement, offers)
        new = [a for a in re.findall(AMT, act['text']) if a not in (st.get('_spoken') or [])]
        if new:
            st['_spoken'] = (st.get('_spoken') or []) + new
    if act.get('type') == '_loop':
        st['_said_n'], st['_said_last'], st['_resay_n'] = 0, None, 0
        act = loop_break(policy, st, today, cv)
    if act.get('type') == 'close':
        act = np_question(policy, st, act)
    if policy.get('hooks'):
        act = attach_hooks(policy, st, act)
    else:
        st.pop('_hp', None)
    if act.get('type') == 'call_tool':   # canonical argument roles -> the brief's OAS body fields (bridge tool_args)
        ta = (policy.get('tool_args') or dict()).get(act['tool']) or dict()
        args = dict(act.get('args') or dict())
        for key, spec in (policy.get('composed_fields') or dict()).items():
            tool, _, fld = str(key).partition('.')
            roles = (spec or dict()).get('roles') or []
            if tool == act['tool'] and roles and all(r in args for r in roles):
                args[fld] = compose(spec, [args.pop(r) for r in roles])   # one field from several roles, never overwritten
        act = dict(act, args=dict((ta.get(k) or k, v) for k, v in args.items()))
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
    okv = te.get('ok')
    if okv is None and isinstance(te.get('data'), dict) and tr_path(policy, pend['node'][2:], 'ok'):
        okv = get_path(te['data'], tr_path(policy, pend['node'][2:], 'ok'))    # a nested ok flag
    ok = str(okv).lower() == 'true'
    success = (not te.get('no_delta')) and ds > 0 and df <= 0 and (sc is None or sc < 400) and ok
    op = pend['op']
    data = te.get('data') if isinstance(te.get('data'), dict) else dict()
    if not success:
        return tool_failed(policy, st, te, today, cv)
    st['pending'] = None
    if op == 'verify':
        return verify_result(policy, st, data, cv)
    if op == 'account':
        load_products(policy, st, _account_rows(te, policy), today)
        return account_statement(policy, st, today, cv)
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
        if pend.get('product_id'):
            st['products'][_index(st, pend['product_id'])]['status'] = 'routed'
            return next_write(policy, st, cv)
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
        if pend.get('product_id'):
            st['products'][_index(st, pend['product_id'])]['status'] = 'route_failed'
            return next_write(policy, st, cv)
        return resay(st)
    if pend['op'] == 'callback':
        o, r = V(policy)['callback_failed']
        return do_close(policy, st, o, r, D_FAREWELL)
    o, r = V(policy)['unclear']
    return do_close(policy, st, o, r, D_FAREWELL)


def verify_result(policy, st, data, cv):
    idt = st['identity']
    qs = (policy.get('identity') or dict()).get('questions') or []
    data = dict(data, hint=tr_get(policy, 'verify_identity', 'hint', data, 'hint'),
                verified=tr_get(policy, 'verify_identity', 'verified_this', data, 'verified'),
                all_verified=(None if isinstance((policy.get('tool_results') or dict()).get('verify_identity'), dict)
                              and not tr_path(policy, 'verify_identity', 'verified_all')
                              else tr_get(policy, 'verify_identity', 'verified_all', data, 'all_verified')),
                wrong_answers_left=tr_get(policy, 'verify_identity', 'wrong_left', data, 'wrong_answers_left'))
    if str(data.get('hint') or '') == 'day_month_swapped' and st['_id_hint'] < 1:
        st['_id_hint'] += 1
        return ask(st, D_HINT_MONTH, 'id_' + idt['order'][idt['idx']])
    vv = tr_path(policy, 'verify_identity', 'verified_value')
    if vv is not None:      # a string status (e.g. 'verified' | 'failed'); a boolean path (all_verified) still counts
        yes = lambda x: str(x).lower() == 'true' or str(x) == str(vv)
        data = dict(data, verified=yes(data.get('verified')), all_verified=yes(data.get('all_verified')))
    verified = str(data.get('verified')).lower() == 'true'
    if verified:
        # all verified: the bank's all-field when the policy binds one (bound paths without it: the field is ignored),
        # else this answer passed on the LAST question; the reducer moves on only after the previous one passed, so a
        # per-answer flag is never all-verified on question 1
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


def account_statement(policy, st, today, cv=None):
    active = _open_products(st)
    if not active:
        return next_write(policy, st, cv or dict(customer_id=st.get('_cid')))
    lines = [debt_intro(policy)] + [product_line(st['_pd'][i]) for i in active]
    if len(active) == 1:
        p, pd = _p(st, active[0])
        p['status'], p['offer'] = 'proposed', dict(amount=pd['past_due'], date=iso(today))
        st['cur'] = active[0]
        st['offer'] = dict(product_ids=[p['id']], amount=pd['past_due'], date=iso(today), kind='full')
        text = ' '.join(x for x in lines + [pay_today_question(policy)] if x)
    else:
        st['all_today_asked'] = True
        text = ' '.join(x for x in lines + [D_ALL_TODAY] if x)
    st['phase'] = 'negotiation'
    hook_point(st, 'after_debt')
    return ask(st, text, 'pay_today')


# ---------------------------------------------------------------- writes and wrap-up
def next_write(policy, st, cv):
    while st['_queue']:
        pid = st['_queue'].pop(0)
        i = _index(st, pid)
        p = st['products'][i]
        if p['status'] == 'confirmed':
            approved = next((x for x in (st.get('_confirmed_readback') or []) if x['product_id'] == pid), None)
            if not approved or approved.get('amount') != p['offer'].get('amount') or approved.get('date') != p['offer'].get('date'):
                for product in st['products']:
                    if product['status'] == 'confirmed':
                        product['status'] = 'agreed'
                st['_queue'] = []
                return start_readback(policy, st)
            st['_last_args'] = dict(customer_id=cid(cv), product_id=pid, amount=api_amount(policy, p['offer']['amount']),
                                    date=p['offer']['date'])
            return call(st, 'promise', 'create_promise', dict(st['_last_args']), product_id=pid)
    st['_confirmed_readback'] = None
    st['phase'] = 'wrapup'
    notes = (policy.get('writes') or dict()).get('notes') or dict()
    q = np_hook(policy)
    if q and not st.get('_np_asked') and not st['transfers'] and st.get('verified') == 'yes' \
            and not any(p['status'] == 'persisted' for p in st['products']) and \
            (precedence(policy, st)[0] or V(policy)['refused'][0]) == V(policy)['refused'][0]:
        st['_np_asked'], st['_np_resume'] = True, True        # the question before the notes (a date reopens)
        st['_hooks_said'] = (st.get('_hooks_said') or []) + [q.get('id')]
        return ask(st, str(q['text']).strip(), 'confirm_np')
    if notes.get('enabled') and not st['transfers']:
        for i, (p, pd) in enumerate(zip(st['products'], st['_pd'])):
            if p['status'] in ('refused', 'failed', 'open', 'proposed') and pd.get('note_reason') is None:
                pd['note_reason'] = V(policy)['note']['refused' if p['status'] != 'failed' else 'write_error']
            if p['status'] not in ('persisted', 'noted') and pd.get('note_reason') and not pd.get('_noted_try'):
                pd['_noted_try'] = True
                st['_last_args'] = dict(customer_id=cid(cv), product_id=p['id'], reason=pd['note_reason'])
                return call(st, 'note', 'add_note', dict(st['_last_args']), product_id=p['id'])
    for p, pd in zip(st['products'], st['_pd']):
        if p['status'] == 'route_pending':
            r = pd['route']
            p['status'] = 'routing'
            st['_xfer_queue'] = r['queue']
            st['_xfer_close'] = [r['close']['outcome'], r['close'].get('reason')]
            st['_last_args'] = dict(customer_id=cid(cv), queue=r['queue'])
            return call(st, 'transfer', 'transfer_to_agent', dict(st['_last_args']), product_id=p['id'])
    if any(p['status'] == 'persisted' for p in st['products']):
        st['_wrapup_said'] = True
        st['q'] = 'none'
        sms = sentence(policy, 'text_message') or sentence(policy, 'sms_confirmation')
        rec = sentence(policy, 'recorded') or sentence(policy, 'saved')
        if not rec:
            words = ((policy.get('honesty_words') or dict()).get('words') or []) + ['saved']
            rec = '' if any(w in sms.lower() for w in words) else D_RECORDED   # the SMS line may already say it
        text = (rec + ' ' + sms).strip()
        hook_point(st, 'on_promise_recorded')
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
    st['_confirmed_readback'] = None
    st.pop('_uncertain_q', None)
    st['_readback_valid'] = True
    st['readback'] = dict(items=items, asked=((st.get('readback') or dict()).get('asked') or 0) + 1)
    if len(st['products']) > 1:
        st['cur'] = _index(st, items[0]['product_id']) if st['cur'] is not None else None
    return ask(st, readback_line(policy, st, items, clamped), 'readback')


def after_resolved(policy, st, today, cv, ack=''):
    """A product was resolved (agreed, refused, noted, paid): move to the next open product, else read back or wrap up."""
    nxt = _open_products(st)
    if nxt and len(st['products']) > 1:
        out = start_attempt(policy, st, nxt[0], today, from_today_ask=False)
        if ack and out.get('type') == 'say_exact':
            out['text'] = ack + ' ' + out['text']
        return out
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
    """An attempt's day: deadline | today | next_business_day | last_business_day_this_week (next week's when today is
    that day or past) | last_business_day_next_week | <n>_business_days_after_today | <n>_calendar_days_after_today |
    {type: offset, count, unit}; clamped to the deadline, a closed day moved to the next business day inside it."""
    dl = _d(pd['deadline'])
    r = rule if isinstance(rule, dict) else str(rule or '')
    if isinstance(r, dict):
        r = '%s_%s_days_after_today' % (r.get('count'), 'business' if 'business' in str(r.get('unit')) else 'calendar') \
            if r.get('type') == 'offset' else str(r.get('type') or '')
    for w, n in NUM_WORDS:
        r = re.sub(r'^' + w + r'_', n + '_', r)
    m = re.match(r'^(\d+)_(business|calendar)_days?_after_today$', r)
    if r == 'deadline':
        return dl
    if r == 'today':
        d = today
    elif r == 'next_business_day':
        d = add_business_days(today, 1, policy)
    elif m and m.group(2) == 'business':
        d = add_business_days(today, int(m.group(1)), policy)
    elif m:
        d = today + datetime.timedelta(days=int(m.group(1)))
    elif r == 'last_business_day_next_week':
        d = _last_bd_of_week(today, policy, 1)
    else:
        d = _last_bd_of_week(today, policy, 0)       # last_business_day_this_week; if today is that day: next week's
        if d <= today:
            d = _last_bd_of_week(today, policy, 1)
    if d > dl:
        return dl
    if not is_business_day(d, policy):
        n_ = shift_to_business_day(d, policy, 1)
        d = n_ if n_ and n_ <= dl else dl
    return d


def plan_amount(rule, pd):
    below = pd['floor'] < pd['past_due'] - 0.005     # a floor equal to the full amount is not a floor offer
    if rule in ('floor', 'floor_again'):
        return pd['floor'], below
    if rule == 'full':
        return pd['past_due'], False
    return (pd['floor'], below) if pd['too_much'] else (pd['past_due'], False)


def start_attempt(policy, st, i, today, from_today_ask=True):
    p, pd = _p(st, i)
    st['cur'] = i
    if p['attempts'] >= len(pd['plan']):
        return refuse_product(policy, st, i, today)
    if p['attempts'] >= 1:
        hook_point(st, 'on_refusal')
    rule = pd['plan'][p['attempts']]
    date = plan_date(rule.get('date_rule'), today, pd, policy)
    amount, is_floor = plan_amount(rule.get('amount_rule'), pd)
    if [round(float(amount), 2), iso(date)] in pd.get('refused_offers', []):
        p['attempts'] += 1      # the same amount on the same day was just refused: this attempt is used, the next one
        return start_attempt(policy, st, i, today, from_today_ask)
    again = is_floor and p['floor_offered']        # the floor was already offered: only the new day (PUB-06 live)
    p['attempts'] += 1
    if is_floor:
        p['floor_offered'] = True
    p['status'], p['offer'] = 'proposed', dict(amount=amount, date=iso(date))
    st['offer'] = dict(product_ids=[p['id']], amount=amount, date=iso(date), kind='attempt_n')
    if again:
        pre = D_LOWEST + ' ' if st.pop('_lowest', False) else ''
        return ask(st, pre + 'Could you pay on ' + say_date(date) + ' instead?', 'offer')
    st.pop('_lowest', None)
    text = offer_line(pd, amount, iso(date), floor_clause=is_floor)
    return ask(st, text, 'offer')


def refuse_product(policy, st, i, today, cv=None):
    p, pd = _p(st, i)
    p['status'] = 'refused'
    hook_point(st, 'on_refusal')
    pd['note_reason'] = pd.get('note_reason') or V(policy)['note']['refused']
    st['offer'] = None
    notes_on = bool(((policy.get('writes') or dict()).get('notes') or dict()).get('enabled'))
    if len(st['products']) == 1 and not notes_on:
        o, r = V(policy)['refused']
        return do_close(policy, st, o, r, D_FAREWELL)
    return after_resolved(policy, st, today, cv or dict(customer_id=st.get('_cid')))   # notes on: the note, then the close


def agree(policy, st, i, amount, date, today, cv):
    p, pd = _p(st, i)
    p['status'], p['offer'] = 'agreed', dict(amount=amount, date=date)
    st['offer'] = None
    ack = 'Thank you: ' + money(amount) + ' for your ' + pd['name'] + ' on ' + say_date(_d(date)) + '.'
    return after_resolved(policy, st, today, cv, ack if len(st['products']) > 1 else '')


WDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def parse_items(raw, n):
    """items=<product number>:<amount or empty>:<day or empty>|... -> [(index, amount or None, spec or None)] or None.
    A day: YYYY-MM-DD or d/m (the year is never trusted: the calendar picks it), mon..sun, today or tomorrow."""
    out = []
    for part in str(raw or '').split('|'):
        m = re.fullmatch(r'\s*([1-9][0-9]?)\s*:\s*([0-9]+(?:\.[0-9]+)?)?\s*:\s*([0-9a-z/-]*)\s*', part.lower())
        if not m or int(m.group(1)) > n:
            return None
        x, spec = m.group(3), None
        dm = re.fullmatch(r'[0-9]{4}-([0-9]{1,2})-([0-9]{1,2})', x) or re.fullmatch(r'([0-9]{1,2})/([0-9]{1,2})', x)
        if dm:
            d_, m_ = (dm.group(2), dm.group(1)) if '-' in x else (dm.group(1), dm.group(2))
            spec = 'd=%s;m=%s' % (d_, m_)
        elif x in WDAYS:
            spec = 'wd=' + x
        elif x in ('today', 'tomorrow'):
            spec = 'rel=' + x
        elif x:
            return None
        out.append((int(m.group(1)) - 1, _num(m.group(2)), spec))
    return sorted(out) if out else None


def by_product(policy, st, today, cv):
    """No usable per-product terms: product by product with our own offers (never a silent full balance)."""
    for p in st['products']:
        if p['status'] == 'agreed' and st['q'] in ('readback', 'what_to_change'):
            p['status'] = 'open'
    nxt = _open_products(st)
    return start_attempt(policy, st, nxt[0], today, from_today_ask=False) if nxt else after_resolved(policy, st, today, cv)


def items_event(policy, st, ev, today, cv):
    """PER_ITEM (raw-2 PUB-12 700e9c78): different amounts and/or days per product in one turn. Each item goes through
    the single-product rules (date_verdict, amount_fits), in get_account order; refused=<numbers> refuses products
    in the same turn (an attempt each, as codex-audit). The first item a product cannot take is said and that product
    gets its valid option; else the next open product, then one read-back of every agreed product."""
    items = parse_items(ev.get('items'), len(st['products']))
    if not items:
        return by_product(policy, st, today, cv)
    rb, said, bad = st['q'] in ('readback', 'what_to_change'), [], None
    ids = [st['products'][i]['id'] for i, _, _ in items]
    st['_clamped'] = [c for c in st.get('_clamped') or [] if c not in ids]
    for i, amt, spec in items:
        p, pd = _p(st, i)
        if (p['status'] == 'refused' and not p.get('note')) or (rb and p['status'] == 'agreed'):
            p['status'] = 'open'      # the customer's own terms revive a product refused on our offers / replace the read-back
        if p['status'] not in ('open', 'proposed'):
            continue
        named, kind = date_from_spec(today, parse_spec(spec), policy) if spec else (None, None)
        if named is None or kind != 'exact':
            bad = bad or (i, '', None, amt)
            continue
        r = date_verdict(policy, today, pd, named)
        if r['reason'] == 'refuse':
            bad = bad or (i, fill_date(r['say'], r), None, None)
            continue
        d = iso(r['accepted'] or _d(pd['deadline']))
        if r['reason'] == 'after_deadline':
            st['_clamped'].append(p['id'])
        if r['reason'] in ('after_deadline', 'non_business_day'):
            said += [x for x in re.split(r'(?<=[.?!])\s+', fill_date(r['say'], r)) if x and not x.endswith('?') and x not in said]
        if amt is not None and not amount_fits(policy, pd, amt):
            bad = bad or (i, '', d, amt)
            continue
        prior = readback_item(st, p['id']) or dict()
        p['status'], p['offer'] = 'agreed', dict(amount=amt if amt is not None else prior.get(
            'amount', pd['floor'] if pd['too_much'] else pd['past_due']), date=d)
    flag = (policy.get('attempts') or dict()).get('flat_refusal_uses_attempt', True)
    raw = str(ev.get('refused') or '')
    if (flag.get('value') if isinstance(flag, dict) else flag) is not False and re.fullmatch(r'[1-9][0-9]?(,[1-9][0-9]?)*', raw):
        for i in sorted(set(int(x) - 1 for x in raw.split(','))):
            if i >= len(st['products']) or i in [x[0] for x in items]:
                continue
            p, pd = _p(st, i)
            if p['status'] not in ('open', 'proposed'):
                continue
            p['attempts'] = min(p['attempts'] + 1, len(pd['plan']))
            if p['attempts'] >= len(pd['plan']):
                p['status'] = 'refused'
                pd['note_reason'] = pd.get('note_reason') or V(policy)['note']['refused']
            else:
                p['status'] = 'open'
            hook_point(st, 'on_refusal')
    st['offer'] = None
    if bad:
        i, why, d, amt = bad
        p, pd = _p(st, i)
        if d and amt is not None:      # the day stands, the amount does not: the amount rule says why and offers
            st['cur'] = i
            st['offer'] = dict(product_ids=[p['id']], amount=None, date=d, kind='customer')
            out = amount_event(policy, st, dict(amt=amt), today, cv)
        else:
            out = start_attempt(policy, st, i, today, from_today_ask=False)
            said += [x for x in re.split(r'(?<=[.?!])\s+', why) if x and not x.endswith('?')]
    else:
        out = after_resolved(policy, st, today, cv)
    if said and out.get('type') == 'say_exact':
        out = dict(out, text=' '.join(said) + ' ' + out['text'])
    return out


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
    if ev.get('also') == 'reject':
        # 'No, I cannot pay that on the twenty-second' (raw-3 live): a date with a reject cue that is the day we
        # offered, or a day already refused, is a refusal of that day, never a proposal of it
        refused = set(x[1] for pd in st['_pd'] for x in pd.get('refused_offers') or [])
        refused |= set(it['date'] for it in ((st.get('readback') or dict()).get('items') or []) if st['q'] in ('readback', 'what_to_change'))
        if iso(named) == (st.get('offer') or dict()).get('date') or iso(named) in refused:
            if st['q'] in ('readback', 'what_to_change'):
                return no_event(policy, st, dict(kind='no'), today, cv)
            return reject_event(policy, st, dict(why='flat'), today, cv)
    targets = list(range(len(st['products']))) if (ev.get('prod') == 'all' or (multi and st['cur'] is None and not ev.get('prod'))) else None
    if targets is None:
        idx = st['cur'] if st['cur'] is not None else 0
        if ev.get('prod') and str(ev.get('prod')).isdigit():
            idx = _valid_prod(st, ev, idx)
        targets = [idx]
    if len(targets) > 1 and policy.get('per_item') and not amt and (ev.get('also') == 'amount' or ev.get('kind') == 'date_amount'):
        return by_product(policy, st, today, cv)     # amounts were said but not labelled: our own offers, product by product
    if len(targets) > 1:   # one date for all: per-product decision, clamp without separate acceptance
        st['_clamped'] = []
        said = ''
        for i in targets:
            p, pd = _p(st, i)
            if p['status'] == 'refused' and not p.get('note'):
                p['status'] = 'open'      # the customer's own date for every product revives one refused on our offers
            if p['status'] == 'agreed' and st['q'] in ('readback', 'what_to_change'):
                p['status'] = 'open'      # a new day for every product at the read-back replaces the agreed one
            if p['status'] not in ('open', 'proposed'):
                continue
            r = date_verdict(policy, today, pd, named)
            if r['reason'] == 'refuse':
                continue                  # this product cannot take that day: left open, its offers follow
            d = r['accepted'] or _d(pd['deadline'])
            if r['reason'] == 'after_deadline':
                st['_clamped'].append(p['id'])
            if r['reason'] == 'after_deadline' and not said:   # name the day they proposed, then the deadline
                said = fill_date(r['say'], r)
            elif r['reason'] == 'non_business_day' and not said:   # say why the day moved (raw-2 PUB-11), once
                said = ' '.join(x for x in re.split(r'(?<=[.?!])\s+', fill_date(r['say'], r)) if x and not x.endswith('?'))
            # one amount never goes to several products (raw-2 surface: 220 + 640 + 75 summed to 935): only a product
            # whose own amount it is takes it, every other product its own full amount
            own = _num(amt) if amt and _num(amt) is not None and abs(_num(amt) - pd['past_due']) < 0.005 else None
            prior = readback_item(st, p['id']) or dict()
            p['status'], p['offer'] = 'agreed', dict(amount=own if own is not None else prior.get(
                'amount', pd['floor'] if pd['too_much'] else pd['past_due']), date=iso(d))
        st['offer'] = None
        out = after_resolved(policy, st, today, cv)
        if said and out.get('type') == 'say_exact':
            out = dict(out, text=said + ' ' + out['text'])
        return out
    i = targets[0]
    p, pd = _p(st, i)
    r = date_verdict(policy, today, pd, named)
    reason = r['reason']
    if amt and _num(amt) is not None and not amount_fits(policy, pd, float(amt)):
        if reason == 'ok':     # the date stands; the amount goes through the acceptance rule
            st['cur'] = i
            st['offer'] = dict(product_ids=[p['id']], amount=None, date=iso(r['accepted']), kind='customer')
            return amount_event(policy, st, ev, today, cv)
        amt = None
    prior = readback_item(st, p['id']) or dict()
    amount = float(amt) if amt else ((st['offer'] or dict()).get('amount') or prior.get('amount') or
                                     (pd['floor'] if pd['too_much'] else pd['past_due']))
    if reason == 'ok':
        if multi and st['cur'] is not None and i != st['cur'] or (multi and st['cur'] is None):
            p['status'], p['offer'] = 'agreed', dict(amount=amount, date=iso(r['accepted']))
            return agree(policy, st, i, amount, iso(r['accepted']), today, cv)
        return agree(policy, st, i, amount, iso(r['accepted']), today, cv)
    if reason in ('non_business_day', 'after_deadline') and r['accepted']:
        d = iso(r['accepted'])
        p['status'], p['offer'] = 'proposed', dict(amount=amount, date=d)
        st['cur'] = i
        st['offer'] = dict(product_ids=[p['id']], amount=amount, date=d,
                           kind='customer' if reason == 'non_business_day' else 'deadline')
        tpl = fill_date(r['say'], r)
        text = (tpl + ' ' + 'That is ' + money(amount) + ' for your ' + pd['name'] + '.').strip()
        return ask(st, text, 'offer')
    # refuse: the brief's sentence (else a true contract default), then ask for another day; nothing is proposed
    if p['status'] == 'proposed' and st['cur'] == i:
        p['status'], p['offer'] = 'open', None
    st['offer'] = None
    st['cur'] = i
    text = fill_date(r['say'], r)
    return ask(st, text if text.endswith('?') else (text + ' ' + D_OTHER_DAY).strip(), 'exact_day')


D_OTHER_DAY = 'Which other date would work?'
D_DATE_SAY = dict(past='That date has passed.', today_not_allowed='I cannot record a payment for today.',
                  weekend='<NAMED> is not a business day, so I cannot record it.',
                  holiday='<NAMED> is not a business day, so I cannot record it.',
                  after_deadline='I cannot record a date after <DEADLINE>.',
                  shift='<NAMED> is not a business day. The next business day is <DATE>. Could you pay on <DATE>?',
                  offer_deadline='<NAMED> is after the latest date I can record, which is <DEADLINE>. Could you pay on <DEADLINE>?')

_OFFER_WITHOUT_NAMED = 'The latest date I can record is <DEADLINE>. Could you pay on <DEADLINE>?'


def customer_dated(say, reason):
    """A moved day is spoken with the day the customer proposed. A brief sentence that already names it (<NAMED>) is
    kept; the contract line, and any other sentence that omits it, still names that day."""
    say = (say or '').strip()
    if reason == 'after_deadline':
        if '<NAMED>' in say:
            return say
        line = D_DATE_SAY['offer_deadline']
        if not say or say == _OFFER_WITHOUT_NAMED:
            return line
        return line.split(' Could you pay')[0] + '. ' + say
    if reason == 'non_business_day' and '<NAMED>' not in say:
        return ('<NAMED> is not a business day. ' + say).strip() if say else D_DATE_SAY['shift']
    return say


def fill_date(tpl, r):
    for token, val in (('<NAMED>', r.get('named')), ('<DATE>', r.get('accepted')), ('<DEADLINE>', r.get('deadline'))):
        tpl = tpl.replace(token, say_date(val) if val else '')
    return tpl.strip()


def date_action(policy, sit):
    """policy.date_rules[situation] = dict(action=shift_next_business_day|shift_previous_business_day|offer_deadline|
    refuse, say=...); without it the older sections decide (on_non_business_day, on_after_deadline, earliest)."""
    rule = (policy.get('date_rules') or dict()).get(sit)
    if isinstance(rule, dict) and rule.get('action'):
        return str(rule['action']), str(rule.get('say') or '')
    if sit in ('weekend', 'holiday'):
        sec = policy.get('on_non_business_day') or dict()
        a = str(sec.get('action') or 'next_business_day')
        a = dict(next_business_day='shift_next_business_day', previous_business_day='shift_previous_business_day',
                 reject='refuse').get(a, a)
        say = str(sec.get('say') or '')
        return a, (say if a.startswith('shift') or '<DATE>' not in say else '')
    if sit == 'after_deadline':
        sec = policy.get('on_after_deadline') or dict()
        a = 'offer_deadline' if sec.get('action', 'offer_deadline') == 'offer_deadline' else 'refuse'
        say = str(sec.get('say') or '')
        return a, (say if a == 'offer_deadline' or '<DEADLINE>?' not in say else '')
    return 'refuse', ''


def date_verdict(policy, today, pd, named):
    """The named day for one product -> dict(reason ok|non_business_day|after_deadline|refuse, named, accepted,
    deadline, sit, say). Situations in order: past, today_not_allowed, after_deadline, holiday, weekend."""
    dl = _d(pd['deadline'])
    out = dict(reason='ok', named=named, accepted=named, deadline=dl, sit='', say='')
    allow_today = (policy.get('earliest') or dict()).get('allow_today', True) and \
        not ((policy.get('date_rules') or dict()).get('today_not_allowed') or dict()).get('action')
    bd = policy.get('business_days') or dict()

    def sit_of(d):
        if d < today:
            return 'past'
        if d == today and not allow_today:
            return 'today_not_allowed'
        if d > dl:
            return 'after_deadline'
        if d.isoformat() in (bd.get('holidays') or []):
            return 'holiday'
        if d.weekday() not in (bd.get('weekdays') or [0, 1, 2, 3, 4]):
            return 'weekend'
        return ''
    sit = sit_of(named)
    if not sit:
        return out
    act, say = date_action(policy, sit)
    out['sit'] = sit
    if act.startswith('shift') and sit in ('weekend', 'holiday'):
        alt = shift_to_business_day(named, policy, 1 if act == 'shift_next_business_day' else -1)
        alt_sit = sit_of(alt) if alt else 'after_deadline'
        if not alt_sit:
            return dict(out, reason='non_business_day', accepted=alt,
                        say=customer_dated(say or D_DATE_SAY['shift'], 'non_business_day'))
        sit = alt_sit
        act, say = date_action(policy, sit)
        out['sit'] = sit
    if act == 'offer_deadline' and sit in ('after_deadline', 'weekend', 'holiday') and not sit_of(dl):
        pre = '<NAMED> is not a business day. ' if sit in ('weekend', 'holiday') and not say else ''
        return dict(out, reason='after_deadline', accepted=dl,
                    say=customer_dated(say or pre + D_DATE_SAY['offer_deadline'], 'after_deadline'))
    return dict(out, reason='refuse', accepted=None, say=say or D_DATE_SAY.get(sit, D_DATE_SAY['past']))


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


def consume_bulk_refusals(policy, st, ev):
    """An explicit per-product flat refusal of the bulk ask consumes that product's next attempt."""
    flag = (policy.get('attempts') or dict()).get('flat_refusal_uses_attempt', True)
    flag = flag.get('value') if isinstance(flag, dict) else flag
    k = ev.get('kind')
    if flag is False or len(st['products']) < 2 or st['cur'] is not None or st['q'] != 'pay_today' \
            or st.get('verified') != 'yes' or ev.get('st') != 'complete' or ev.get('why') == 'too_much':
        return
    if k not in ('reject', 'no', 'date', 'date_amount', 'amount'):
        return
    raw = str(ev.get('refused') or '')
    if not re.fullmatch(r'[1-9][0-9]?(,[1-9][0-9]?)*', raw):
        return
    targets = set(int(x) - 1 for x in raw.split(','))
    if any(i >= len(st['products']) for i in targets):
        return
    if k in ('date', 'date_amount', 'amount'):
        # A payment proposal is never a refusal of the product it names.
        targets.discard(_valid_prod(st, ev, None))
    for i in sorted(targets):
        p, pd = _p(st, i)
        if p['status'] != 'open':
            continue
        p['attempts'] = min(p['attempts'] + 1, len(pd['plan']))
        if p['attempts'] >= len(pd['plan']):
            p['status'] = 'refused'
            pd['note_reason'] = pd.get('note_reason') or V(policy)['note']['refused']
        hook_point(st, 'on_refusal')


def reject_event(policy, st, ev, today, cv):
    if not st['products']:
        return resay(st)
    multi = len(st['products']) > 1
    if multi and st['cur'] is None:    # "no" to the all-today ask: attempt 1 for the first open product
        nxt = _open_products(st)
        return start_attempt(policy, st, nxt[0], today) if nxt else after_resolved(policy, st, today, cv)
    i = st['cur'] if st['cur'] is not None else 0
    p, pd = _p(st, i)
    o = st.get('offer') or dict()
    if o.get('amount') is not None and o.get('date') and p['id'] in (o.get('product_ids') or []):
        pd['refused_offers'] = pd['refused_offers'] + [[round(float(o['amount']), 2), o['date']]]   # never proposed again
    if st['q'] == 'pay_today' and ev.get('why') != 'too_much':   # a "not today" answers the today ask
        st['all_today_asked'] = True
    if ev.get('why') == 'too_much' and not p['floor_offered'] and pd['floor'] < pd['past_due'] - 0.005:
        pd['too_much'] = True
        p['floor_offered'] = True
        date = pd['deadline'] if too_much_on_deadline(policy) else ((st['offer'] or dict()).get('date') or iso(today))
        p['status'], p['offer'] = 'proposed', dict(amount=pd['floor'], date=date)
        st['offer'] = dict(product_ids=[p['id']], amount=pd['floor'], date=date, kind='floor')
        return ask(st, offer_line(pd, pd['floor'], date, floor_clause=True), 'offer')
    if ev.get('why') == 'too_much':
        pd['too_much'] = True
        if p['floor_offered']:      # 'too much' (or 'what is the minimum?') after the floor: it was the lowest
            st['_lowest'] = True
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
    prior = readback_item(st, p['id']) or dict()
    date = (st['offer'] or dict()).get('date') or prior.get('date') or iso(today)
    o = st.get('offer') or dict()
    if st['q'] in ('offer', 'pay_today') and o.get('amount') is not None and abs(amt - float(o['amount'])) < 0.005:
        return yes_event(policy, st, today, cv)     # 'Yes, I can pay the full 540': the open offer's own amount (biz-1 PUB-07)
    kind, x = accept_rule(policy)
    full = pd['past_due']
    low = x if kind == 'min_x' and x is not None else pd['floor']
    if kind in ('full_or_floor', 'full_only') and not amount_fits(policy, pd, amt) and amt < full - 0.005:
        low = full                       # between the floor and the full balance: not accepted, the floor once
    if amt < min(low, full) - 0.005:
        if p['floor_offered']:
            return start_attempt(policy, st, i, today)
        p['floor_offered'] = True
        ofr = max(low, pd['floor']) if kind == 'min_x' else pd['floor']
        ofr = min(ofr, full)
        p['status'], p['offer'] = 'proposed', dict(amount=ofr, date=date)
        st['offer'] = dict(product_ids=[p['id']], amount=ofr, date=date, kind='floor')
        return ask(st, 'I cannot record ' + money(amt) + '. ' + offer_line(pd, ofr, date, ofr < full - 0.005), 'offer')
    pre = ''
    if amt > full + 0.005 and kind != 'above_full_allowed':     # never clamped silently
        pre, amt = 'The amount due is ' + money(full) + '. ', full
    p['status'], p['offer'] = 'proposed', dict(amount=amt, date=date)
    st['offer'] = dict(product_ids=[p['id']], amount=amt, date=date, kind='customer')
    return ask(st, pre + offer_line(pd, amt, date), 'offer')


def restore_readback(policy, st):
    saved = st.pop('_rb_restore', None) or dict()
    rb = saved.get('readback') or dict()
    if not rb.get('items'):
        return ask(st, D_WHAT_CHANGE, 'what_to_change')
    st['products'] = copy.deepcopy(saved['products'])
    for pd, reason in zip(st['_pd'], saved.get('note_reasons') or []):
        pd['note_reason'] = reason
    st['readback'], st['offer'], st['_queue'] = None, None, []
    return start_readback(policy, st)


def accept_readback_change(policy, st, ev):
    """An accept after a rejected/changed read-back selects terms; it never confirms them."""
    items = copy.deepcopy((st.get('readback') or dict()).get('items') or [])
    if not items:
        return ask(st, D_WHAT_CHANGE, 'what_to_change')
    prod = str(ev.get('prod') or '')
    if prod == 'all':
        chosen = set(x['product_id'] for x in items)
    elif prod.isdigit() and 0 < int(prod) <= len(st['products']):
        chosen = set([st['products'][int(prod) - 1]['id']])
    elif len(items) == 1:
        chosen = set([items[0]['product_id']])
    else:
        return ask(st, D_WHAT_CHANGE, 'what_to_change')
    for it in items:
        i = _index(st, it['product_id'])
        p, pd = _p(st, i)
        if p['id'] in chosen:
            p['status'], p['offer'], pd['note_reason'] = 'agreed', dict(amount=it['amount'], date=it['date']), None
        else:
            p['status'], pd['note_reason'] = 'refused', V(policy)['note']['refused']
    st['offer'] = None
    return start_readback(policy, st)


def plan_guard(policy, st, ev):
    """One trust boundary for plan uncertainty, read-back invalidation, restoration and re-confirmation."""
    q, k, status = st.get('q'), ev.get('kind'), ev.get('st')
    if status == 'complete' and ev.get('why') == 'restore' and q in ('readback', 'what_to_change'):
        st.pop('_uncertain_q', None)
        return restore_readback(policy, st)
    if status == 'partial':
        # a cut-off turn never acts and is never talked over: the continue line (on_user), the pieces kept; a bare yes
        # right after it re-asks the open question instead of agreeing / writing
        if q in ('offer', 'pay_today', 'readback'):
            st['_uncertain_q'] = q
        if q == 'readback' and k in ('yes', 'no', 'accept', 'reject'):
            return ask(st, D_RB_CLARIFY, q)    # a half yes / no to the read-back is a hedge on the decision (bb748cf5)
        return None
    if status == 'ambiguous':
        if q in ('offer', 'pay_today'):
            st['_uncertain_q'] = q
            return offer_chatter(st) if offer_is_open(st) else ask(st, D_OFFER_NUDGE, q)
        if q == 'readback':
            st['_uncertain_q'] = q
            return ask(st, D_RB_CLARIFY, q)
        return resay(st)
    if q in ('readback', 'what_to_change') and k in ('yes', 'accept'):
        has_date = any(str(ev.get(x) or '').strip() for x in ('rel', 'd', 'm', 'wd', 'items')) or \
            ev.get('wk') in ('this', 'next', 'after_next') or ev.get('vague') == 'yes'
        has_amount = str(ev.get('amt') or '').strip()
        if ev.get('also') in ('no', 'reject'):
            ev['kind'], k = 'no', 'no'
        elif has_date or has_amount:
            ev['kind'] = k = 'date_amount' if has_date and has_amount else 'date' if has_date else 'amount'
        elif k == 'yes' and str(ev.get('prod') or '').isdigit():
            ev['kind'], k = 'accept', 'accept'
    uncertain = st.pop('_uncertain_q', None)
    if uncertain == 'readback' and k == 'yes':
        rb = st.get('readback') or dict()
        if not st.get('_readback_valid', True):
            return ask(st, D_WHAT_CHANGE, 'what_to_change')
        return ask(st, readback_line(policy, st, rb.get('items') or [], st.get('_clamped') or []), 'readback')
    if q in ('readback', 'what_to_change') and k in ('date', 'date_amount', 'amount', 'accept'):
        void_readback(st, rejected=ev.get('also') in ('reject', 'no'))
        if k == 'accept':
            return accept_readback_change(policy, st, ev)
    return None


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
    if q == 'readback' and st['readback'] and st.get('_readback_valid', True):
        items = st['readback']['items']
        agreed = [p for p in st['products'] if p['status'] == 'agreed']
        exact = bool(items) and len(items) == len(agreed) and all(any(
            it['product_id'] == p['id'] and abs(float(it['amount']) - float(p['offer']['amount'])) < 0.005 and
            it['date'] == p['offer']['date'] for it in items) for p in agreed)
        if not exact:
            return start_readback(policy, st) or ask(st, D_WHAT_CHANGE, 'what_to_change')
        st['_queue'] = []
        st['_confirmed_readback'] = copy.deepcopy(items)
        for it in items:
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
        void_readback(st, rejected=True)
        if st['_what_change'] < 1:
            st['_what_change'] += 1
            return ask(st, D_WHAT_CHANGE, 'what_to_change')
    if q in ('readback', 'what_to_change'):
        void_readback(st, rejected=True)
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


QUEUE_STEMS = dict(restructuring=('restructur',), human=('human', 'person', 'agent'), hardship=('hardship', 'support', 'care'))


def queue_for(policy, key):
    """The queue for a contract topic: queue_map keyed by the topic (restructure / human / hardship), else a key that
    names it; for a person, else the pre-verification queue."""
    tr = policy.get('transfer') or dict()
    qmap = tr.get('queue_map') or dict()
    for k in (key, 'restructure' if key == 'restructuring' else key, 'support' if key == 'hardship' else key):
        if qmap.get(k):
            return qmap[k]
    for k, v in qmap.items():
        if any(stem in str(k).lower() for stem in QUEUE_STEMS.get(key, ())):
            return v
    pre = tr.get('pre_verification_queues') or []
    if key == 'human' and pre:
        return pre[0]
    return None


def tool_absent(policy, tool):
    return str(((policy.get('tool_status') or dict()).get(tool) or dict()).get('status') or '') == 'absent'


def transfer(policy, st, key, cv):
    if tool_absent(policy, 'transfer_to_agent'):     # the API has no transfer: the situation closes with its own codes
        o, r = (V(policy)['xfer'].get(key) or V(policy)['refused'])
        if st['verified'] != 'yes':
            o, r = V(policy)['declined'] if st['who'] == 'self' else V(policy)['unclear']
        return do_close(policy, st, o, r, D_FAREWELL)
    queue = queue_for(policy, key)
    pre = (policy.get('transfer') or dict()).get('pre_verification_queues') or []
    if not queue:                      # the brief gives no queue for this transfer: say so once, keep the call going
        V(policy)['log'].append('no transfer queue for ' + key)
        return resay(st)
    if st['verified'] != 'yes' and queue not in pre:
        # no transfer before verification for this queue: never loop on the help-first question, close politely
        o, r = V(policy)['declined'] if st['who'] == 'self' else V(policy)['unclear']
        return do_close(policy, st, o, r, D_FAREWELL)
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


AMT = r'\d[\d,]*\.\d\d'


def no_restated_amount(st, act):
    """Invariant 14: an amount once offered is never restated in a later offer line (re-asks, next attempts, date
    shifts): 'Could you pay X for your ...' -> 'Could you make that payment for your ...', 'That is X for your ...' goes."""
    said, spoken = list(st.get('_offered') or []), st.get('_spoken') or []
    key = 'text' if act['type'] == 'say_exact' else 'hint'
    t = act.get(key) or ''
    repeated = False
    for a in re.findall(AMT, t):
        if a in said:
            repeated = True
            t = re.sub(r'pay ' + re.escape(a) + r' for', 'make that payment for', t)
        if a in said or (a in spoken and (st.get('offer') or dict()).get('kind') == 'customer'):   # PUB-07 / PUB-04
            t = re.sub(r'\s*That is ' + re.escape(a) + r' for your [^.?]*\.', '', t)
    if repeated:
        t = t.replace(D_OVERDUE, '')   # the floor clause belongs to the one full statement of that offer
    new = [a for a in re.findall(r'(?:pay|That is) (' + AMT + r') for', t) if a not in said]
    if new:
        st['_offered'] = said + new
    return dict(act, **dict([(key, t.strip())]))


HOOK_POINTS = ('opening', 'after_debt', 'on_refusal', 'on_no_promise', 'before_close', 'on_promise_recorded')
HOOK_HONESTY = r'\b(recorded|scheduled|transferr?ed|saved|booked)\b'


def hook_point(st, point):
    st['_hp'] = (st.get('_hp') or []) + [point]


def hook_ok(h, st, act, pd_cur):
    """condition: a closed set of key=value terms joined by ';', ',' or '&': band=, product_type=, outcome=."""
    for term in re.split(r'[;,&]', str(h.get('condition') or '')):
        if not term.strip():
            continue
        k, _, v = term.strip().partition('=')
        k, v = k.strip(), v.strip()
        pds = [pd_cur] if pd_cur else st.get('_pd') or []
        if k == 'band':
            ok = any(str(pd.get('band')) == v for pd in pds)
        elif k == 'product_type':
            ok = any(str(pd.get('type')) == v for pd in pds)
        elif k == 'outcome':
            ok = act.get('type') == 'close' and str(act.get('outcome')) == v
        else:
            st['_hook_skip'] = (st.get('_hook_skip') or []) + [str(h.get('id')) + ':condition']
            return False
        if not ok:
            return False
    return True


def attach_hooks(policy, st, act):
    """Brief sentences at fixed points (policy.hooks), each once per call, added to the line said anyway: before the
    closing question of a say_exact, or before the farewell of a close. A point reached on a tool call waits for the
    next spoken line. expects_answer hooks are not supported (logged); a hook that claims a write is only allowed after
    a recorded promise (honesty lint)."""
    pts = list(st.get('_hp') or [])
    if act.get('type') == 'close':
        v = V(policy)
        if act.get('outcome') in set(x[0] for x in (v['refused'], v['hardship'], v['dispute'], v['write_failed']) if x[0]):
            pts.append('on_no_promise')
        pts.append('before_close')
    if not pts:
        return act
    if act.get('type') not in ('say_exact', 'close'):
        st['_hp'] = pts
        return act
    st['_hp'] = []
    said = st.get('_hooks_said') or []
    pd_cur = st['_pd'][st['cur']] if st.get('cur') is not None and st.get('_pd') else None
    lines = []
    for point in pts:
        for h in policy.get('hooks') or []:
            if not isinstance(h, dict) or h.get('point') != point or h.get('id') in said or h.get('expects_answer'):
                continue
            text = str(h.get('text') or '').strip()
            if not text or not hook_ok(h, st, act, pd_cur):
                continue
            if point != 'on_promise_recorded' and re.search(HOOK_HONESTY, text, re.I) and not re.search(r'\bcall\b', text, re.I):
                st['_hook_skip'] = (st.get('_hook_skip') or []) + [str(h.get('id')) + ':honesty']
                said = said + [h.get('id')]
                continue
            said = said + [h.get('id')]
            lines.append(text)
    st['_hooks_said'] = said
    if not lines:
        return act
    add = ' '.join(lines)
    if act['type'] == 'close':
        return dict(act, farewell=(add + ' ' + (act.get('farewell') or '')).strip())
    parts = re.split(r'(?<=[.?!])\s+', act['text'].strip())
    qi = [i for i, x in enumerate(parts) if x.endswith('?')]
    if qi:                       # before the last question: the customer answers the question, not the hook
        return dict(act, text=' '.join(parts[:qi[-1]] + [add] + parts[qi[-1]:]))
    return dict(act, text=act['text'].strip() + ' ' + add)


def info_line(policy, st, t):
    """The answer line of an answer topic (robot, scam, unknown_info: the brief's say; terms: the no-other-terms line
    at most once, never 'I am sorry' unless the brief says it)."""
    if t == 'terms':
        st['_terms_n'] = st.get('_terms_n', 0) + 1
        return brief_sentence(policy, 'no_other_terms', D_NO_TERMS) if st['_terms_n'] == 1 else ''
    return (event_row(policy, t) or dict()).get('say') or (D_PROTECT if t == 'purpose' else '')


def compose(spec, vals):
    """composed_fields: format date-time (date YYYY-MM-DD + time HH:MM -> YYYY-MM-DDTHH:MM:00); otherwise joined by a
    space."""
    if str((spec or dict()).get('format')) == 'date-time' and len(vals) == 2:
        t = str(vals[1])
        return str(vals[0]) + 'T' + (t if t.count(':') == 2 else t + ':00')
    return ' '.join(str(v) for v in vals)


def np_question(policy, st, act):
    """hooks[point=on_no_promise, expects_answer]: before a refused-family close after verification (not a write failure),
    ask the brief's question once; the close waits for the answer (nightmare-1 rule 14)."""
    v = V(policy)
    if st.get('verified') != 'yes' or st.get('_np_asked') or act.get('outcome') != v['refused'][0] or \
            (act.get('outcome'), act.get('reason')) == tuple(v['write_failed']):
        return act
    h = np_hook(policy)
    if not h:
        return act
    st['_np_asked'], st['_np_close'] = True, [act.get('outcome'), act.get('reason')]
    st['phase'], st['outcome'], st['reason'] = 'wrapup', None, None
    st['_hooks_said'] = (st.get('_hooks_said') or []) + [h.get('id')]
    return ask(st, str(h['text']).strip(), 'confirm_np')


def np_hook(policy):
    return next((h for h in policy.get('hooks') or [] if isinstance(h, dict) and h.get('point') == 'on_no_promise'
                 and h.get('expects_answer') and str(h.get('text') or '').strip()), None)


def np_answer(policy, st, ev, today, cv):
    """The answer to the no-promise question: a date or an amount reopens the product and is handled as a proposal;
    anything else closes as decided."""
    k = ev.get('kind')
    if k in ('date', 'date_amount', 'amount') or (k == 'no' and ev.get('also') in ('date', 'date_amount', 'amount')):
        if k == 'no':
            ev = dict(ev, kind=ev.get('also'), also='none')
        for i, p in enumerate(st['products']):
            if p['status'] in ('refused', 'noted'):
                p['status'], p['offer'] = 'open', None
                st['cur'] = i if st['cur'] is None or st['products'][st['cur']]['status'] != 'open' else st['cur']
        st['phase'], st['q'] = 'negotiation', 'offer'
        return date_event(policy, st, ev, today, cv) if ev['kind'] != 'amount' else amount_event(policy, st, ev, today, cv)
    if st.pop('_np_resume', False):
        return next_write(policy, st, cv)          # asked before the notes: the notes, then the close
    o, r = st.get('_np_close') or V(policy)['refused']
    return do_close(policy, st, o, r, D_FAREWELL)


def extra_topic(policy, t):
    """policy.extra_topics [{id, trigger, effect: close, outcome, reason}]: a situation the brief names outside the
    contract topics (e.g. a complaint)."""
    return next((x for x in policy.get('extra_topics') or [] if isinstance(x, dict) and x.get('id') == t), None)


def loop_break(policy, st, today, cv):
    """The on-cap action of every open question (contract default; never free talk, never a tts loop).
    Before verification: a permitted transfer for a help-first loop, else a safe close on the stage's slot.
    After verification: the next policy step (next attempt / refusal of the product, read-back -> close)."""
    v, q = V(policy), st.get('q') or 'none'
    if st['verified'] != 'yes':
        pre = (policy.get('transfer') or dict()).get('pre_verification_queues') or []
        if q == 'help_first' and queue_for(policy, 'human') in pre and queue_for(policy, 'human'):
            return transfer(policy, st, 'human', cv)
        if st['who'] == 'other' or q == 'callback_time':
            o, r = v['callback_failed']
        elif st['who'] == 'self' and q.startswith('id_') and st['identity'].get('refusals', 0) >= 1:
            o, r = v['declined']        # an explicit refusal
        elif st['who'] == 'self' and q.startswith('id_'):
            o, r = id_unfinished(policy)  # no answer: the brief's 'not verified before the end' close
        else:
            o, r = v['unclear']
        return do_close(policy, st, o, r, D_FAREWELL)
    if q == 'support_offer':
        return no_event(policy, st, dict(), today, cv)     # an unanswered support offer is a decline (its policy path)
    if q in ('offer', 'pay_today', 'exact_day') and st['products']:
        i = st['cur'] if st['cur'] is not None else (_open_products(st) or [None])[0]
        if i is not None and st['products'][i]['status'] in ('open', 'proposed'):
            return start_attempt(policy, st, i, today)   # a non-answer counts as a no: next attempt, refusal at the cap
    o, r = precedence(policy, st)
    if not o:
        o, r = v['refused']
    return do_close(policy, st, o, r, D_FAREWELL)


def _talk_node(st):
    return 'talk_post' if st['verified'] == 'yes' else 'talk_pre'


def topic_event(policy, st, ev, today, cv):
    t = ev.get('t')
    multi = len(st['products']) > 1
    if t == 'injection':
        return resay(st)
    if t == 'human':
        cap = int((event_row(policy, 'human') or dict()).get('max_times') or 1)
        if st['q'] == 'help_first' or st['counters']['human_asks'] >= cap:
            return transfer(policy, st, 'human', cv)
        st['counters']['human_asks'] += 1
        row = event_row(policy, 'human')
        st['_q_prev'], st['_ask_prev'] = st['q'], st.get('_last_ask') or ''
        return ask(st, (row or dict()).get('say') or D_HELP_FIRST, 'help_first')
    if st['q'] == 'support_offer' and t in TOPIC_INFO + ('decline', 'purpose', 'hardship'):
        if t in TOPIC_INFO and (event_row(policy, t) or dict()).get('continuation_only') and ev.get('also') not in ('reject', 'no'):
            return resay(st, info_line(policy, st, t))
        line = ''        # PUB-05: "no, can I get a discount?" declines the support offer; it is never offered again
        if t == 'terms' and st.get('_terms_n', 0) < 1:
            st['_terms_n'] = 1
            line = brief_sentence(policy, 'no_other_terms', D_NO_TERMS)
        elif t in TOPIC_INFO and t != 'terms':
            line = (event_row(policy, t) or dict()).get('say') or ''
        act = no_event(policy, st, ev, today, cv)
        if line and act.get('type') == 'close':
            act = dict(act, farewell=line + ' ' + act['farewell'])
        return act
    if t in TOPIC_INFO:
        line = info_line(policy, st, t)
        if st['phase'] == 'opening':
            return reask_name(policy, st, cv, line)
        if st.get('verified') == 'yes' and ev.get('also') in SUBSTANTIVE:
            act = on_user(policy, st, dict(ev, kind=ev['also'], also='none'), today, cv)
            if line and act.get('type') == 'say_exact':
                act = dict(act, text=line + ' ' + act['text'])
            return act
        return resay(st, line)
    if t == 'change_promise':
        row = event_row(policy, 'change_promise')
        return dict(type='say_exact', text=(row or dict()).get('say') or D_CHANGE)
    if t in ('decline', 'purpose') and st['phase'] == 'opening':
        return reask_name(policy, st, cv)        # rule 3: a question first, the ask that follows is counted
    if t in ('decline', 'purpose') and st['q'] == 'offer' and (st.get('offer') or dict()).get('kind') in OUR_OFFERS:
        return resay(st, (event_row(policy, t) or dict()).get('say') or '')   # answer briefly, then only the day
    if t in ('decline', 'purpose'):
        if st['phase'] == 'identity':
            st['identity']['refusals'] += 1
            if st['identity']['refusals'] >= 2:
                o, r = slot(policy, 'declined')
                return do_close(policy, st, o, r, D_FAREWELL)
            st['counters']['decline_explain'] += 1
            row = event_row(policy, t)
            return resay(st, (row or dict()).get('say') or D_PROTECT)
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
    if t == 'hardship' and st['counters']['support_offered'] >= 1:   # offered once: a second hardship is the decline path
        st['q'] = 'support_offer'
        return no_event(policy, st, ev, today, cv)
    if t == 'hardship':
        row = next((e for e in policy.get('events') or [] if e.get('topic') == 'hardship' and not _none(e.get('note_reason'))), None)
        st['counters']['support_offered'] += 1
        st['offer'] = None
        p = st['products'][i]
        if p['status'] == 'proposed':
            p['status'], p['offer'] = 'open', None
        row = row or next((e for e in policy.get('events') or [] if e.get('topic') == 'hardship'), None)
        return ask(st, (row or dict()).get('say') or D_SUPPORT.replace('<DESK>', desk_name(row)), 'support_offer')
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
        notes_on = bool(((policy.get('writes') or dict()).get('notes') or dict()).get('enabled'))
        if not multi and not notes_on:
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
    guarded = plan_guard(policy, st, ev)
    if guarded:
        return guarded
    if ev.get('st') == 'partial':
        if offer_is_open(st) and ev.get('kind') in (None, '', 'other'):
            return offer_chatter(st)     # a cut-off chat is not a second statement of the offer
        if st['phase'] == 'identity' and ev.get('kind') == 'identity' and str(st.get('q') or '').startswith('id_'):
            idt, qs = st['identity'], (policy.get('identity') or dict()).get('questions') or []
            fmt = str(qs[idt['idx']].get('format') or '') if idt['idx'] < len(qs) else ''
            if answer_format(fmt)[0] in ('date', 'digits'):
                assemble_answer(st, idt['order'][idt['idx']], fmt, dict(ev, st='complete'))
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
    if st['q'] == 'confirm_np':
        return np_answer(policy, st, ev, today, cv)
    x = extra_topic(policy, ev.get('t') or ev.get('also_t')) if k == 'topic' or ev.get('also_t') else None
    if x and str(x.get('effect') or 'close') == 'close' and _none(x.get('outcome')):
        return do_close(policy, st, _none(x.get('outcome')), _none(x.get('reason')), D_FAREWELL)   # no facts, no promise
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
    if ev.get('prod') and str(ev['prod']).isdigit():
        i = _valid_prod(st, ev, None)
        if i is not None and st['_pd'][i].get('route'):
            return after_resolved(policy, st, today, cv)
    if policy.get('per_item') and len(st['products']) > 1 and ev.get('items') and k != 'topic':
        return items_event(policy, st, ev, today, cv)     # its own refused= handling: never counted twice
    consume_bulk_refusals(policy, st, ev)
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
    if k == 'other' and offer_is_open(st):
        return offer_chatter(st)         # do not hand the open offer to free talk
    if st['q'] == 'offer' and (st.get('offer') or dict()).get('kind') in OUR_OFFERS:
        st['q'], st['_last_ask'] = 'exact_day', D_WHICH_DAY    # the free reply never re-proposes the heard offer
    return dict(type='speak_free', node=_talk_node(st), hint=reask_line(st) if st.get('_last_ask') else '')


def gate_spec(policy):
    g = (policy.get('identity') or dict()).get('gate')
    return g if isinstance(g, dict) and str(g.get('ask') or '').strip() else None


_GATE_DENY = re.compile(r"\b(not authoris\w*|not authoriz\w*|can(?:not|'t) discuss|cannot discuss|not allowed)\b", re.I)


def gate_is_no(ev):
    """A denial of authority while the gate is open: no, reject, t=decline, who=other, or a negated statement."""
    if ev.get('kind') in ('no', 'reject') or ev.get('also') in ('no', 'reject'):
        return True
    if ev.get('t') == 'decline' or ev.get('also_t') == 'decline':
        return True
    if ev.get('who') == 'other':
        return True
    blob = ' '.join(str(ev.get(x) or '') for x in ('ans', 'why', 'party'))
    return bool(_GATE_DENY.search(blob))


def gate_no(policy, st, today, cv):
    on_no = gate_spec(policy).get('on_no') or 'callback'
    if isinstance(on_no, dict) and isinstance(on_no.get('close'), dict) and _none(on_no['close'].get('outcome')):
        return do_close(policy, st, _none(on_no['close'].get('outcome')), _none(on_no['close'].get('reason')), D_FAREWELL)
    st['who'], st['phase'] = 'other', 'third_party'
    return ask(st, fill_names(str(gate_spec(policy).get('callback_ask') or D_REACH_AUTH), cv), 'callback_time')


def gate_answer(policy, st, ev, today, cv):
    """identity.gate (biz-1 rules 3-4: 'Are you authorised to discuss this account?'): a yes opens the security
    questions; a denial of authority takes on_no ('callback': ask when an authorised person can be reached, nothing
    disclosed; {close: {outcome, reason}}: close); anything else asks again (counted, loop cap)."""
    k = ev.get('kind')
    if gate_is_no(ev):
        return gate_no(policy, st, today, cv)
    if k in ('yes', 'accept') or (k == 'who' and ev.get('who') == 'self'):
        st['_gate_ok'], st['q'] = True, 'none'
        return opening(policy, st, dict(kind='who', who='self', party=''), today, cv)
    if k == 'callback':
        st['who'], st['phase'] = 'other', 'third_party'
        return third_party(policy, st, ev, today, cv)
    return resay(st)


D_REACH_AUTH = 'Could you tell me when an authorised person can be reached?'


def opening(policy, st, ev, today, cv):
    k, who = ev.get('kind'), ev.get('who')
    if st.get('q') == 'gate':
        return gate_answer(policy, st, ev, today, cv)
    if k == 'callback' and who in (None, '', 'self'):
        return self_callback(policy, st, ev, today, cv)
    if k == 'yes':
        who = 'self'
    if k == 'no':
        who = 'other'
    if k == 'topic' and ev.get('t') in SELF_TOPICS:
        who = 'self'     # only the account holder raises the account (nightmare-1 PUB-09 live: the 'yes, it's me' was lost)
    elif k == 'topic':
        return topic_event(policy, st, ev, today, cv)
    if k != 'who' and who is None:
        return reask_name(policy, st, cv)    # an identity answer or anything else never confirms the name (rule 3)
    party = ev.get('party') or ''
    if who == 'self' and gate_spec(policy) and not st.get('_gate_ok'):
        st['who'] = 'self'
        return ask(st, fill_names(str(gate_spec(policy)['ask']).strip(), cv), 'gate')   # before any security question
    if who == 'self':
        st['who'], st['phase'] = 'self', 'identity'
        idp = policy.get('identity') or dict()
        qs = idp.get('questions') or []
        blk = idp.get('blocked') if isinstance(idp.get('blocked'), dict) else dict()
        if blk.get('fields') or any(q.get('blocked') for q in qs):
            # §14.3: a required identity field the API cannot verify; identity cannot pass, so close on the fail slot
            # before any blocked question and before any account fact
            c = blk.get('close') or idp.get('on_fail') or dict()
            o, r = (_none(c.get('outcome')), _none(c.get('reason'))) if c.get('outcome') else V(policy)['id_failed']
            return do_close(policy, st, o, r, (id_fail_line(policy) + ' ' + D_FAREWELL).strip())
        if not qs:
            o, r = slot(policy, 'declined')
            return do_close(policy, st, o, r, D_FAREWELL)
        return ask(st, qs[0].get('ask') or D_SAFE, 'id_' + qs[0].get('field'))
    if who in ('other', 'misdialled', 'deceased') or party in ('relative', MISDIAL, 'deceased'):
        if party == MISDIAL or who == 'misdialled':
            row = party_row(policy, MISDIAL) or who_row(policy, 'misdialled')
            o, r = (_none(row.get('outcome')), _none(row.get('reason'))) if row else V(policy)['unclear']
            return do_close(policy, st, o or V(policy)['unclear'][0], r, D_FAREWELL)
        if party == 'deceased' or who == 'deceased':
            row = party_row(policy, 'deceased') or who_row(policy, 'deceased')
            say = (row or dict()).get('say') or sentence(policy, 'condolence')
            o, r = (_none(row.get('outcome')), _none(row.get('reason'))) if row else V(policy)['unclear']
            return do_close(policy, st, o or V(policy)['unclear'][0], r, (say + ' Goodbye.').strip())
        st['who'], st['phase'] = 'other', 'third_party'
        return ask(st, fill_names(V(policy)['callback_say'] or D_REACH, cv), 'callback_time')
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
    elif out['text'] == q:                   # worded differently from the greet's question
        out['text'] = (D_JUST_CHECK + ' ' + q).strip()
    return out


D_JUST_CHECK = 'Just to be sure:'


def _callback_ok(policy, st, d, tm, today, now_time):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', tm):
        return False
    cb = (policy.get('writes') or dict()).get('callback') or dict()
    nb = add_business_days(today, 1, policy)
    days = {'today_or_next_business_day': [today, nb], 'next_business_day_only': [nb],
            'today_only': [today]}.get(cb.get('days', 'today_or_next_business_day'), [])
    if d not in days or not is_business_day(d, policy) and d != today:
        return False
    start, end = cb.get('start', '00:00'), cb.get('end', '23:59')
    if not ((start <= tm <= end) if cb.get('inclusive', True) else (start < tm < end)):
        return False
    if cb.get('after_now', True) and d == today and tm <= now_time:
        return False
    return True


def self_callback(policy, st, ev, today, cv):
    """The customer asks to be called back before the security questions are done (nightmare-1 rule 15): no
    verification, no account facts; the same window rules as a third party's callback."""
    st['who'], st['phase'] = 'self', 'third_party'
    return third_party(policy, st, ev, today, cv)


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
    if k in ('no', 'reject') and st.get('q') == 'callback_time':   # no (other) time: do not schedule
        o, r = V(policy)['callback_failed']
        return do_close(policy, st, o, r, D_FAREWELL)
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


def answer_format(fmt):
    """identity.questions[].format -> (kind, n). Closed set: date, digits(n), name, alnum, postcode, free; older
    free-text formats ('YYYY-MM-DD', '4 digits', 'YYYY') are read too. Unknown -> free."""
    f = str(fmt or '').strip().lower()
    for w, d in NUM_WORDS:
        f = re.sub(r'\b' + w + r'\b', d, f)
    m = re.match(r'^digits\s*\(\s*(\d+)\s*\)$', f) or re.match(r'^(\d+) digits\b', f)
    if m:
        return 'digits', int(m.group(1))
    if f in ('date', 'name', 'alnum', 'postcode', 'free', 'digits'):
        return f, 0
    if f.startswith('yyyy-mm-dd'):
        return 'date', 0
    if f == 'yyyy':
        return 'digits', 4
    if re.search(r'\b(inward|outward) code\b', f):
        return 'postcode', 0
    return 'free', 0


NUM_WORDS = (('one', '1'), ('two', '2'), ('three', '3'), ('four', '4'), ('five', '5'), ('six', '6'), ('seven', '7'),
             ('eight', '8'), ('nine', '9'), ('ten', '10'), ('eleven', '11'), ('twelve', '12'))


def norm_answer(fmt, ans):
    """The answer as the verify tool should get it, or '' when it does not fit the format (re-ask, not counted)."""
    kind, n = answer_format(fmt)
    a = re.sub(r'\s+', ' ', str(ans or '')).strip()
    if kind == 'date':
        m = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$', a)
        return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ''
    if kind == 'digits':
        d = re.sub(r'\D', '', a)
        return d if d and (not n or len(d) == n) else ''
    if kind == 'name':
        a = re.sub(r"[^\w '\-]|\d|_", '', a).strip()
        return re.sub(r'[^\W\d_]+', lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), a)
    if kind == 'alnum':
        return re.sub(r'[^0-9A-Za-z]', '', a).upper()
    if kind == 'postcode':     # uppercase, one space; a UK-style 'inward code' format gets the space before the last 3
        p = re.sub(r'[^0-9A-Za-z]', '', a).upper()
        if re.search(r'\b(inward|outward) code\b', str(fmt).lower()) and 5 <= len(p) <= 7:
            return p[:-3] + ' ' + p[-3:]
        return re.sub(r'[^0-9A-Za-z ]', '', a).upper().strip()
    return a


D_ASK_YEAR = 'And the year, please?'
D_ASK_DAY = 'And the day and the month, please?'


def assemble_answer(st, field, fmt, ev):
    """An identity answer over several turns (clean-1 surface PUB-06: 'May seventeenth.' then 'nineteen eighty six.').
    Pieces are kept per field until the answer is complete; a new piece replaces the old one (a correction); they are
    dropped once an answer is sent, so a later answer never inherits a piece of an earlier one (PUB-03).
    -> (answer, '') when complete, ('', question) when a piece is missing, ('', '') when nothing usable came."""
    kind, n = answer_format(fmt)
    pcs = dict((st.get('_idp') or dict()).get(field) or dict())
    raw = str(ev.get('ans') or '').strip()
    if kind == 'date':
        m = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$', raw)
        if m:
            pcs['d'], pcs['m'] = int(m.group(3)), int(m.group(2))
            if 'y' not in ev:            # older prompt: the year in ans is taken as said
                pcs['y'] = int(m.group(1))
        for key in ('d', 'm'):
            v = re.sub(r'\D', '', str(ev.get(key) or ''))
            if v:
                pcs[key] = int(v)
        y = re.sub(r'\D', '', str(ev.get('y') or ''))
        if len(y) == 4:                  # only a year said in these words (PUB-03)
            pcs['y'] = int(y)
        if not pcs:
            return '', ''
        if all(k in pcs for k in ('d', 'm', 'y')):
            st.setdefault('_idp', dict()).pop(field, None)
            return norm_answer('date', '%04d-%02d-%02d' % (pcs['y'], pcs['m'], pcs['d'])), ''
        st.setdefault('_idp', dict())[field] = pcs
        return '', (D_ASK_YEAR if 'y' not in pcs else D_ASK_DAY)
    if kind == 'digits' and n:
        got = re.sub(r'\D', '', raw)
        if not got:
            return '', ''
        digits = got if len(got) >= n else (pcs.get('digits', '') + got)
        if len(digits) >= n:
            st.setdefault('_idp', dict()).pop(field, None)
            return norm_answer(fmt, digits[-n:] if len(got) < n else got), ''
        st.setdefault('_idp', dict())[field] = dict(digits=digits)
        return '', D_CONTINUE
    st.setdefault('_idp', dict()).pop(field, None)
    return norm_answer(fmt, raw), ''


def identity(policy, st, ev, today, cv):
    k = ev.get('kind')
    idt = st['identity']
    qs = (policy.get('identity') or dict()).get('questions') or []
    if k == 'callback':
        return self_callback(policy, st, ev, today, cv)
    if k == 'identity':
        field = idt['order'][idt['idx']]
        fmt = str(qs[idt['idx']].get('format') or '') if idt['idx'] < len(qs) else ''
        ans, missing = assemble_answer(st, field, fmt, ev)
        if missing:          # a piece of the answer is still to come: ask for it, not a wrong answer or a refusal
            return ask(st, missing, st['q'])
        if not ans:          # not in the field's format: ask again, not a wrong answer
            return resay(st)
        st['_last_args'] = dict(customer_id=cid(cv), field=field, answer=ans)
        return call(st, 'verify', 'verify_identity', dict(st['_last_args']))
    if k == 'topic':
        return topic_event(policy, st, ev, today, cv)
    if k == 'no':
        return topic_event(policy, st, dict(ev, kind='topic', t='decline'), today, cv) if st['q'].startswith('id_') else resay(st)
    if str(st.get('q') or '').startswith('id_'):     # chatter or a garbled turn: never a refusal (clean-1 surface PUB-07)
        return id_reask(policy, st)
    return resay(st)


def id_unfinished(policy):
    """A customer who confirmed the name but never finished the security questions (biz-1 surface PUB-10): the brief's
    hangup_default.before_verified close, else the declined slot (the not-verified family, never a callback code)."""
    h = (policy.get('hangup_default') or dict()).get('before_verified') or dict()
    if isinstance(h, dict) and _none(h.get('outcome')):
        return _none(h.get('outcome')), _none(h.get('reason'))
    return tuple(V(policy)['declined'])


ID_OTHER_CAP = 6     # DEFAULT hard cap: this many turns with no answer to a security question, then the unclear slot


def id_reask(policy, st):
    """The open security question again, worded two ways in turn (no tts loop), counted on its own cap; at the cap the
    unclear slot (no refusal was said)."""
    st['_id_other'] = st.get('_id_other', 0) + 1
    if st['_id_other'] > ID_OTHER_CAP:
        o, r = id_unfinished(policy) if st.get('who') == 'self' else V(policy)['unclear']
        return do_close(policy, st, o, r, D_FAREWELL)
    idt, qs = st['identity'], (policy.get('identity') or dict()).get('questions') or []
    q = (qs[idt['idx']].get('ask') if idt['idx'] < len(qs) else '') or D_SAFE
    return ask(st, (D_NOT_CAUGHT + ' ' + q) if st['_id_other'] % 2 else q, st['q'])


D_NOT_CAUGHT = "Sorry, I didn't catch that."


# ---------------------------------------------------------------- event parsing (the hub reads `ev`)
def one_edit(a, b):
    """True when a and b differ by at most one inserted, deleted or changed letter. ponytail: tokens are 6 random
    letters (26^6), so a one-edit collision with a stale token is about 1 in 10^6 per turn; the last token itself is
    always rejected exactly."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or not a or not b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def parse_event(raw, st, topics=()):
    """The ev grammar -> dict, or None when stale / unparseable (stale events change nothing)."""
    if not raw:
        return None
    out = dict()
    for part in str(raw).split(';'):
        k, _, v = part.partition('=')
        k, v = k.strip(), v.strip()
        if k in out:     # a repeated key: the first wins; a topic name in a second also= is kept as also_t
            if k == 'also' and v in TOPIC_RANK and not out.get('also_t'):
                out['also_t'] = v
            continue
        out[k] = v
    n, tok = out.get('n') or '', st.get('tok') or ''
    if n == st.get('last_tok') and tok != 'kstart':
        return None
    if n != tok and not (tok != 'kstart' and n != st.get('last_tok') and one_edit(n, tok)):
        return None
    out['n'] = tok
    if out.get('also') in TOPIC_RANK and out.get('also') != 'other':
        out['also_t'], out['also'] = out.get('also_t') or out['also'], 'topic'
    if out.get('also') == 'topic' and not out.get('also_t') and out.get('kind') != 'topic' and out.get('t') in TOPIC_RANK:
        out['also_t'] = out['t']    # PUB-04 live: kind=date;also=topic;t=robot (the secondary topic in t=)
    if out.get('also') == 'topic' and not out.get('also_t'):
        out['also'] = 'none'
    if out.get('kind') in topics and out.get('kind') not in ('identity', 'who', 'date', 'amount', 'date_amount', 'accept',
                                                             'reject', 'yes', 'no', 'callback', 'topic', 'other'):
        out['t'], out['kind'] = out['kind'], 'topic'
    return out


# ---------------------------------------------------------------- code-node wrapper (runs inside Freya)
CONTRACT_TOPICS = TOPIC_RANK


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


def _dump(st, sep=None):
    s = json.dumps(st, separators=sep)
    two_c, two_o = '}' * 2, '{' * 2      # built, so this source never contains the pair itself
    while two_c in s or two_o in s:
        s = s.replace(two_c, '} }').replace(two_o, '{ {')
    return s


# Freya's code_exec prints __CODE_EXEC_RESULT__ plus the vars JSON and cuts the stdout near 10,000 chars (seen at
# 9,974). Stay under 9,000. A cut result is discarded and the error text is stored back into vars, so the next run
# is larger.
RETURN_BUDGET = 9000
# What the engine and the workflow's edges / bodies / spoken text read: never trimmed (w_*, *_count, *_status_code
# and the call variables too)
ENGINE_VARS = ('st', 'route', 'route_ok', 'say_next', 'farewell', 'talk_hint', 'close_outcome', 'close_reason', 'ev',
               'ev_tok', 'xfer_pre', 'promise_recorded', 'promise_word', 'hook_skip', 'hub_error', 'close_ok', 'ending',
               'hub_status_code', 'hub_response.status', 'hub_response.status_code')
_RESULT_MARK = '__CODE_EXEC_RESULT__'


def returned_len(vars):
    """Bytes the sandbox prints for this variable table (the same spacing the platform uses)."""
    return len(_RESULT_MARK) + len(json.dumps(dict(vars=vars), default=str))


def _noise_key(k):
    sk = str(k)
    return '.header.' in sk or sk.endswith('_response.message') or sk.endswith('_response.error') or sk.startswith('system.')


def _blank_noise(vars):
    """Response headers, platform clock strings and stored code_exec errors are never read.
    Drop the key. An empty string would still be printed, and the key names alone blew past 6,000."""
    for k in list(vars):
        if _noise_key(k):
            vars.pop(k, None)


def _blank_spent_data(vars):
    """Tool bodies are copied into st on the hub run that reads them. Drop them afterwards.
    Counts and status codes stay."""
    for k in list(vars):
        sk = str(k)
        if '_response.data' in sk or sk.endswith('_data'):
            vars.pop(k, None)


def _note_promise(vars):
    """A recorded promise must survive a later close: the outcome word is promise_word from the workflow.
    A transfer wins, the same way precedence() does."""
    st = _jsonish(vars.get('st'))
    if isinstance(st, dict) and any((p or dict()).get('status') == 'persisted' for p in (st.get('products') or [])):
        vars['promise_recorded'] = 'yes'
    if isinstance(st, dict) and st.get('transfers'):
        return
    word = vars.get('promise_word') or ''
    if vars.get('promise_recorded') == 'yes' and word:
        vars['close_outcome'] = word
        vars['close_reason'] = ''


def safe_close(policy):
    """A close the bank accepts when nothing else is known: the unclear slot, else the table's unclear / refused row,
    else the closing table's first outcome. Never an empty outcome."""
    for o, r in (slot(policy, 'unclear'), V(policy)['unclear'], V(policy)['refused']):
        if o:
            return o, r
    row = next((x for x in (policy.get('closing') or dict()).get('table') or [] if _none(x.get('outcome'))), dict())
    return _none(row.get('outcome')) or '', _none(row.get('reason')) or ''


def _engine_var(k, policy):
    sk = str(k)
    cv = (policy.get('meta') or dict()).get('call_vars') or dict()
    return (sk in ENGINE_VARS or sk.startswith('w_') or sk.endswith('_count') or sk.endswith('_status_code')
            or sk in cv.values() or sk == (policy.get('now') or dict()).get('var', 'now'))


def enforce_budget(vars, policy=None):
    """Keep the printed result under RETURN_BUDGET by dropping what nothing reads, in order: headers, old errors and
    clock strings, spent tool bodies, then every other non-engine var (largest first). st and the engine vars are
    never trimmed. A close is the last resort, only when the engine vars alone are over, and it carries a valid
    outcome (a recorded promise stays promise)."""
    policy = policy or dict()
    _blank_noise(vars)
    if returned_len(vars) <= RETURN_BUDGET:
        return
    _blank_spent_data(vars)
    for k in sorted((k for k in vars if not _engine_var(k, policy)), key=lambda k: -len(json.dumps(vars.get(k), default=str))):
        if returned_len(vars) <= RETURN_BUDGET:
            return
        vars.pop(k, None)
    if returned_len(vars) <= RETURN_BUDGET:
        return
    vars['hub_error'] = 'payload over budget: closed'
    if vars.get('route') not in ('close', 'close_retry', 'end'):
        vars['route'] = 'close'
        vars['close_outcome'], vars['close_reason'] = safe_close(policy)
    _note_promise(vars)
    if not vars.get('close_outcome'):
        vars['close_outcome'], vars['close_reason'] = safe_close(policy)
    if not vars.get('farewell'):
        vars['farewell'] = D_FAREWELL
    vars.pop('ev', None)      # an empty ev is rejected by the extractor's schema; dropped, the platform keeps its own
    vars['say_next'] = ''
    vars['talk_hint'] = ''


CLOSE_PREF = dict(refused=('refused', 'dispute', 'hardship', 'write'), dispute=('dispute', 'refused', 'hardship', 'write'),
                  hardship=('hardship', 'refused', 'dispute', 'write'), write_failed=('write', 'refused', 'dispute', 'hardship'))


def close_retry(policy, st, data):
    """close_call came back rejected (ok false or an error): the same outcome once more, with the reason the error
    explicitly allows, otherwise preserving the source outcome/reason pair. -> pair or None when already retried."""
    if st.get('_close_retried'):
        return None
    st['_close_retried'] = True
    v, o, r = V(policy), st.get('outcome'), st.get('reason')
    text = json.dumps(data) if not isinstance(data, str) else data
    m = re.search(r'reasons?[^:]*:\s*([a-z_ ,]+)', text, re.I)
    allowed = [x.strip() for x in re.split(r'[ ,]+', m.group(1)) if x.strip() and x.strip() not in ('and', 'or')] if m else []
    if r in allowed:
        return o, r
    fam = next((k for k in ('dispute', 'hardship', 'write_failed') if tuple(v[k]) == (o, r)), 'refused')
    names = dict(refused=v['refused'][1], dispute=v['dispute'][1], hardship=v['hardship'][1], write=v['write_failed'][1])
    for key in CLOSE_PREF[fam]:
        for cand in (names.get(key), key if key != 'write' else None):
            if cand and cand in allowed:
                return o, cand
    if allowed:
        return o, allowed[0]
    return o, r


def close_hub(vars, policy, st):
    """The hub run after close_call: accepted -> end; rejected -> one retry (route close_retry, no second farewell);
    rejected again -> end, never a loop."""
    s0, f0 = st['_close_snap']
    s, f = _int(vars.get('t_close_call_success_count')), _int(vars.get('t_close_call_failure_count'))
    data = _jsonish(vars.get('close_call_data'))
    if not isinstance(data, dict):
        data = _flat_data(vars, 't_close_call_response.data.')
    ok = str((data or dict()).get('ok')).lower()
    rejected = f > f0 or (s > s0 and ok == 'false') or (s == s0 and f == f0 and ok == 'false')
    st['_close_snap'] = [s, f]
    nxt = close_retry(policy, st, data) if rejected else None
    if nxt:
        st['outcome'], st['reason'] = nxt
        vars['route'], vars['close_outcome'], vars['close_reason'] = 'close_retry', nxt[0] or '', nxt[1] or ''
    else:
        vars['route'] = 'end'
    vars['st'] = _dump(st, (',', ':'))


def hub_main(vars, policy):
    _blank_noise(vars)          # headers and old sandbox errors, before anything is printed back
    cvmap = (policy.get('meta') or dict()).get('call_vars') or dict()
    cv = dict((role, vars.get(name)) for role, name in cvmap.items())
    now = str(vars.get((policy.get('now') or dict()).get('var', 'now')) or cv.get('now') or '')
    st = _jsonish(vars.get('st'))
    if not isinstance(st, dict):
        st = init_state(policy, cv)
    st['tok'] = str(vars.get('ev_tok') or st.get('tok') or 'kstart')
    if st.get('phase') == 'closed' and st.get('_close_snap') is not None:
        close_hub(vars, policy, st)        # back from t_close_call: a rejected close is retried once
        _blank_spent_data(vars)
        enforce_budget(vars, policy)
        return
    try:
        te = read_tool(vars, st)
        extra = [x.get('id') for x in policy.get('extra_topics') or [] if isinstance(x, dict) and x.get('id')]
        ev = None if te else parse_event(vars.get('ev'), st, CONTRACT_TOPICS + extra)
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
            o, r = safe_close(policy)
    vars['close_outcome'], vars['close_reason'] = o or '', r or ''
    if t == 'close':     # the counters before close_call: a later hub run can see whether it was accepted
        st2['_close_snap'] = [_int(vars.get('t_close_call_success_count')), _int(vars.get('t_close_call_failure_count'))]
    vars['route_ok'] = 'yes' if st2.get('verified') == 'yes' else 'no'
    vars['xfer_pre'] = st2.get('_xfer_pre') or 'no'
    if st2.get('_hook_skip'):
        vars['hook_skip'] = ','.join(st2['_hook_skip'])
    new = _token(st2.get('runs', 0))
    st2['tok'] = new
    vars['ev_tok'] = new
    vars['st'] = _dump(st2, (',', ':'))
    _blank_spent_data(vars)
    _note_promise(vars)
    enforce_budget(vars, policy)


def minify(src):
    """The shipped string (code_exec limit: code + data <= 131072 bytes): no docstrings or comments, no local-only
    import, and only the top-level names reachable from hub_main."""
    import ast
    tree = ast.parse(src)
    for n in ast.walk(tree):
        b = getattr(n, 'body', None)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and b and isinstance(b[0], ast.Expr) \
                and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
            n.body = b[1:] or [ast.Pass()]
    body = [n for n in tree.body if not isinstance(n, ast.Try)]   # the local 'from builder.engine.dates import'
    defs = dict()
    for n in body:
        for t in ([n.name] if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else
                  [x.id for x in getattr(n, 'targets', []) if isinstance(x, ast.Name)]):
            defs[t] = n
    keep, todo = set(), ['hub_main']
    while todo:
        k = todo.pop()
        if k in keep or k not in defs:
            continue
        keep.add(k)
        todo += [x.id for x in ast.walk(defs[k]) if isinstance(x, ast.Name)]
    named = lambda n: isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))
    tree.body = [n for n in body if not named(n) or any(defs.get(k) is n for k in keep)]   # a redefined name: the last
    out = []
    for line in ast.unparse(tree).split('\n'):   # unparse indents by 4 and puts no newline inside a literal
        body = line.lstrip(' ')
        out.append(' ' * ((len(line) - len(body)) // 4) + body)
    return '\n'.join(out)


def hub_source(policy):
    """The full code-node string: date core + reducer + policy literal + call. No double braces."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'dates.py')) as f:
        dates_src = f.read()
    with open(os.path.join(here, 'reducer.py')) as f:
        red_src = f.read()
    def strip(x):   # source quotes are for the trace, not the runtime (keeps the node small)
        if isinstance(x, dict):
            return dict((k, strip(v)) for k, v in x.items() if k not in ('source', 'superseded'))
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    pol = strip(policy)
    if os.environ.get('PER_ITEM') == '1':
        pol['per_item'] = True     # generator flag, default off: per-product terms in one turn (items=, refused=)
    for k, v in (policy.get('sentences') or dict()).items():   # brief_sentence needs to know a bridge default
        if isinstance(v, dict) and brief_sentence(policy, k, None) is None and v.get('text'):
            pol['sentences'][k]['default'] = True
    for r in pol.get('events') or []:          # the desk name is read from source quotes: keep it, not the quotes
        if r.get('topic') == 'hardship':
            r['desk'] = desk_name(next((x for x in policy.get('events') or [] if x.get('topic') == 'hardship'
                                        and x.get('effect') == r.get('effect')), r))
    lit = repr(_dump(pol, (',', ':')))
    code = minify(dates_src + '\n\n' + red_src) + '\nPOLICY = json.loads(' + lit + ')\nhub_main(vars, POLICY)\n'
    if '{' * 2 in code or '}' * 2 in code:
        raise ValueError('hub source contains double braces')
    compile(code, 'hub', 'exec')
    return code
