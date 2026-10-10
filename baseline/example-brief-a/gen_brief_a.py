"""Generate out/brief-a.workflow.json from Brief A and tools/openapi.json."""
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

# ---------------------------------------------------------------- code: account facts after get_account
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
try:
    prods = find_products()
    p = prods[0]
    today = datetime.date.fromisoformat(str(vars.get('now'))[:10])
    ptype = str(p.get('type'))
    past_due = float(p.get('past_due'))
    days_late = int(float(p.get('days_late')))
    if ptype == 'credit_card':
        floor = float(p.get('minimum_payment'))
        phrase = 'credit card ending ' + str(p.get('card_last4') or '')
    else:
        floor = float(p.get('instalment_amount'))
        phrase = 'personal loan' if ptype == 'personal_loan' else 'car loan'
    early = days_late <= 7
    n = 12 if early else 7
    d = today; c = 0
    while c < n:
        d = d + datetime.timedelta(days=1)
        if bd(d): c += 1
    deadline = d
    a1 = datetime.date.fromisoformat(str(vars.get('attempt1_iso')))
    allowed = []
    d = today
    while d <= deadline:
        if bd(d): allowed.append(d)
        d = d + datetime.timedelta(days=1)
    cal = []
    d = today
    end = deadline + datetime.timedelta(days=21)
    while d <= end:
        nxt = d
        while not bd(nxt): nxt = nxt + datetime.timedelta(days=1)
        label = say(d) + ' (' + d.isoformat() + ')' + (' TODAY' if d == today else '')
        if d > deadline:
            act = 'AFTER THE DEADLINE -> say the latest date you can record is ' + say(deadline) + ' and offer it'
        elif bd(d):
            act = 'allowed business day -> can be recorded'
        else:
            why = 'bank holiday' if d.isoformat() in HOL else 'weekend'
            if nxt <= deadline:
                act = why + ', before the deadline -> offer the next business day ' + say(nxt) + ' instead'
            else:
                act = why + ' -> offer the deadline ' + say(deadline) + ' instead'
        cal.append(label + ': ' + act)
        d = d + datetime.timedelta(days=1)
    vars['product_id'] = str(p.get('product_id'))
    vars['product_type'] = ptype
    vars['product_phrase'] = phrase
    vars['past_due_value'] = past_due
    vars['past_due_text'] = money(past_due)
    vars['floor_value'] = floor
    vars['floor_text'] = money(floor)
    vars['floor_name'] = 'minimum payment' if ptype == 'credit_card' else 'monthly instalment'
    vars['days_late'] = days_late
    vars['band'] = 'early' if early else 'late'
    vars['attempts_allowed'] = 1 if early else 2
    vars['deadline_iso'] = deadline.isoformat()
    vars['deadline_text'] = say(deadline)
    vars['attempt1_text'] = say(a1)
    vars['attempt1_iso'] = a1.isoformat()
    vars['allowed_dates_iso'] = ','.join(x.isoformat() for x in allowed)
    vars['allowed_dates_text'] = '; '.join(say(x) + ' (' + x.isoformat() + ')' for x in allowed)
    vars['calendar_text'] = '\n'.join(cal)
    if early:
        vars['attempt_plan_text'] = 'This customer is in the EARLY band: exactly ONE persuasion attempt is allowed. Attempt 1: propose the payment on ' + say(a1) + '. After attempt 1 is refused, stop and close as no_promise / refused.'
    else:
        vars['attempt_plan_text'] = 'This customer is in the LATE band: TWO persuasion attempts are allowed. Attempt 1: propose the payment on ' + say(a1) + '. Attempt 2: propose the floor amount ' + money(floor) + ' on the deadline ' + say(deadline) + ' (say that the rest stays overdue). After attempt 2 is refused, stop and close as no_promise / refused.'
    vars['acct_state'] = 'ok'
except Exception as e:
    vars['acct_state'] = 'error'
    vars['acct_error'] = str(e)[:200]
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

