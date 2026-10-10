"""Generate out/brief-b.workflow.json from Brief B (which builds on Brief A) and tools/openapi.json."""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = json.load(open(ROOT / "tools/openapi.json"))
BASE = API["servers"][0]["url"]
HOLIDAYS = ["2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"]


def body_schema(path):
    return API["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]


def api_tool(name, desc, fields, required, pre="", post="", retries=0, mapping=None):
    """fields: name -> leaf spec (without default); customer_id is always baked."""
    props = {"customer_id": {"type": "string", "default": "{{customer_id}}"}}
    for k, spec in fields.items():
        leaf = dict(spec)
        leaf.setdefault("default", "{{%s}}" % k)
        props[k] = leaf
    t = {
        "type": "function",
        "config": {"timeoutMs": 12000, "maxRetries": retries},
        "function": {
            "name": name,
            "handler": "__function__:api_call",
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "default": BASE + "/" + name},
                    "method": {"type": "string", "default": "POST"},
                    "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                    "body": {"type": "object", "properties": props, "required": required},
                },
            },
        },
    }
    if pre: t["pre_process_code"] = pre
    if post: t["post_process_code"] = post
    if mapping: t["response_mapping"] = mapping
    return t


def check_code(src):
    assert "{{" not in src and "}}" not in src, src
    compile(src, "<hook>", "exec")
    return src


def enum_of(path, field):
    return body_schema(path)["properties"][field]["enum"]


# ---------------------------------------------------------------- code: date facts at call start
SETUP_CODE = check_code(r'''
import datetime, json
HOL = HOLIDAYS_JSON
WD = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
MO = ['January','February','March','April','May','June','July','August','September','October','November','December']
def bd(d):
    return d.weekday() < 5 and d.isoformat() not in HOL
def say(d):
    return WD[d.weekday()] + ' ' + str(d.day) + ' ' + MO[d.month-1] + ' ' + str(d.year)
try:
    now = str(vars.get('now') or '')
    today = datetime.date.fromisoformat(now[:10])
    now_time = now[11:16] if len(now) >= 16 else '00:00'
    vars['today_iso'] = today.isoformat()
    vars['today_text'] = say(today)
    vars['now_time'] = now_time
    def nth_bd(n):
        d = today; c = 0
        while c < n:
            d = d + datetime.timedelta(days=1)
            if bd(d): c += 1
        return d
    nb = nth_bd(1)
    vars['next_bd_iso'] = nb.isoformat()
    vars['next_bd_text'] = say(nb)
    vars['deadline_early_iso'] = nth_bd(12).isoformat()
    vars['deadline_late_iso'] = nth_bd(7).isoformat()
    monday = today - datetime.timedelta(days=today.weekday())
    def last_bd_of_week(m):
        best = None
        for i in range(5):
            d = m + datetime.timedelta(days=i)
            if bd(d): best = d
        return best
    l1 = last_bd_of_week(monday)
    if l1 is None or l1 <= today:
        l1 = last_bd_of_week(monday + datetime.timedelta(days=7))
    vars['attempt1_iso'] = l1.isoformat()
    words = []
    for i in range(7):
        this_d = monday + datetime.timedelta(days=i)
        next_d = this_d + datetime.timedelta(days=7)
        words.append('"this ' + WD[i] + '" = ' + say(this_d) + ('' if this_d >= today else ' (already past)') + '; "next ' + WD[i] + '" = ' + say(next_d))
    vars['weekday_words_text'] = '\n'.join(words)
    today_ok = now_time < '19:00'
    if today_ok:
        vars['callback_days_text'] = 'today ' + say(today) + ' (' + today.isoformat() + '), only at a time later than ' + now_time + ' and no later than 19:00; or the next business day ' + say(nb) + ' (' + nb.isoformat() + '), from 10:00 to 19:00'
    else:
        vars['callback_days_text'] = 'the next business day ' + say(nb) + ' (' + nb.isoformat() + '), from 10:00 to 19:00. Today is no longer possible'
    vars['date_state'] = 'ok'
except Exception as e:
    vars['date_state'] = 'error'
    vars['today_iso'] = ''
    vars['today_text'] = str(vars.get('now') or '')
    vars['now_time'] = ''
    vars['weekday_words_text'] = ''
    vars['callback_days_text'] = 'today or the next business day, from 10:00 to 19:00, later than now'
'''.replace("HOLIDAYS_JSON", json.dumps(HOLIDAYS)))

# ---------------------------------------------------------------- hooks
VERIFY_PRE = check_code(r'''
import re
MO = ['january','february','march','april','may','june','july','august','september','october','november','december']
try:
    b = config.get('body')
    if isinstance(b, dict):
        f = str(b.get('field') or '')
        a = str(b.get('answer') or '').strip()
        vars['pending_field'] = f
        if f == 'phone_last4':
            digits = re.sub(r'\D', '', a)
            if len(digits) >= 4:
                b['answer'] = digits[-4:]
        elif f == 'date_of_birth':
            low = a.lower()
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', a):
                m = re.match(r'^(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})$', a)
                if m:
                    b['answer'] = m.group(3) + '-' + m.group(2).zfill(2) + '-' + m.group(1).zfill(2)
                else:
                    mon = None
                    for i, name in enumerate(MO):
                        if name in low or (name[:3] in low and len(name) > 3):
                            mon = i + 1
                            break
                    nums = re.findall(r'\d+', low)
                    year = [x for x in nums if len(x) == 4]
                    day = [x for x in nums if 1 <= len(x) <= 2]
                    if mon and year and day:
                        b['answer'] = year[0] + '-' + str(mon).zfill(2) + '-' + day[0].zfill(2)
except Exception:
    pass
''')

