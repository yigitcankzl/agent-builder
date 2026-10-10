"""End to end: bridge-v2 (ae1890b) policies -> gen-reducer. Read-only copies in tests/generated/e2e8.
mut-03 percent floor, Osprey (floor/acceptance/date rules), Kestrel (hooks/identity formats), packed hub size.
The kit sequences and personas run on the same files with POLICY_DIR=tests/generated/e2e8.

    python3 tests/test_reducer_e2e8.py
"""
import base64, json, os, sys, zlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R

D = os.path.join(ROOT, "tests", "generated", "e2e8")
load = lambda n: json.load(open(os.path.join(D, n + ".reducer_policy.json")))
CV = dict(customer_id="c_e", first_name="Ann", last_name="Lee", title="Ms")
n = [0]


def check(c, m):
    if not c:
        raise AssertionError(m)


class Call:
    def __init__(self, pol, now, acc, id_answers):
        self.pol, self.now, self.cv = pol, now, dict(CV, now=now)
        self.st = R.init_state(pol, self.cv)
        self.say("kind=who;also=none;st=complete;prod=;who=self;party=")
        qs = pol["identity"]["questions"]
        for k, q in enumerate(qs):
            self.say("kind=identity;also=none;st=complete;prod=;field=%s;ans=%s" % (q["field"], id_answers[k]))
            self.tool(dict(verified=True, all_verified=k == len(qs) - 1, wrong_answers_left=3))
        self.a = self.tool(dict(products=acc))

    def say(self, body):
        n[0] += 1
        self.st["tok"] = "kx" + "abcdefghjk"[n[0] % 10] * 2 + "abcdefghjk"[(n[0] // 10) % 10] * 2
        e = R.parse_event("n=" + self.st["tok"] + ";src=user;" + body, self.st, R.CONTRACT_TOPICS)
        tok = self.st["tok"]
        self.st, self.a = R.step(self.pol, self.st, e, None, self.now, self.cv)
        self.st["last_tok"] = tok
        return self.a

    def tool(self, data):
        p = self.st["pending"]
        te = dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"], status_code=200, ok="true", data=data)
        self.st, self.a = R.step(self.pol, self.st, None, te, self.now, self.cv)
        return self.a

    def date(self, d, m, rel=""):
        return self.say("kind=date;also=none;st=complete;prod=;rel=%s;d=%s;m=%s;wd=;wk=none;vague=no" % (rel, d, m))


def card(past_due, days_late=10, **kw):
    return [dict(product_id="p1", type="credit_card", past_due=past_due, days_late=days_late, minimum_payment=kw.get("mp", 10.0))]


def mut03():
    pol = load("mut-03")
    for pd, exp in ((540.0, 162.0), (333.33, 100.0), (100.0, 30.0)):
        check(R._floor(pol, card(pd)[0]) == exp, f"mut-03 floor of {pd}: {R._floor(pol, card(pd)[0])} != {exp}")
    c = Call(pol, "2026-10-14T11:00", card(540.0), ["1990-01-01", "1234"])
    a = c.say("kind=reject;also=none;st=complete;prod=;why=too_much")
    check("162.00" in a["text"] and "overdue" in a["text"], f"mut-03 too much -> 162.00: {a}")
    return "floor 30% up to unit: 540->162, 333.33->100, 100->30; too much offers 162.00"


def osprey():
    pol = load("snippet-floor-dates")
    ids = ["1990-01-01", "1234"]
    for pd, exp in ((100.0, 25.0), (300.0, 60.0), (333.0, 67.0), (20.0, 20.0)):
        check(R._floor(pol, card(pd)[0]) == exp, f"osprey floor of {pd}: {R._floor(pol, card(pd)[0])} != {exp}")
    now = "2026-10-14T11:00"          # Wednesday; deadline 10 calendar days = Saturday 24 -> Friday 23 October

    def after_no(acc=None):
        c = Call(pol, now, acc or card(300.0), ids)
        c.say("kind=no;also=none;st=complete;prod=")
        return c
    out = []
    c = after_no(); a = c.say("kind=amount;also=none;st=complete;prod=;amt=50")
    check(c.st["offer"]["amount"] == 50.0 and "cannot" not in a["text"], f"min_x 40: 50 accepted: {a}")
    c = after_no(); a = c.say("kind=amount;also=none;st=complete;prod=;amt=30")
    check(a["text"].startswith("I cannot record 30.00.") and c.st["offer"]["amount"] == 60.0, f"below 40 -> the floor 60: {a}")
    out.append("min_x 40: 50 accepted; 30 -> 'I cannot record 30.00.' + floor 60.00")
    c = after_no(); a = c.date("", "", rel="today")
    check(a["text"] == "I can only record a date from tomorrow on. Which day would work?", f"today: {a}")
    c = after_no(); a = c.date(17, 10)
    check(a["text"] == "We cannot take a payment on a weekend. Which weekday would suit you?" and c.st["offer"] is None, f"weekend: {a}")
    c = after_no(); a = c.date(30, 10)
    check(a["text"] == "I cannot record a date after Friday 23 October. Which other date would work?", f"after deadline: {a}")
    c = after_no(); a = c.date(10, 10)
    check(a["text"].startswith("That date has passed."), f"past: {a}")
    c = after_no(); a = c.date(22, 10)
    check(c.st["q"] == "readback" and "22 October" in a["text"], f"a good day: {a}")
    for d, m in [(x, 10) for x in range(15, 32)] + [(x, 11) for x in range(1, 31)]:
        c = after_no(); a = c.date(d, m)
        check("passed" not in a.get("text", ""), f"future {d}/{m} said passed: {a}")
    c = Call(pol, "2026-12-22T11:00", card(300.0), ids)      # Tuesday; deadline 1 Jan (holiday) -> 31 December
    c.say("kind=no;also=none;st=complete;prod=")
    a = c.date(25, 12)
    check("Monday 28 December" in a["text"] and c.st["offer"]["date"] == "2026-12-28", f"holiday shift: {a}")
    out.append("dates: today/weekend refused with the brief's lines, after-deadline refused (default), past refused, "
               "holiday 25 Dec -> Monday 28 December, 47 future days never 'passed'")
    return "; ".join(out)


def kestrel():
    pol = load("snippet-hooks-id")
    c = Call(pol, "2026-10-14T11:00", card(400.0, 10, mp=40.0), ["  ahmet ", "sw1a  1aa"])
    check("_hooks_said" in c.st and not any(x.startswith("no_promise_confirm") for x in c.st.get("_hook_skip") or []), c.st.get("_hook_skip"))
    txt = c.a["text"]
    check("Interest continues to accrue" in txt and txt.endswith("?"), f"after_debt: {txt}")
    for b in ("kind=no;also=none;st=complete;prod=", "kind=reject;also=none;st=complete;prod=;why=flat"):
        a = c.say(b)
    check(a["type"] == "say_exact" and "not making a payment promise today" in a["text"], f"the brief's no-promise question first: {a}")
    a = c.say("kind=yes;also=none;st=complete;prod=")
    while a["type"] == "call_tool":
        a = c.tool(dict(ok=True))
    check(a["type"] == "close" and "Kestrel Savings" in a["farewell"] and "recoveries" not in a["farewell"], f"standard band close: {a}")
    c = Call(pol, "2026-10-14T11:00", card(400.0, 45, mp=40.0), ["ahmet", "sw1a 1aa"])
    for b in ("kind=no;also=none;st=complete;prod=", "kind=reject;also=none;st=complete;prod=;why=flat"):
        a = c.say(b)
    check("not making a payment promise today" in a.get("text", ""), f"serious band: the question: {a}")
    q = a["text"]
    a = c.say("kind=yes;also=none;st=complete;prod=")
    while a["type"] == "call_tool":
        a = c.tool(dict(ok=True))
    check(a["type"] == "close" and (q + a["farewell"]).count("recoveries team") == 1, f"serious band: the warning once: {q} / {a}")
    return "hooks at their points once; the on_no_promise question asked before the close; band condition; Ahmet / SW1A 1AA"


def sizes():
    out = dict()
    for f in sorted(os.listdir(D)):
        src = R.hub_source(json.load(open(os.path.join(D, f))))
        packed = len(base64.b64encode(zlib.compress(src.encode(), 9))) + 220
        check(packed <= 45000, f"{f}: packed {packed} > 45000")
        out[f.split(".")[0]] = "%.1f KB" % (packed / 1000.0)
    return out


if __name__ == "__main__":
    print("3 mut-03:", mut03())
    print("4 osprey:", osprey())
    print("5 kestrel:", kestrel())
    print("6 packed hub:", sizes())