PROMISE_POST = check_code(r'''
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
            vars['promise_state'] = 'recorded'
            d['what_to_do_next'] = 'The promise IS recorded. Say that it is recorded, then say exactly: "You will receive a text message confirming this promise." Then thank the customer, say goodbye, and call close_call with outcome promise.'
        else:
            n = int(vars.get('promise_failures') or 0) + 1
            vars['promise_failures'] = n
            if n < 2:
                result['data'] = dict(ok=False, recorded=False, what_to_do_next='The promise was NOT recorded. Do not say it is recorded. Call create_promise once more right now with exactly the same amount and date.')
            else:
                vars['promise_state'] = 'failed'
                result['data'] = dict(ok=False, recorded=False, what_to_do_next='The promise was NOT recorded, for the second time. Tell the customer you could not record the promise. Do not say it is recorded. Thank them, say goodbye, then call close_call with outcome no_promise and reason service_error.')
except Exception:
    pass
''')

# close_call: the recorded facts decide the outcome where they can.
CLOSE_PRE = check_code(r'''
try:
    b = config.get('body')
    if isinstance(b, dict):
        q = str(vars.get('transfer_queue') or '')
        qmap = dict(restructuring='restructuring', general='human', support='support')
        if q in qmap:
            b['outcome'] = 'transferred'
            b['reason'] = qmap[q]
        elif vars.get('promise_state') == 'recorded':
            b['outcome'] = 'promise'
        elif vars.get('promise_state') == 'failed':
            b['outcome'] = 'no_promise'
            b['reason'] = 'service_error'
        elif vars.get('id_state') == 'failed':
            b['outcome'] = 'not_verified'
            b['reason'] = 'failed'
        elif vars.get('callback_state') == 'booked':
            b['outcome'] = 'not_reached'
            b['reason'] = 'callback'
        elif vars.get('id_state') != 'verified' and b.get('outcome') in ('promise', 'paid', 'no_promise', 'transferred'):
            b['outcome'] = 'not_verified'
            b['reason'] = 'declined'
        if b.get('outcome') in ('promise', 'paid'):
            b.pop('reason', None)
        elif not b.get('reason') or '{' in str(b.get('reason')):
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
        else:
            result['data'] = dict(ok=False, what_to_do_next='close_call failed. Call close_call again with a valid outcome and reason from the table.')
except Exception:
    pass
''')

# ---------------------------------------------------------------- tools
OUTCOMES = enum_of("/close_call", "outcome")
QUEUES = enum_of("/transfer_to_agent", "queue")
FIELDS = enum_of("/verify_identity", "field")

T_VERIFY = api_tool(
    "verify_identity",
    "Check ONE security answer. CALL it every time the customer gives a date of birth or phone digits, one answer per call. "
    "field date_of_birth: answer as YYYY-MM-DD (convert spoken dates; numbers only = day, month, year). field phone_last4: exactly four digits.",
    {"field": {"type": "string", "enum": FIELDS, "description": "Which question was answered: " + " or ".join(FIELDS) + ".", "default": "{{verify_field}}"},
     "answer": {"type": "string", "description": "date_of_birth as YYYY-MM-DD; phone_last4 as four digits.", "default": "{{verify_answer}}"}},
    ["field", "answer"], pre=VERIFY_PRE, post=VERIFY_POST)

