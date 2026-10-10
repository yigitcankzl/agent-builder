"""Runtime date resolver. Runs inside a Freya code node: stdlib only, never raises from run_safe, no double braces.

Natural language is NOT parsed here. The extraction model writes two normalized fields:
  date_iso   exact date as YYYY-MM-DD or ''   (custom extraction_prompt anchored to the call variable now)
  date_spec  rel=..;d=..;m=..;wd=..;wk=..;vague=..;corr=..   (labels only, no arithmetic)
This module recomputes the date from date_spec and now, cross-checks date_iso, and applies the brief's date policy
(business days, holidays, per-band deadline, actions). Every brief-specific value comes from the policy argument.
"""
import datetime
import json

WD_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
WD_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']


def say_date(d):
    return WD_NAMES[d.weekday()] + ' ' + str(d.day) + ' ' + MONTHS[d.month - 1]


def is_business_day(d, policy):
    return d.weekday() in policy['business_weekdays'] and d.isoformat() not in policy['holidays']


def next_business_day(d, policy):
    while not is_business_day(d, policy):
        d = d + datetime.timedelta(days=1)
    return d


def add_business_days(d, n, policy):
    c = 0
    while c < n:
        d = d + datetime.timedelta(days=1)
        if is_business_day(d, policy):
            c += 1
    return d


def deadline_for(today, days_late, policy):
    """Latest recordable date: the first band whose max_days_late covers days_late gives n business days after today."""
    bands = policy['deadline_bands']
    band = next((b for b in bands if days_late <= b['max_days_late']), bands[-1])
    return add_business_days(today, band['business_days_after_today'], policy)


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
    """-> (date or None, kind) with kind in exact | vague | none | invalid."""
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
        if mm is not None:
            # the year is never said: take the occurrence nearest to today (handles the year boundary)
            opts = [c for c in (_safe_date(today.year + k, mm, dd) for k in (-1, 0, 1)) if c is not None]
            cand = min(opts, key=lambda c: abs((c - today).days)) if opts else None
        else:
            cand = _safe_date(today.year, today.month, dd)
            if cand is None or cand < today:
                ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                cand = _safe_date(ny, nm, dd)
        if cand is None:
            return None, 'invalid'
        if wd in WD_KEYS and cand.weekday() != WD_KEYS.index(wd):
            return None, 'invalid'
        return cand, 'exact'
    if wd in WD_KEYS:
        target = WD_KEYS.index(wd)
        monday = today - datetime.timedelta(days=today.weekday())
        if wk == 'next' and policy.get('next_weekday') != 'following_week':
            return today + datetime.timedelta(days=(target - today.weekday() - 1) % 7 + 1), 'exact'
        weeks = 1 if wk == 'next' else 2 if wk == 'after_next' else 0
        cand = monday + datetime.timedelta(days=7 * weeks + target)
        if weeks == 0 and cand < today:  # a bare or "this" weekday already gone this week means the coming one
            cand = cand + datetime.timedelta(days=7)
        return cand, 'exact'
    if spec.get('vague') == 'yes' or wk in ('this', 'next', 'after_next'):
        return None, 'vague'
    return None, 'none'


def resolve(today, days_late, date_iso, date_spec, vague_count, policy):
    """Pure decision -> dict(status, named, record, deadline).
    status: ok | non_business | after_deadline | past | vague | vague_final | unclear | none."""
    deadline = deadline_for(today, days_late, policy)
    cand, kind = date_from_spec(today, parse_spec(date_spec), policy)
    try:
        iso = datetime.date.fromisoformat(str(date_iso)[:10]) if date_iso else None
    except ValueError:
        iso = None
    res = lambda st, named=None, rec=None: dict(status=st, named=named, record=rec, deadline=deadline)
    if kind == 'invalid' or (kind == 'exact' and iso is not None and iso != cand):
        return res('unclear')
    if kind == 'none' and iso is not None:
        cand, kind = iso, 'exact'
    if kind == 'vague':
        return res('vague_final', rec=deadline) if vague_count >= policy.get('vague_asks', 1) else res('vague')
    if kind != 'exact':
        return res('none')
    earliest = today if policy.get('allow_today', True) else today + datetime.timedelta(days=1)
    if cand < earliest:
        return res('past', named=cand)
    if cand > deadline:
        return res('after_deadline', named=cand, rec=deadline)
    if not is_business_day(cand, policy):
        shifted = next_business_day(cand, policy)
        if shifted > deadline:
            return res('after_deadline', named=cand, rec=deadline)
        return res('non_business', named=cand, rec=shifted)
    return res('ok', named=cand, rec=cand)


def fill(template, r):
    out = str(template)
    for key, d in (('<NAMED>', r['named']), ('<DATE>', r['record']), ('<DEADLINE>', r['deadline'])):
        out = out.replace(key, say_date(d) if d else '')
    return out


def run(vars, policy):
    """Code-node entry: reads extraction and call variables, writes the decision variables."""
    sig = str(vars.get('date_iso') or '') + '|' + str(vars.get('date_spec') or '')
    if sig == str(vars.get('date_handled') or ''):
        vars['date_state'] = 'same'  # extraction vars cannot be cleared from code, so dedupe on what was handled
        return
    vars['date_handled'] = sig
    vars['date_state'] = 'new'
    today = datetime.date.fromisoformat(str(vars.get(policy.get('now_var', 'now')))[:10])
    days_late = int(float(vars.get(policy.get('days_late_var', 'days_late')) or 0))
    vague_count = int(vars.get('date_vague_count') or 0)
    r = resolve(today, days_late, vars.get('date_iso'), vars.get('date_spec'), vague_count, policy)
    st = r['status']
    if st == 'vague':
        vars['date_vague_count'] = str(vague_count + 1)
    vars['date_status'] = st
    vars['date_named_iso'] = r['named'].isoformat() if r['named'] else ''
    vars['date_record'] = r['record'].isoformat() if r['record'] else ''
    vars['date_record_say'] = say_date(r['record']) if r['record'] else ''
    vars['date_deadline_iso'] = r['deadline'].isoformat()
    vars['date_deadline_say'] = say_date(r['deadline'])
    tpl = policy['say'].get(st)
    vars['say_next'] = fill(tpl, r) if tpl else ''
    vars['date_route'] = 'say' if tpl else 'cont'
    vars['date_facts'] = json.dumps(dict(status=st, customer_named=vars['date_named_iso'],
                                         recordable_date=vars['date_record'], deadline=vars['date_deadline_iso']))


def run_safe(vars, policy):
    try:
        run(vars, policy)
    except Exception as e:
        vars['date_state'] = 'new'
        vars['date_route'] = 'cont'
        vars['date_status'] = 'error'
        vars['date_error'] = str(e)[:200]