VERIFY_POST = check_code(r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        f = str(vars.get('pending_field') or '')
        if not isinstance(d, dict):
            result['data'] = dict(ok=False, what_to_do_next='The check service did not answer. Say there was a short technical problem and ask the same question again.')
        else:
            left = d.get('wrong_answers_left')
            if str(d.get('all_verified')).lower() == 'true':
                vars['id_state'] = 'verified'
                d['what_to_do_next'] = 'Both security answers are correct. The customer is verified.'
            elif d.get('hint') == 'day_month_swapped':
                d['what_to_do_next'] = 'The day and the month look swapped. This is NOT a wrong answer. Ask the customer to say their date of birth again with the month as a word, for example 14 March 1988.'
            elif str(d.get('ok')).lower() != 'true':
                d['what_to_do_next'] = 'The answer could not be read. This is NOT a wrong answer. Ask the same question again (for a date of birth, ask for the day, the month as a word, and the year).'
            elif str(d.get('verified')).lower() == 'true':
                if f == 'date_of_birth':
                    d['what_to_do_next'] = 'The date of birth is correct. Now ask for the last four digits of the phone number on file.'
                else:
                    d['what_to_do_next'] = 'This answer is correct. Ask the remaining security question.'
            else:
                try:
                    n = int(left)
                except Exception:
                    n = 1
                if n <= 0:
                    vars['id_state'] = 'failed'
                    d['what_to_do_next'] = 'Three wrong answers: the identity check has failed. Do not mention any account or debt.'
                else:
                    d['what_to_do_next'] = 'That answer is wrong. Do not reveal the right answer. Ask the same question once more.'
except Exception:
    pass
''')

GENERIC_POST = check_code(r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
except Exception:
    pass
''')

TRANSFER_PRE = check_code(r'''
try:
    b = config.get('body')
    if isinstance(b, dict):
        vars['pending_queue'] = str(b.get('queue') or '')
except Exception:
    pass
''')
TRANSFER_POST = check_code(r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
            vars['transfer_queue'] = str(vars.get('pending_queue') or '')
            d['what_to_do_next'] = 'The transfer is done. Tell the customer a colleague will take over, thank them and say goodbye, then call close_call with outcome transferred.'
        else:
            result['data'] = dict(ok=False, what_to_do_next='The transfer failed. Tell the customer you could not connect them right now. Do not say they were connected.')
except Exception:
    pass
''')

CALLBACK_PRE = check_code(r'''
import re
try:
    b = config.get('body')
    if isinstance(b, dict):
        t = str(b.get('time') or '').strip()
        m = re.match(r'^(\d{1,2})[:.h ]?(\d{2})?', t)
        if m:
            b['time'] = m.group(1).zfill(2) + ':' + (m.group(2) or '00')
except Exception:
    pass
''')
CALLBACK_POST = check_code(r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
            vars['callback_state'] = 'booked'
            d['what_to_do_next'] = 'The callback is booked. Tell the person we will call back then, thank them, say goodbye, then call close_call with outcome not_reached and reason callback.'
        else:
            result['data'] = dict(ok=False, what_to_do_next='The callback could not be booked. Call schedule_callback once more with the same date and time. If it fails again, say you could not book it, thank them, say goodbye, and call close_call with not_reached / no_callback.')
except Exception:
    pass
''')