T_CLOSE = api_tool(
    "close_call",
    "End the call record. CALL it exactly once, as the very last action, right after you said thank you and goodbye in the same message. "
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
    "Record the payment promise. CALL it only after you read back product, amount and date and the customer clearly said yes. "
    "Never say the promise is recorded before this tool returned ok true.",
    {"amount": {"type": "number", "description": "The agreed amount, a number such as 455 or 120.5.", "default": "{{promise_amount}}"},
     "date": {"type": "string", "description": "The agreed date as YYYY-MM-DD.", "default": "{{promise_date}}"},
     "product_id": {"type": "string", "default": "{{product_id}}"}},
    ["amount", "date"], post=PROMISE_POST)

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
- To end the call: in one message say thank you and goodbye, then call close_call with the outcome and reason. close_call is always the last thing you do.
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
Until the identity is verified you must NOT say "collections", "debt", "payment", "account", the product, or why you are calling, to anyone.
- Only "yes", "that's me", "speaking" or the customer's own name confirm. "Hello", "go ahead", "who is this" do not.
- If the person did not confirm (for example "hello?", "who is this?", a robot or scam question): answer any question briefly first, then ask "Am I speaking with {{title}} {{last_name}}?" once more. That is the second ask.
- If after the second ask it is still not clear that this is {{title}} {{last_name}}: thank them, say goodbye and call close_call with outcome not_reached and reason unclear.
- If they say they do not want to talk: ask once more whether you are speaking with {{title}} {{last_name}}. If they refuse a second time, say goodbye and call close_call with not_verified / declined.
""" + COMMON

THIRD_PARTY_TASK = """The person on the line is NOT {{title}} {{last_name}}. Do not say why you are calling and nothing about any account, debt or payment, even if they ask or offer to pay. They may not answer security questions.
- If they say the customer has died: say exactly "I am sorry for your loss.", ask nothing else, say goodbye and call close_call with not_reached / deceased.
- If they say this number does not belong to {{title}} {{last_name}} (wrong number, they do not know the person): apologise, say goodbye, call close_call with not_reached / wrong_number.
- Otherwise ask when {{title}} {{last_name}} can be reached. Allowed callback times: {{callback_days_text}}. 10:00 and 19:00 are both allowed.
- When they give a day and time inside that window, call schedule_callback with date YYYY-MM-DD and time HH:MM, then confirm, thank, say goodbye and call close_call with not_reached / callback.
- If the day or time is outside the window (or vague), ask once for another time inside the window, and say which times are possible. If the second answer is also outside or they cannot give one, do not schedule: thank them, say goodbye and call close_call with not_reached / no_callback.
- If they only give a day without a time, ask for the time.
""" + COMMON

IDENTITY_TASK = """The person confirmed they are {{title}} {{last_name}}. You must verify identity with two security questions, one at a time: first the date of birth, then the last four digits of the phone number on file.
Until both are verified you must NOT say "collections", "debt", "payment", the product, or why you are calling.
- Call verify_identity for every answer (field date_of_birth with answer as YYYY-MM-DD; field phone_last4 with four digits). Convert spoken dates yourself. A date said only as numbers is day, then month, then year (for example 03/04/1985 is 1985-04-03).
- If the customer gives only part of an answer, wait for or ask for the rest before calling the tool.
- Follow the what_to_do_next line of each result. A wrong answer may be asked again. Never tell the customer the correct answer.
- If the customer will not answer, or asks what the call is about instead of answering: the FIRST time, explain once that these questions protect their account, and ask again. The SECOND time they refuse or ask what it is about: say you cannot continue without verification, thank them, say goodbye and call close_call with not_verified / declined.
""" + COMMON

NEGOTIATE_TASK = """The customer is verified. You already told them the debt and asked "Can you make this payment today?". Now get a payment promise if you can, and close the call with the right outcome.

FACTS (computed for you, trust them; do not calculate dates yourself):
- Today: {{today_text}} ({{today_iso}}).
- Product: {{product_phrase}}. Full past-due amount: {{past_due_text}}. Days late: {{days_late}}.
- Floor amount ({{floor_name}}), the lowest amount you can record: {{floor_text}}.
- Deadline, the latest date you can record: {{deadline_text}} ({{deadline_iso}}).
- {{attempt_plan_text}}
- Dates you may record (business days from today to the deadline): {{allowed_dates_text}}
- Calendar:
{{calendar_text}}
- Weekday words ("next X" = following calendar week, "this X" = current week):
{{weekday_words_text}}

AMOUNTS:
- You propose every amount. Never ask "how much can you pay?". Start with the full past-due amount {{past_due_text}}.
- If the customer says the full amount is too much: offer the floor {{floor_text}} ONCE, and say that the rest stays overdue. If they refuse the floor, that is a flat refusal (uses a persuasion attempt).
- If the customer proposes an amount from {{floor_text}} up to {{past_due_text}} (both included): accept it.
- If they propose less than {{floor_text}}: say that amount cannot be recorded and offer the floor {{floor_text}} once. If they do not accept, that is a flat refusal.

