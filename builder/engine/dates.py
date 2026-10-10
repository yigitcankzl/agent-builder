"""Runtime date engine. This file IS the Freya code-node snippet (the emitter appends the policy and the call), so:
stdlib only, run_safe never raises, routing flags are strings, and the source never contains double braces.

No natural-language parsing happens here. The Freya extraction model writes ONE normalized field (policy
inputs.date_var), anchored to the call variable `now` by its extraction prompt:
    'YYYY-MM-DD'  an exact day the customer named (the corrected one if they corrected themselves)
    'vague: ...'  only a period or an event, with the customer's words ("vague: when my salary comes"); the words
                  make a second, different vague answer a new value, so it is not swallowed by the sticky dedupe
    ''            nothing yet
The engine applies the brief's date policy to it and writes:
    accepted_date  the date that may be recorded now (YYYY-MM-DD) or ''
    date_reason    ok | non_business_day | after_deadline | before_earliest | vague | vague_final | invalid | error
    route_date     'say' (speak say_next verbatim) | 'continue' (dialogue model continues)
    say_next       the sentence to speak when route_date is 'say'
    date_state     'new' | 'same'   (extraction values are sticky and cannot be cleared from code)
Every brief-specific value (calendar, holidays, deadline bands, actions, sentences, variable names) is in the policy.
"""
import datetime
import json

WD_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']


def say_date(d):
    return WD_NAMES[d.weekday()] + ' ' + str(d.day) + ' ' + MONTHS[d.month - 1]


def is_business_day(d, policy):
    bd = policy['business_days']
    return d.weekday() in bd['weekdays'] and d.isoformat() not in bd['holidays']


def shift_to_business_day(d, policy, step):
    for _ in range(366):
        if is_business_day(d, policy):
            return d
        d = d + datetime.timedelta(days=step)
    return None


def add_business_days(d, n, policy):
    c = 0
    for _ in range(3660):
        if c >= n:
            return d
        d = d + datetime.timedelta(days=1)
        if is_business_day(d, policy):
            c += 1
    return d


def deadline_for(today, days_late, policy):
    """Latest recordable date: the first band whose max_days_late covers days_late (bands sorted ascending)."""
    dl = policy['deadline']
    bands = sorted(dl['bands'], key=lambda b: b['max_days_late'])
    band = bands[-1]
    for b in bands:
        if days_late <= b['max_days_late']:
            band = b
            break
    if dl.get('rule', 'business_days_after_today') == 'calendar_days_after_today':
        return today + datetime.timedelta(days=band['days'])
    return add_business_days(today, band['days'], policy)


def _as_list(x):
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except Exception:
            return []
    if isinstance(x, dict):
        x = x.get('products') or []
    return x if isinstance(x, list) else []


def current_days_late(vars, policy):
    """days_late of the product being discussed: products list + current id, else a plain variable."""
    inp = policy['inputs']
    prods = _as_list(vars.get(inp.get('products_var', 'products')))
    cur = str(vars.get(inp.get('current_product_var', 'current_product_id')) or '')
    idf, dlf = inp.get('product_id_field', 'product_id'), inp.get('days_late_field', 'days_late')
    chosen = None
    for p in prods:
        if isinstance(p, dict) and str(p.get(idf)) == cur:
            chosen = p
    if chosen is None and prods and isinstance(prods[0], dict):
        chosen = prods[0]
    if chosen is not None and chosen.get(dlf) is not None:
        return int(float(chosen.get(dlf)))
    return int(float(vars.get(inp.get('days_late_var', 'days_late'))))


def decide(today, days_late, said, vague_count, policy):
    """Pure decision -> dict(reason, named, accepted, deadline). `said` is 'YYYY-MM-DD', 'vague' or ''."""
    deadline = deadline_for(today, days_late, policy)
    out = lambda reason, named=None, acc=None: dict(reason=reason, named=named, accepted=acc, deadline=deadline)
    said = str(said or '').strip().lower()
    if said.startswith('vague'):
        v = policy['on_vague']
        if vague_count >= int(v.get('asks', 1)) and v.get('then') == 'offer_deadline':
            return out('vague_final', acc=deadline)
        return out('vague')
    try:
        named = datetime.date.fromisoformat(said[:10])
    except ValueError:
        return out('invalid')
    earliest = today if policy['earliest'].get('allow_today', True) else today + datetime.timedelta(days=1)
    if named < earliest:
        return out('before_earliest', named=named)
    if named > deadline:
        return out('after_deadline', named=named,
                   acc=deadline if policy['on_after_deadline'].get('action') == 'offer_deadline' else None)
    if is_business_day(named, policy):
        return out('ok', named=named, acc=named)
    action = policy['on_non_business_day'].get('action', 'next_business_day')
    if action == 'reject':
        return out('non_business_day', named=named)
    alt = shift_to_business_day(named, policy, 1 if action == 'next_business_day' else -1)
    if alt is None or alt > deadline:
        return out('after_deadline', named=named,
                   acc=deadline if policy['on_after_deadline'].get('action') == 'offer_deadline' else None)
    if alt < earliest:
        return out('before_earliest', named=named)
    return out('non_business_day', named=named, acc=alt)


SAY_KEYS = dict(non_business_day=('on_non_business_day', 'say'), after_deadline=('on_after_deadline', 'say'),
                before_earliest=('on_before_earliest', 'say'), vague=('on_vague', 'say_ask'),
                vague_final=('on_vague', 'say_final'), invalid=('on_invalid', 'say'), ok=('on_ok', 'say'))


def sentence(r, policy):
    sec, key = SAY_KEYS.get(r['reason'], ('', ''))
    tpl = (policy.get(sec) or dict()).get(key) or ''
    for token, d in (('<NAMED>', r['named']), ('<DATE>', r['accepted']), ('<DEADLINE>', r['deadline'])):
        tpl = tpl.replace(token, say_date(d) if d else '')
    return tpl


def run(vars, policy):
    inp = policy['inputs']
    said = str(vars.get(inp.get('date_var', 'date_said')) or '').strip()
    if not said:
        vars['date_state'] = 'same'
        vars['route_date'] = 'continue'
        return
    if said == str(vars.get('date_handled') or ''):
        vars['date_state'] = 'same'  # sticky extraction: a turn without a new date must not re-decide the old one
        vars['route_date'] = 'continue'
        return
    vars['date_handled'] = said
    vars['date_state'] = 'new'
    today = datetime.date.fromisoformat(str(vars.get(policy['now']['var']))[:10])
    vague_count = int(vars.get('date_vague_count') or 0)
    r = decide(today, current_days_late(vars, policy), said, vague_count, policy)
    if r['reason'] == 'vague':
        vars['date_vague_count'] = str(vague_count + 1)
    vars['date_reason'] = r['reason']
    vars['accepted_date'] = r['accepted'].isoformat() if r['accepted'] else ''
    vars['accepted_date_say'] = say_date(r['accepted']) if r['accepted'] else ''
    vars['date_deadline'] = r['deadline'].isoformat()
    vars['say_next'] = sentence(r, policy)
    vars['route_date'] = 'say' if vars['say_next'] else 'continue'


def run_safe(vars, policy):
    try:
        run(vars, policy)
    except Exception as e:
        vars['date_state'] = 'new'
        vars['date_reason'] = 'error'
        vars['accepted_date'] = ''
        vars['say_next'] = ''
        vars['route_date'] = 'continue'
        vars['date_error'] = str(e)[:200]