# ---------------------------------------------------------------- code: account facts after get_account (1 to 3 products)
ACCOUNT_CODE = check_code(r'''
import datetime, json, re
HOL = HOLIDAYS_JSON
WD = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
MO = ['January','February','March','April','May','June','July','August','September','October','November','December']
def bd(d):
    return d.weekday() < 5 and d.isoformat() not in HOL
def say(d):
    return WD[d.weekday()] + ' ' + str(d.day) + ' ' + MO[d.month-1] + ' ' + str(d.year)
def money(x):
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return format(int(round(x)), ',')
    return format(x, ',.2f')
def find_products():
    p = vars.get('products')
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            p = None
    if isinstance(p, dict) and 'products' in p:
        p = p.get('products')
    if isinstance(p, list) and p:
        return p
    for k in list(vars.keys()):
        v = vars.get(k)
        if k.endswith('products') and k != 'products':
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    v = None
            if isinstance(v, list) and v:
                return v
    rows = dict()
    for k in list(vars.keys()):
        m = re.search(r'products\.(\d+)\.(\w+)$', k)
        if m:
            rows.setdefault(int(m.group(1)), dict())[m.group(2)] = vars.get(k)
    return [rows[i] for i in sorted(rows)]
def nth_bd(today, n):
    d = today; c = 0
    while c < n:
        d = d + datetime.timedelta(days=1)
        if bd(d): c += 1
    return d
def next_bd_on_or_after(d):
    while not bd(d): d = d + datetime.timedelta(days=1)
    return d
try:
    prods = find_products()
    if not prods:
        raise ValueError('no products')
    today = datetime.date.fromisoformat(str(vars.get('now'))[:10])
    a1 = datetime.date.fromisoformat(str(vars.get('attempt1_iso')))
    facts = dict()
    order = []
    lines = []
    plan = []
    say_lines = []
    max_deadline = today
    for i, p in enumerate(prods):
        pid = str(p.get('product_id'))
        ptype = str(p.get('type'))
        past_due = float(p.get('past_due'))
        days_late = int(float(p.get('days_late')))
        if ptype == 'credit_card':
            floor = float(p.get('minimum_payment'))
            phrase = 'credit card ending ' + str(p.get('card_last4') or '')
            floor_name = 'minimum payment'
        else:
            floor = float(p.get('instalment_amount'))
            phrase = 'personal loan' if ptype == 'personal_loan' else 'car loan'
            floor_name = 'instalment amount'
        early = days_late <= 7
        deadline = nth_bd(today, 12 if early else 7)
        if deadline > max_deadline: max_deadline = deadline
        allowed = []
        d = today
        while d <= deadline:
            if bd(d): allowed.append(d.isoformat())
            d = d + datetime.timedelta(days=1)
        facts[pid] = dict(phrase=phrase, past_due=past_due, floor=floor, deadline=deadline.isoformat(), deadline_text=say(deadline), allowed=allowed)
        order.append(pid)
        band = 'EARLY band (1 to 7 days late): ONE persuasion attempt' if early else 'LATE band (8 to 45 days late): TWO persuasion attempts'
        lines.append(str(i + 1) + '. product_id ' + pid + ' = ' + phrase + ': past-due amount ' + money(past_due) + ', ' + str(days_late) + ' days late. Floor (' + floor_name + '): ' + money(floor) + '. Deadline (latest date you can record): ' + say(deadline) + ' (' + deadline.isoformat() + '). ' + band + '.')
        if early:
            plan.append('- ' + phrase + ' (' + pid + '), EARLY band, exactly ONE persuasion attempt. Attempt 1: propose ' + money(past_due) + ' on ' + say(a1) + ' (if the customer already said the full amount is too much: the floor ' + money(floor) + ' on ' + say(a1) + '). If attempt 1 is refused: STOP for this product. Make no other offer for it, do not offer the floor as a new attempt; it ends without a promise (note reason refused).')
        else:
            plan.append('- ' + phrase + ' (' + pid + '), LATE band, exactly TWO persuasion attempts. Attempt 1: propose ' + money(past_due) + ' on ' + say(a1) + ' (if the customer already said the full amount is too much: the floor ' + money(floor) + ' on ' + say(a1) + '). Attempt 2 (only after attempt 1 is refused): propose the floor ' + money(floor) + ' on the deadline ' + say(deadline) + ' and say the rest stays overdue. If attempt 2 is refused: STOP for this product, make no other offer; it ends without a promise (note reason refused).')
        say_lines.append('Your ' + phrase + ' has a past-due amount of ' + money(past_due) + ' and is ' + str(days_late) + ' days late.')
    cal = []
    d = today
    end = max_deadline + datetime.timedelta(days=21)
    while d <= end:
        label = say(d) + ' (' + d.isoformat() + ')' + (' TODAY' if d == today else '')
        kind = 'business day' if bd(d) else ('BANK HOLIDAY' if d.isoformat() in HOL else 'weekend')
        parts = []
        for pid in order:
            f = facts[pid]
            dl = datetime.date.fromisoformat(f['deadline'])
            if d > dl:
                act = 'AFTER its deadline -> latest date is ' + say(dl)
            elif bd(d):
                act = 'OK, can be recorded'
            else:
                nxt = next_bd_on_or_after(d)
                act = ('offer the next business day ' + say(nxt)) if nxt <= dl else ('offer its deadline ' + say(dl))
            parts.append((f['phrase'] + ': ' if len(order) > 1 else '') + act)
        cal.append(label + ', ' + kind + ' -> ' + '; '.join(parts))
        d = d + datetime.timedelta(days=1)
    n = len(order)
    if n == 1:
        intro = 'I am calling from the collections team about a late payment. '
        ask = ' Can you make this payment today?'
    else:
        intro = 'I am calling from the collections team about late payments on ' + str(n) + ' products. '
        ask = ' Can you pay all of them today?'
    vars['statement_text'] = intro + ' '.join(say_lines) + ask
    vars['prod_json'] = json.dumps(dict(order=order, facts=facts))
    vars['n_products'] = n
    vars['product_order_text'] = ', '.join(facts[p]['phrase'] + ' (' + p + ')' for p in order)
    vars['products_text'] = '\n'.join(lines)
    vars['attempt_plan_text'] = '\n'.join(plan)
    vars['attempt1_text'] = say(a1)
    vars['calendar_text'] = '\n'.join(cal)
    vars['missing_text'] = ', '.join(k + ' (' + facts[k]['phrase'] + ')' for k in order)
    vars['wrap_state'] = 'open'
    vars['acct_state'] = 'ok'
except Exception as e:
    vars['acct_state'] = 'error'
    vars['acct_error'] = str(e)[:200]
'''.replace("HOLIDAYS_JSON", json.dumps(HOLIDAYS)))

# ---------------------------------------------------------------- promise / note hooks
# HTTP errors skip the post-hook (the model then sees "API request failed"), so nothing here relies on a post-hook
# for a failed call, and nothing is blocked by sending to a bad URL. Code corrects values to the brief instead.
STATE_HELPERS = r'''
def _load(name, default):
    try:
        v = json.loads(str(vars.get(name) or ''))
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default
def _update_wrap():
    info = _load('prod_json', dict())
    order = info.get('order') or []
    facts = info.get('facts') or dict()
    promised = [x for x in str(vars.get('promised_ids') or '').split(',') if x]
    notes = _load('notes_json', dict())
    missing = [k for k in order if k not in promised and k not in notes]
    vars['missing_text'] = ', '.join(k + ' (' + facts.get(k, dict()).get('phrase', k) + ')' for k in missing) or 'none'
    vars['wrap_state'] = 'ready' if (order and not missing) else 'open'
    return missing
'''

