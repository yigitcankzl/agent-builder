"""Runtime date engine. This file IS the Freya code-node snippet (the emitter appends the policy and the call), so:
stdlib only, run_safe never raises, routing flags are strings, and the source never contains double braces.

No natural-language parsing happens here. Two-field extraction contract (validated live, 13/13 and 6/6), both
anchored to the call variable `now` by custom extraction prompts:
    date_iso   'YYYY-MM-DD' the exact day the customer named or accepted, or ''
    date_spec  labels only: rel=<today|tomorrow|none>;d=..;m=..;wd=<mon..sun>;wk=<this|next|after_next|none>;
               vague=<yes|no>;corr=<yes|no>
The engine recomputes the day from the labels with calendar arithmetic, cross-checks it with date_iso (a mismatch
means ask again, except when date_iso is the date just offered: an accepted offer), applies the policy, and writes:
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
        # a calendar deadline on a non-business day: the last recordable day is the business day before it
        d = shift_to_business_day(today + datetime.timedelta(days=band['days']), policy, -1)
        return d if d is not None and d >= today else today
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


WD_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def parse_spec(spec):
    out = dict()
    for part in str(spec or '').split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            v = v.strip().lower()
            if v not in ('', 'none', 'null'):
                out[k.strip().lower()] = v
    return out


def _safe_date(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def date_from_spec(today, spec, policy):
    """Calendar arithmetic on the extraction's labels (no language parsing). -> (date or None, kind)
    kind: exact | vague | none | invalid."""
    rel, wd, wk = spec.get('rel'), spec.get('wd'), spec.get('wk', 'none')
    try:
        dd = int(spec['d']) if 'd' in spec else None
        mm = int(spec['m']) if 'm' in spec else None
    except ValueError:
        return None, 'invalid'
    if rel == 'today':
        return today, 'exact'
    if rel == 'tomorrow':
        return today + datetime.timedelta(days=1), 'exact'
    if dd is not None:
        if mm is not None:  # the year is never said: take the occurrence nearest to today
            opts = [c for c in (_safe_date(today.year + k, mm, dd) for k in (-1, 0, 1)) if c is not None]
            cand = min(opts, key=lambda c: abs((c - today).days)) if opts else None
        else:  # day only: this month if still ahead, else next month
            cand = _safe_date(today.year, today.month, dd)
            if cand is None or cand < today:
                ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                cand = _safe_date(ny, nm, dd)
        if cand is None or (wd in WD_KEYS and cand.weekday() != WD_KEYS.index(wd)):
            return None, 'invalid'
        return cand, 'exact'
    if wd in WD_KEYS:
        target = WD_KEYS.index(wd)
        monday = today - datetime.timedelta(days=today.weekday())
        if wk == 'next' and (policy.get('weekday_words') or dict()).get('next') == 'next_occurrence':
            return today + datetime.timedelta(days=(target - today.weekday() - 1) % 7 + 1), 'exact'
        weeks = 1 if wk == 'next' else 2 if wk == 'after_next' else 0
        cand = monday + datetime.timedelta(days=7 * weeks + target)
        if weeks == 0 and cand < today:  # a bare or 'this' weekday already gone this week: the coming one
            cand = cand + datetime.timedelta(days=7)
        return cand, 'exact'
    if spec.get('vague') == 'yes' or wk in ('this', 'next', 'after_next'):
        return None, 'vague'
    return None, 'none'


def interpret(today, date_iso, date_spec, policy, last_offer=''):
    """Two-field extraction contract. date_spec (labels) is recomputed in code and cross-checked with date_iso;
    a disagreement is 'invalid' (ask again), except when date_iso is the date we just offered: the customer accepted
    the offer and the label extractor kept its old labels (seen live, PUB-07 sim dd5bdf3c). -> (kind, date)."""
    cand, kind = date_from_spec(today, parse_spec(date_spec), policy)
    try:
        iso = datetime.date.fromisoformat(str(date_iso).strip()[:10]) if date_iso else None
    except ValueError:
        iso = None
    if iso is not None and last_offer and iso.isoformat() == last_offer and iso != cand:
        return 'exact', iso
    if kind == 'invalid' or (kind == 'exact' and iso is not None and iso != cand):
        return 'invalid', None
    if kind == 'none' and iso is not None:
        return 'exact', iso
    return kind, cand


def decide(today, days_late, kind, named, vague_count, policy):
    """Pure decision -> dict(reason, named, accepted, deadline)."""
    deadline = deadline_for(today, days_late, policy)
    out = lambda reason, named=None, acc=None: dict(reason=reason, named=named, accepted=acc, deadline=deadline)
    if kind == 'vague':
        v = policy['on_vague']
        if vague_count >= int(v.get('asks', 1)) and v.get('then') == 'offer_deadline':
            return out('vague_final', acc=deadline)
        return out('vague')
    if kind != 'exact' or named is None:
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
    iso = str(vars.get(inp.get('iso_var', 'date_iso')) or '').strip()
    spec = str(vars.get(inp.get('spec_var', 'date_spec')) or '').strip()
    sig = iso + '|' + spec
    if sig == '|' or sig == str(vars.get('date_handled') or ''):
        vars['date_state'] = 'same'  # sticky extraction: a turn without a new date must not re-decide the old one
        vars['route_date'] = 'continue'
        return
    vars['date_handled'] = sig
    vars['date_state'] = 'new'
    today = datetime.date.fromisoformat(str(vars.get(policy['now']['var']))[:10])
    vague_count = int(vars.get('date_vague_count') or 0)
    kind, named = interpret(today, iso, spec, policy, str(vars.get('accepted_date') or ''))
    r = decide(today, current_days_late(vars, policy), kind, named, vague_count, policy)
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