DATES:
- Whenever the customer names a day, find that exact day in the calendar above (match the day of the month and the month) and do exactly what its line says. Never decide from memory whether a date is a holiday or after the deadline.
- A promise date must be one of the allowed dates above.
- A weekend day or holiday on or before the deadline: offer the next business day (the calendar line names it).
- A date after the deadline: say the latest date you can record is {{deadline_text}} and offer it. If they refuse the deadline, that is a flat refusal.
- A vague period ("next week", "end of the month", "when my salary comes"): ask once for the exact day. If they still give none, propose the deadline {{deadline_text}}.
- A date or an amount the customer proposes is never a refusal.

PERSUASION:
- A "no" to paying today with no date and no amount, a flat refusal or a non-answer uses one persuasion attempt. Before each reply count from the conversation which attempts you already made.
- Attempt 1 date: {{attempt1_text}}. Attempt 1 amount: if the customer has said at ANY earlier point that the full amount is too much (or you already offered the floor), attempt 1 is the floor {{floor_text}} on {{attempt1_text}} (say the rest stays overdue). Only otherwise is it the full amount {{past_due_text}}. Never go back to the full amount after the customer said it is too much.
- The floor is OFFERED only once (rule: offer the floor once). So when attempt 1 follows a floor offer you already made, do not name the floor amount again as a new offer: only propose the new date, for example "Could you make that payment on {{attempt1_text}} instead?".
- Example: full amount too much -> you offer the floor {{floor_text}} today, saying the rest stays overdue -> "I can't pay that today" (a no with no date and no amount) -> attempt 1: "Could you make that payment on {{attempt1_text}} instead?" -> yes -> read back {{floor_text}} on {{attempt1_text}}.
- {{attempt_plan_text}}
- When the allowed attempts are used up and refused, stop: do not repeat any offer they refused. Thank them, say goodbye and call close_call with no_promise / refused.
- If the customer says twice that they do not want to talk: say goodbye and close_call with no_promise / refused.

CONFIRM AND RECORD:
- When an amount and a date are agreed, read back: the product ({{product_phrase}}), the amount and the date, and ask "Do you confirm?". Call create_promise only after a clear yes, with amount as a number and date as YYYY-MM-DD.
- If they change the date or amount at this step, check it against the rules above and read it back again.
- Say the promise is recorded only after create_promise returned ok true. Then say: "You will receive a text message confirming this promise." Follow what_to_do_next for failures (retry once, then say you could not record it, close no_promise / service_error).
- Only one promise. A recorded promise cannot be changed or cancelled in this call: if asked, say they can change it in the mobile app.

OTHER SITUATIONS (these take priority over persuasion):
- Illness, a death in the family or job loss: say one short sentence of sympathy, make NO persuasion attempt, and offer to connect them with the customer support team. If they accept: call transfer_to_agent with queue support, then goodbye and close_call (transferred / support). If they decline: goodbye and close_call with no_promise / hardship. If they themselves name a date or amount, handle it as a promise under the rules above.
- "I already paid": say payments can take one business day to appear, take no promise, thank, goodbye, close_call with outcome paid.
- "This debt is not mine", "I never had this product", or the product was closed or paid off in the past: do not argue, take no promise, goodbye, close_call with no_promise / dispute.
- A request for a new payment plan or lower instalments: do not describe any plan; call transfer_to_agent with queue restructuring, then goodbye and close_call (transferred / restructuring).
""" + COMMON

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
    on_enter={"type": "tts", "text": "Hello, I am a digital assistant calling from Freya Bank. This call is recorded. Am I speaking with {{title}} {{last_name}}?"},
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
nodes["negotiate"] = conv(
    "negotiate", NEGOTIATE_TASK, [T_PROMISE, T_TRANSFER, T_CLOSE], [CLOSED],
    on_enter={"type": "tts", "text": "Thank you, {{title}} {{last_name}}, you are verified. I am calling from the collections team about a late payment on your {{product_phrase}}. The past-due amount is {{past_due_text}}, and it is {{days_late}} days late. Can you make this payment today?"})
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
    "test_variables": {"customer_id": "c_test", "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"},
}
out = ROOT / "out/brief-a.workflow.json"
json.dump(wf, open(out, "w"), indent=1)
print("wrote", out)