PROMISE_PRE = check_code(r'''
import json, re, datetime
''' + STATE_HELPERS + r'''
MO = ['january','february','march','april','may','june','july','august','september','october','november','december']
def parse_said(text, today):
    low = str(text or '').lower()
    mon = None
    for i, name in enumerate(MO):
        if re.search(r'\b' + name[:3], low):
            mon = i + 1
            break
    nums = [int(x) for x in re.findall(r'\b(\d{1,2})(?:st|nd|rd|th)?\b', low)]
    if not mon or not nums:
        return None
    y = today.year
    try:
        d = datetime.date(y, mon, nums[0])
        if d < today:
            d = datetime.date(y + 1, mon, nums[0])
        return d
    except Exception:
        return None
try:
    b = config.get('body')
    if isinstance(b, dict):
        info = _load('prod_json', dict())
        facts = info.get('facts') or dict()
        order = info.get('order') or []
        today = datetime.date.fromisoformat(str(vars.get('now'))[:10])
        said = b.pop('date_as_said', None)
        pid = str(b.get('product_id') or '').strip()
        if pid not in facts and len(order) == 1:
            pid = order[0]
        if pid not in facts:
            for k in order:
                ph = facts[k]['phrase'].lower()
                if pid and (ph in pid.lower() or pid.lower() in ph):
                    pid = k
        b['product_id'] = pid
        sd = parse_said(said, today) if said and '{' not in str(said) else None
        iso = str(b.get('date') or '')[:10]
        if sd is not None:
            iso = sd.isoformat()
        f = facts.get(pid)
        if f:
            allowed = f['allowed']
            if iso not in allowed:
                later = [x for x in allowed if x >= iso]
                if iso > f['deadline'] or not later:
                    iso = f['deadline']
                else:
                    iso = later[0]
            try:
                amt = round(float(str(b.get('amount')).replace(',', '')), 2)
                if amt < f['floor']: amt = f['floor']
                if amt > f['past_due']: amt = f['past_due']
                b['amount'] = amt
            except Exception:
                pass
        b['date'] = iso
        q = [x for x in str(vars.get('pending_promise_ids') or '').split(',') if x]
        q.append(pid)
        vars['pending_promise_ids'] = ','.join(q)
except Exception:
    pass
''')

PROMISE_POST = check_code(r'''
import json
''' + STATE_HELPERS + r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        q = [x for x in str(vars.get('pending_promise_ids') or '').split(',') if x]
        pid = q.pop(0) if q else ''
        vars['pending_promise_ids'] = ','.join(q)
        facts = _load('prod_json', dict()).get('facts') or dict()
        phrase = facts.get(pid, dict()).get('phrase', pid)
        if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
            ids = [x for x in str(vars.get('promised_ids') or '').split(',') if x]
            if pid and pid not in ids: ids.append(pid)
            vars['promised_ids'] = ','.join(ids)
            vars['promise_state'] = 'recorded'
            missing = _update_wrap()
            d['what_to_do_next'] = 'The promise for the ' + phrase + ' IS recorded. If another promise from the confirmed read-back is not recorded yet, call create_promise for it now, without asking again.' + ((' Products with no promise and no note yet: ' + vars['missing_text'] + '. When their discussion is over, call add_note for each.') if missing else '')
        else:
            result['data'] = dict(ok=False, recorded=False, what_to_do_next='The promise for the ' + phrase + ' was NOT recorded. Do not say it is recorded. Call create_promise once more with the same values. If it fails a second time, tell the customer you could not record it and call add_note for it with reason service_error.')
except Exception:
    pass
''')

NOTE_PRE = check_code(r'''
import json
''' + STATE_HELPERS + r'''
try:
    b = config.get('body')
    if isinstance(b, dict):
        info = _load('prod_json', dict())
        facts = info.get('facts') or dict()
        order = info.get('order') or []
        pid = str(b.get('product_id') or '').strip()
        if pid not in facts and len(order) == 1:
            pid = order[0]
        b['product_id'] = pid
        notes = _load('notes_json', dict())
        notes[pid] = str(b.get('reason') or '')
        vars['notes_json'] = json.dumps(notes)
except Exception:
    pass
''')

NOTE_POST = check_code(r'''
import json
''' + STATE_HELPERS + r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        missing = _update_wrap()
        if isinstance(d, dict):
            if missing:
                d['what_to_do_next'] = 'Note saved. Products still without a promise or a note: ' + vars['missing_text'] + '.'
            else:
                d['what_to_do_next'] = 'Note saved. Every product now has a promise or a note.'
except Exception:
    pass
''')

# close_call: the recorded facts decide the outcome where they can (Brief A table + Brief B closing rules).
CLOSE_PRE = check_code(r'''
import json
''' + STATE_HELPERS + r'''
try:
    b = config.get('body')
    if isinstance(b, dict):
        q = str(vars.get('transfer_queue') or '')
        qmap = dict(restructuring='restructuring', general='human', support='support')
        promised = [x for x in str(vars.get('promised_ids') or '').split(',') if x]
        notes = _load('notes_json', dict())
        order = _load('prod_json', dict()).get('order') or []
        verified = vars.get('id_state') == 'verified'
        if q in qmap:
            b['outcome'] = 'transferred'
            b['reason'] = qmap[q]
        elif promised:
            b['outcome'] = 'promise'
        elif vars.get('id_state') == 'failed':
            b['outcome'] = 'not_verified'
            b['reason'] = 'failed'
        elif vars.get('callback_state') == 'booked':
            b['outcome'] = 'not_reached'
            b['reason'] = 'callback'
        elif not verified and b.get('outcome') in ('promise', 'paid', 'no_promise', 'transferred'):
            b['outcome'] = 'not_verified'
            b['reason'] = 'declined'
        elif verified and order and notes:
            reasons = [notes.get(k) for k in order]
            if all(r == 'paid' for r in reasons):
                b['outcome'] = 'paid'
            else:
                first = [r for r in reasons if r and r != 'paid']
                if first:
                    b['outcome'] = 'no_promise'
                    b['reason'] = first[0]
        if b.get('outcome') in ('promise', 'paid'):
            b.pop('reason', None)
        elif not b.get('reason') or '{' in str(b.get('reason')) or b.get('reason') == 'none':
            b.pop('reason', None)
except Exception:
    pass
''')
CLOSE_POST = check_code(r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
            vars['close_state'] = 'done'
            d['what_to_do_next'] = 'The call is closed. Say nothing more.'
except Exception:
    pass
''')


# ---------------------------------------------------------------- tools
OUTCOMES = enum_of("/close_call", "outcome")
QUEUES = enum_of("/transfer_to_agent", "queue")
FIELDS = enum_of("/verify_identity", "field")
NOTE_REASONS = enum_of("/add_note", "reason")

T_VERIFY = api_tool(
    "verify_identity",
    "Check ONE security answer. CALL it every time the customer gives a date of birth or phone digits, one answer per call. "
    "field date_of_birth: answer as YYYY-MM-DD (convert spoken dates; numbers only = day, month, year). field phone_last4: exactly four digits.",
    {"field": {"type": "string", "enum": FIELDS, "description": "Which question was answered: " + " or ".join(FIELDS) + ".", "default": "{{verify_field}}"},
     "answer": {"type": "string", "description": "date_of_birth as YYYY-MM-DD; phone_last4 as four digits.", "default": "{{verify_answer}}"}},
    ["field", "answer"], pre=VERIFY_PRE, post=VERIFY_POST)

T_CLOSE = api_tool(
    "close_call",
    "End the call record. CALL it exactly once, as the very last action, right after you said thank you and goodbye. "
    "Outcomes and reasons: promise (no reason); paid (no reason); transferred: restructuring | human | support; "
    "no_promise: refused | hardship | dispute | service_error; not_verified: failed | declined; "
    "not_reached: callback | no_callback | wrong_number | deceased | unclear.",
    {"outcome": {"type": "string", "enum": OUTCOMES, "description": "One of: " + ", ".join(OUTCOMES) + ".", "default": "{{close_outcome}}"},
     "reason": {"type": "string", "enum": ["refused", "hardship", "dispute", "service_error", "failed", "declined", "callback", "no_callback", "wrong_number", "deceased", "unclear", "restructuring", "human", "support", "none"],
                "description": "Reason that matches the outcome (see the list). Use none for promise and paid.", "default": "{{close_reason}}"}},
    ["outcome", "reason"], pre=CLOSE_PRE, post=CLOSE_POST)

T_TRANSFER = api_tool(
    "transfer_to_agent",
    "Hand the call to a person. CALL it only when a rule says so: queue restructuring for a new payment plan or lower instalments; "
    "queue general when the customer insists on a human after you asked once whether you can help; queue support when a customer in hardship accepts the offer.",
    {"queue": {"type": "string", "enum": QUEUES, "description": "One of: " + ", ".join(QUEUES) + ".", "default": "{{transfer_queue_arg}}"}},
    ["queue"], pre=TRANSFER_PRE, post=TRANSFER_POST)

T_CALLBACK = api_tool(
    "schedule_callback",
    "Book a callback for the customer. CALL it as soon as the person gave a day and time inside the allowed window.",
    {"date": {"type": "string", "description": "YYYY-MM-DD", "default": "{{callback_date}}"},
     "time": {"type": "string", "description": "HH:MM, 24 hour", "default": "{{callback_time}}"}},
    ["date", "time"], pre=CALLBACK_PRE, post=CALLBACK_POST)

T_PROMISE = api_tool(
    "create_promise",
    "Record ONE payment promise for ONE product. CALL it only after you read back all agreed promises and the customer clearly said yes; then call it once per agreed product, one call per message. "
    "Never say a promise is recorded before this tool returned ok true.",
    {"product_id": {"type": "string", "description": "The product_id from the product list, for example p1. Copy it exactly.", "default": "{{promise_product_id}}"},
     "amount": {"type": "number", "description": "The agreed amount, a number such as 455 or 120.5.", "default": "{{promise_amount}}"},
     "date": {"type": "string", "description": "The agreed date as YYYY-MM-DD.", "default": "{{promise_date}}"},
     "date_as_said": {"type": "string", "description": "The same agreed date exactly as you read it back, with weekday, day number and month, for example 'Tuesday 27 October'.", "default": "{{promise_date_as_said}}"}},
    ["product_id", "amount", "date", "date_as_said"], pre=PROMISE_PRE, post=PROMISE_POST)

T_NOTE = api_tool(
    "add_note",
    "Record why ONE product ended without a promise. CALL it once per product that has no recorded promise, only at the end of the call, just before close_call. "
    "Never call it when the call was transferred. Reasons: " + ", ".join(NOTE_REASONS) + ".",
    {"product_id": {"type": "string", "description": "The product_id from the product list, for example p2. Copy it exactly.", "default": "{{note_product_id}}"},
     "reason": {"type": "string", "enum": NOTE_REASONS, "description": "One of: " + ", ".join(NOTE_REASONS) + ".", "default": "{{note_reason}}"}},
    ["product_id", "reason"], pre=NOTE_PRE, post=NOTE_POST)

T_GET_ACCOUNT = {
    "type": "function",
    "config": {"timeoutMs": 12000, "maxRetries": 2},
    "function": {
        "name": "get_account",
        "handler": "__function__:api_call",
        "description": "Get the late products.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "default": BASE + "/get_account"},
            "method": {"type": "string", "default": "POST"},
            "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
            "body": {"type": "object", "properties": {"customer_id": {"type": "string", "default": "{{customer_id}}"}}, "required": []}}},
    },
}


def code_node(name, code, nxt, transitions=None):
    return {
        "name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": nxt,
        "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
        "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                         "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 10000}}}}}],
        "transitions": (transitions or []) + [{"target_node": nxt, "description": "always", "condition": {"operator": "always"}}],
    }


def cond_any(*pairs):
    return {"logic": "or", "conditions": [{"variable": v, "operator": "equals", "operand": o} for v, o in pairs]}


CLOSED = {"target_node": "hangup", "description": "close_call succeeded",
          "condition": cond_any(("close_state", "done"), ("close_call_response.data.ok", "true"), ("close_call_response.data.ok", "True"))}

COMMON = """
GENERAL RULES FOR EVERY TURN:
- After every tool result, either speak to the customer or call the next tool. Never end a turn with nothing. Follow the what_to_do_next line of a tool result.
- Call one tool per message. When a rule says to call a tool, call it; saying it is not enough.
- To end the call: say thank you and goodbye, then call close_call with the outcome and reason. close_call is always the last tool call.
- If asked whether you are a robot or an AI: say you are Freya Bank's digital assistant, then continue.
- If asked "is this a scam?": say they can verify this call by phoning Freya Bank's customer service number, then continue.
- If the customer asks for a human: the first time, ask whether you can help them first. If they insist, call transfer_to_agent with queue general; after it succeeds, say goodbye and call close_call (transferred / human).
- A question you cannot answer from the information you have: say you do not have that information. Never invent figures, dates or reasons.
"""

SYSTEM = (
    "You are Freya Bank's digital assistant, making an outbound phone call to {{title}} {{first_name}} {{last_name}}. "
    "Freya Bank is fictional. Speak English. Keep every turn to one or two short sentences and ask one question at a time. "
    "Address the customer as {{title}} {{last_name}}. The current date and time is {{now}} (today is {{today_text}}); use it for every date, never the real clock. "
    "Never offer a discount, a waiver, an instalment plan or any term that is not given to you. Never claim something was recorded unless a tool result says ok true."
)

OPENING_TASK = """You have just said who you are and asked "Am I speaking with {{title}} {{last_name}}?". Your job here is only to find out who is on the line. No tool call except close_call and transfer_to_agent is allowed here.
Until the identity is verified you must NOT say "collections", "debt", "payment", "account", any product, or why you are calling, to anyone.
- Only "yes", "that's me", "speaking" or the customer's own name confirm. "Hello", "go ahead", "who is this" do not.
- If the person did not confirm (for example "hello?", "who is this?", a robot or scam question): answer any question briefly first, then ask "Am I speaking with {{title}} {{last_name}}?" once more. That is the second ask.
- If after the second ask it is still not clear that this is {{title}} {{last_name}}: thank them, say goodbye and call close_call with outcome not_reached and reason unclear.
- If they say they do not want to talk: ask once more whether you are speaking with {{title}} {{last_name}}. If they refuse a second time, say goodbye and call close_call with not_verified / declined.
""" + COMMON

THIRD_PARTY_TASK = """The person on the line is NOT {{title}} {{last_name}}. Do not say why you are calling and nothing about any account, product, debt or payment, even if they ask or offer to pay. They may not answer security questions.
- If they say the customer has died: say exactly "I am sorry for your loss.", ask nothing else, say goodbye and call close_call with not_reached / deceased.
- If they say this number does not belong to {{title}} {{last_name}} (wrong number, they do not know the person): apologise, say goodbye, call close_call with not_reached / wrong_number.
- Otherwise ask when {{title}} {{last_name}} can be reached. Allowed callback times: {{callback_days_text}}. 10:00 and 19:00 are both allowed.
- When they give a day and time inside that window, call schedule_callback with date YYYY-MM-DD and time HH:MM, then confirm, thank, say goodbye and call close_call with not_reached / callback.
- If the day or time is outside the window (or vague), ask once for another time inside the window, and say which times are possible. If the second answer is also outside or they cannot give one, do not schedule: thank them, say goodbye and call close_call with not_reached / no_callback.
- If they only give a day without a time, ask for the time.
""" + COMMON

IDENTITY_TASK = """The person confirmed they are {{title}} {{last_name}}. You must verify identity with two security questions, one at a time: first the date of birth, then the last four digits of the phone number on file.
Until both are verified you must NOT say "collections", "debt", "payment", any product, or why you are calling.
- Call verify_identity for every answer (field date_of_birth with answer as YYYY-MM-DD; field phone_last4 with four digits). Convert spoken dates yourself. A date said only as numbers is day, then month, then year (for example 03/04/1985 is 1985-04-03).
- If the customer gives only part of an answer, wait for or ask for the rest before calling the tool.
- Follow the what_to_do_next line of each result. A wrong answer may be asked again (ask the SAME question again, not the one that already passed). Never tell the customer the correct answer.
- If the customer will not answer, or asks what the call is about instead of answering: the FIRST time, explain once that these questions protect their account, and ask again. The SECOND time they refuse or ask what it is about: say you cannot continue without verification, thank them, say goodbye and call close_call with not_verified / declined.
""" + COMMON

NEG_COMMON = """
GENERAL RULES FOR EVERY TURN:
- After every tool result, either speak to the customer or call the next tool. Never end a turn with nothing. Follow the what_to_do_next line of a tool result.
- Call exactly one tool per message, never several at once. When a rule says to call a tool, call it; saying it is not enough.
- Do not say goodbye in this step; the goodbye comes after the last tool call.
- If asked whether you are a robot or an AI: say you are Freya Bank's digital assistant, then continue.
- If asked "is this a scam?": say they can verify this call by phoning Freya Bank's customer service number, then continue.
- A question you cannot answer from the information you have: say you do not have that information. Never invent figures, dates or reasons.
"""

NEGOTIATE_TASK = """The customer is verified. You already stated every late product and asked whether they can pay today. Now get payment promises where you can, record them, and note every product that ends without a promise. You cannot close the call from here: closing happens automatically once every product has a recorded promise or a note, or after a transfer.

FACTS (computed for you, trust them; never calculate dates yourself):
- Today: {{today_text}} ({{today_iso}}).
- Late products, in this order:
{{products_text}}
- Persuasion plan per product (attempts are counted per product):
{{attempt_plan_text}}
- Calendar (find the customer's day here, match day of the month and month, and do exactly what its line says for each product):
{{calendar_text}}
- Weekday words ("next X" = following calendar week, "this X" = current week):
{{weekday_words_text}}

ORDER OF THE TALK:
- If the customer agrees to pay everything today: each product is its full past-due amount today.
- If not, go through the products one by one in the order above ({{product_order_text}}). Do not ask about "today" again for each product. A "no" to today with no date and no amount is a flat refusal: for each product you start directly with its attempt 1 from the plan.
- If the customer names one date or plan for all products at once, apply it to each product. If that date is after one product's deadline, that product is recorded on its own deadline instead (say so in the read-back); the other products keep the customer's date.
- When every product has an agreed promise or has ended without one, read back ALL agreed promises together in one message (product, amount and date for each) and ask "Do you confirm?". Then call create_promise once per agreed product, one call per message.

AMOUNTS (per product):
- You propose every amount. Never ask "how much can you pay?". Start with the full past-due amount.
- If the customer says the full amount is too much: offer that product's floor ONCE and say that the rest stays overdue. After that, never say the floor number again as an offer for that product: a later attempt only proposes a new date for "that payment", for example "Could you make that payment on Friday ... instead?". The read-back after a yes may name it. If they refuse the floor, that is a flat refusal (uses a persuasion attempt).
- An amount the customer proposes from the floor up to the full amount (both included): accept it.
- Below the floor: say that amount cannot be recorded and offer the floor once. If they do not accept, that is a flat refusal.

DATES (per product):
- A promise date must be a business day from today up to that product's deadline. Use the calendar.
- A weekend day or holiday on or before the deadline: offer the next business day (the calendar line names it).
- A date after the deadline: say the latest date you can record is the deadline and offer it. If they refuse the deadline, that is a flat refusal.
- A vague period ("next week", "end of the month", "when my salary comes"): ask once for the exact day. If they still give none, propose the deadline.
- A date or an amount the customer proposes is never a refusal.

PERSUASION (per product):
- A flat refusal or a non-answer uses one persuasion attempt for the product being discussed. Follow the plan above. Never go back to the full amount after the customer said it is too much. When attempt 1 follows a floor offer you already made, only propose the new date, do not name the floor as a new offer.
- When a product's attempts are used up and refused: stop for that product, do not repeat any refused offer, and move on to the next product. That product will get a note with reason refused.
- If the customer says twice that they do not want to talk: stop; every product without a promise gets a note with reason refused.
- If the customer asks for a human: the first time, ask whether you can help them first. If they insist, call transfer_to_agent with queue general.

CONFIRM AND RECORD:
- Call create_promise only after a clear yes to the read-back. Pass product_id exactly as listed, amount as a number, date as YYYY-MM-DD, and date_as_said as you read it back (for example "Tuesday 27 October").
- If they change a date or amount at the read-back, check it against the rules and read it back again.
- Say promises are recorded only after create_promise returned ok true. Then say exactly: "You will receive a text message confirming this promise." Follow what_to_do_next for failures (retry once; after a second failure say you could not record that promise; that product gets a note with reason service_error).
- A recorded promise cannot be changed or cancelled in this call: if asked, say they can change it in the mobile app.

NOTES:
- Call add_note once for each product that has no recorded promise, with its reason: refused, hardship, dispute, paid or service_error. Do this only when the whole discussion is over: after the promises are recorded, or right away when no promise was agreed at all. This also applies when no product gets a promise.
- Never call add_note before or after a transfer (restructuring, support or human).
- If create_promise returns an error, the promise was NOT recorded: call it once more with the same values. After a second error, tell the customer you could not record that promise; that product gets a note with reason service_error.

OTHER SITUATIONS (these take priority over persuasion):
- Illness, a death in the family or job loss: say one short sentence of sympathy, make NO persuasion attempt, and offer to connect them with the customer support team. If they accept: call transfer_to_agent with queue support, no notes. If they decline: each product without a promise gets a note with reason hardship. If they themselves name a date or amount, handle it as a promise under the rules above.
- "I already paid" (this past-due amount) for a product: say payments can take one business day to appear and take no promise for that product (note reason paid). Continue with the other products; if none is left, add the notes.
- "This debt is not mine", "I never had this product", or the product was closed or paid off in the past: do not argue, take no promise for that product (note reason dispute). Continue with the other products.
- A request for a new payment plan or lower instalments: do not describe any plan; call transfer_to_agent with queue restructuring right away (promises agreed but not yet recorded are NOT recorded), no notes.
""" + NEG_COMMON

CLOSING_TASK = """The talk is over. No more offers or questions. Look at the tool results in this call to see what was recorded.
Do these in ONE message, then call close_call:
- If at least one promise was recorded in this call and you have not yet said so, say the promises are recorded and say exactly: "You will receive a text message confirming this promise."
- If the call was transferred, say a colleague will take over.
- Thank the customer and say goodbye.
Then call close_call. Outcome: transferred with its reason if the call was transferred; else promise if at least one promise was recorded; else paid if every product was noted paid; else no_promise with the reason of the first product (in get_account order) whose note is not paid.
After close_call, say nothing more. Never say a promise is recorded unless create_promise returned ok true.
"""

ADD_NOTES_TASK = """Before the call can end, each product without a promise needs a note. Products still missing one: {{missing_text}}.
Call add_note for the first of them now, with the reason that fits the conversation: refused (would not pay or refused the offers), hardship (illness, death in the family or job loss), dispute (says the debt is not theirs or the product was closed), paid (says they already paid this amount), service_error (create_promise failed twice). One add_note per message. Do not ask the customer anything.
"""

ACCOUNT_ERROR_TASK = """The customer is verified, but the account details could not be loaded. Apologise, say you cannot access the account details right now and that the bank will contact them again. Do not invent any amount. Thank them, say goodbye and call close_call with outcome no_promise and reason service_error.
""" + COMMON


def conv(name, task, tools, transitions, on_enter=None, extraction=None, first_only=True):
    n = {"name": name, "node_type": "conversation", "task_message": task, "tools": tools,
         "transitions": transitions, "max_node_turns": 60}
    if on_enter: n["on_enter"] = on_enter
    n["on_enter_first_entry_only"] = first_only
    if extraction: n["extraction_schema"] = extraction
    return n


nodes = {}
nodes["setup"] = code_node("setup", SETUP_CODE, "opening")
nodes["opening"] = conv(
    "opening", OPENING_TASK, [T_CLOSE, T_TRANSFER],
    [CLOSED,
     {"target_node": "identity", "description": "The person confirmed they are the customer",
      "condition": cond_any(("speaker", "confirmed"))},
     {"target_node": "third_party", "description": "Someone else answered",
      "condition": cond_any(("speaker", "someone_else"))}],
    on_enter={"type": "tts", "text": "Hello, I am a digital assistant calling from Freya Bank. Please note that we keep a recording of this call. Am I speaking with {{title}} {{last_name}}?"},
    extraction=[{"name": "speaker", "type": "string", "enum_values": ["confirmed", "someone_else"], "min_confidence": 0.7,
                 "description": "Who answered, judged from the person's LATEST message. confirmed: they clearly confirm they are {{title}} {{first_name}} {{last_name}} ('yes', 'that's me', 'speaking', or say that name as their own). "
                                "someone_else: they say they are a different person (relative, colleague, the customer is not there or not available, wrong number, or the customer has died). "
                                "Leave empty for greetings, 'who is this', 'go ahead', questions, refusals or anything unclear."}])
nodes["third_party"] = conv("third_party", THIRD_PARTY_TASK, [T_CALLBACK, T_CLOSE], [CLOSED])
nodes["identity"] = conv(
    "identity", IDENTITY_TASK, [T_VERIFY, T_CLOSE, T_TRANSFER],
    [CLOSED,
     {"target_node": "load_account", "description": "Both security answers verified",
      "condition": cond_any(("id_state", "verified"), ("verify_identity_response.data.all_verified", "true"), ("verify_identity_response.data.all_verified", "True"))},
     {"target_node": "id_failed", "description": "Three wrong answers",
      "condition": cond_any(("id_state", "failed"), ("verify_identity_response.data.wrong_answers_left", "0"))}],
    on_enter={"type": "tts", "text": "Thank you. Before we continue, I need to ask you two security questions. First, what is your date of birth?"})
nodes["id_failed"] = {
    "name": "id_failed", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "hangup",
    "on_enter": {"type": "tts", "text": "I am sorry, I could not verify your identity, so I cannot continue this call. Please use the Freya Bank mobile app or visit a branch. Thank you for your time, goodbye."},
    "disable_inactivity_monitor": True,
    "pre_actions": [{
        "type": "function", "config": {"timeoutMs": 12000, "maxRetries": 1},
        "function": {"name": "close_call", "handler": "__function__:api_call", "description": "Close the call.",
                     "parameters": {"type": "object", "properties": {
                         "url": {"type": "string", "default": BASE + "/close_call"},
                         "method": {"type": "string", "default": "POST"},
                         "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                         "body": {"type": "object", "properties": {
                             "customer_id": {"type": "string", "default": "{{customer_id}}"},
                             "outcome": {"type": "string", "default": "not_verified"},
                             "reason": {"type": "string", "default": "failed"}}, "required": []}}}}}],
    "transitions": [{"target_node": "hangup", "description": "always", "condition": {"operator": "always"}}],
}
nodes["load_account"] = {
    "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "prepare_account",
    "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
    "pre_actions": [T_GET_ACCOUNT],
    "response_mapping": [{"path": "data.products", "variable": "products"}],
    "transitions": [{"target_node": "prepare_account", "description": "always", "condition": {"operator": "always"}}],
}
nodes["prepare_account"] = code_node(
    "prepare_account", ACCOUNT_CODE, "account_error",
    [{"target_node": "negotiate", "description": "account facts ready", "condition": cond_any(("acct_state", "ok"))}])
TO_CLOSING = [
    {"target_node": "closing", "description": "The call was transferred",
     "condition": {"logic": "or", "conditions": [{"variable": "transfer_queue", "operator": "is_set"}]}},
    {"target_node": "closing", "description": "Every product has a promise or a note",
     "condition": cond_any(("wrap_state", "ready"))},
]
nodes["negotiate"] = conv(
    "negotiate", NEGOTIATE_TASK, [T_PROMISE, T_NOTE, T_TRANSFER], TO_CLOSING + [
        {"target_node": "add_notes", "description": "The customer ends the conversation",
         "condition": {"operator": "matches_intent", "description": "The customer says goodbye or hangs up, and there is nothing left to discuss"}}],
    on_enter={"type": "tts", "text": "Thank you, {{title}} {{last_name}}, you are verified. {{statement_text}}"})
nodes["negotiate"]["max_turn_transition"] = "add_notes"
nodes["add_notes"] = conv("add_notes", ADD_NOTES_TASK, [T_NOTE], TO_CLOSING, on_enter={"type": "llm"}, first_only=False)
nodes["add_notes"]["max_node_turns"] = 4
nodes["add_notes"]["max_turn_transition"] = "closing"
nodes["closing"] = conv("closing", CLOSING_TASK, [T_CLOSE], [CLOSED], on_enter={"type": "llm"})
nodes["account_error"] = conv("account_error", ACCOUNT_ERROR_TASK, [T_CLOSE], [CLOSED])
nodes["hangup"] = {
    "name": "hangup", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
    "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
                 "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}},
}

wf = {
    "initial_node": "setup",
    "system_prompt": SYSTEM,
    "nodes": nodes,
    "global_nodes": {},
    "test_variables": {"customer_id": "c_test", "first_name": "Sofia", "last_name": "Almeida", "title": "Ms", "now": "2026-10-14T11:00"},
}
out = ROOT / "out/brief-b.workflow.json"
json.dump(wf, open(out, "w"), indent=1)
print("wrote", out)
