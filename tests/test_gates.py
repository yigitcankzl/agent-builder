"""Code-node gates (builder/engine/gates.py) on Brief A, raw-4 (per-band deadline rule) and raw-5 (route_by_type):
holiday, after-deadline, past, floor, extra offer, stale yes. Every check also runs once through the shipped,
packed code-node string.

    python3 tests/test_gates.py
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import policy_bridge as B
from builder.engine import gates as G
from tests.test_reducer_sequences import POL

NOW = "2026-10-14T11:00"
OAS = os.path.join(ROOT, "tools/openapi.json")
FIX = os.path.join(ROOT, "tests/fixtures/brief_reading")


def check(c, m):
    if not c:
        raise AssertionError(m)


def bridged(n):
    d = os.path.join(FIX, "raw-%d-single" % n)
    rp, _ = B.to_reducer(json.load(open(d + "/extracted.json")), OAS, brief_text=open(d + "/brief.md").read())
    return rp


SRC = dict()


def run(pol, name, vars, **inp):
    """One gate run: in-process, and the same through the packed code-node string; both must agree."""
    v1 = dict(vars, **inp)
    getattr(G, name)(v1, pol)
    key = (id(pol), name)
    if key not in SRC:
        SRC[key] = G.gate_source(pol, name)
    v2 = dict(vars, **inp)
    exec(SRC[key], dict(vars=v2))
    out = [k for k in G.GATE_OUT if k != 'gate_error']
    check([v1.get(k) for k in out] == [v2.get(k) for k in out], "%s: packed differs: %s / %s" % (name, v1, v2))
    check(v1.get('gate_status') != 'error', "%s error: %s" % (name, v1.get('gate_error')))
    return v1


def base(acc):
    return dict(now=NOW, gate_account=json.dumps(dict(products=acc)))


def brief_a():
    pol = POL["A"]
    v = base([dict(product_id="p1", type="personal_loan", past_due=540.0, days_late=5, instalment_amount=180.0)])
    r = run(pol, "date_amount_gate", v, gate_product="p1", gate_date="2026-10-13")
    check(r["gate_status"] == "past" and r["gate_ok"] == "no" and r["gate_say"], "A past: %s" % r)
    dl = r["gate_deadline"]
    r = run(pol, "date_amount_gate", r, gate_date=dl, gate_amount="")
    check(r["gate_status"] == "ok" and r["gate_ok"] == "yes" and r["gate_out_date"] == dl and r["gate_out_amount"] == "540.00", "A ok: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_date="2026-12-01")
    check(r["gate_status"] == "after_deadline" and r["gate_out_date"] == dl and "1 December" in r["gate_say"], "A after deadline: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_date=dl, gate_amount="900")
    check(r["gate_status"] == "not_allowed_amount" and r["gate_out_amount"] == "540.00" and "540.00" in r["gate_say"], "A above full: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_date="", gate_spec="rel=tomorrow;d=;m=;wd=;wk=none;vague=no", gate_amount="")
    check(r["gate_out_date"] == "2026-10-15", "A spec labels: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_date="", gate_spec="rel=;d=;m=;wd=;wk=next;vague=yes")
    check(r["gate_status"] == "unclear_date", "A vague: %s" % r)
    r = run(pol, "attempt_gate", r, gate_event="first")
    check(r["gate_status"] == "offer" and r["gate_out_amount"] == "540.00" and r["gate_say"].startswith("Could you pay 540.00"), "A first offer: %s" % r)
    return True


def raw4():
    pol = bridged(4)
    acc = [dict(product_id="p1", type="credit_card", past_due=420.0, days_late=6),
           dict(product_id="p2", type="personal_loan", past_due=780.0, days_late=21)]
    v = base(acc)
    # early band: the 4th business day (Wed 21); the Friday holiday moves to Monday and is said with the customer's day
    r = run(pol, "date_amount_gate", v, gate_product="p1", gate_date="2026-10-16", gate_amount="420")
    check(r["gate_deadline"] == "2026-10-21", "raw-4 early deadline: %s" % r)
    check(r["gate_status"] == "non_business" and r["gate_out_date"] == "2026-10-19" and "Friday 16 October" in r["gate_say"]
          and r["gate_ok"] == "no", "raw-4 holiday: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_date="2026-10-26")
    check(r["gate_status"] == "after_deadline" and r["gate_out_date"] == "2026-10-21" and "Monday 26 October" in r["gate_say"], "raw-4 after deadline: %s" % r)
    # late band: the 2nd calendar day is the holiday -> the previous business day (Thu 15)
    r = run(pol, "date_amount_gate", r, gate_product="2", gate_date="2026-10-15", gate_amount="")
    check(r["gate_deadline"] == "2026-10-15" and r["gate_status"] == "ok", "raw-4 late deadline: %s" % r)
    # full_or_floor: 30 percent of 780 = 234; 300 is neither; 100 is below
    r = run(pol, "date_amount_gate", r, gate_amount="300")
    check(r["gate_status"] == "not_allowed_amount" and r["gate_out_amount"] == "234.00" and r["gate_floor"] == "234.00", "raw-4 300: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_amount="100")
    check(r["gate_status"] == "below_floor" and "234.00" in r["gate_say"], "raw-4 below: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_amount="234")
    check(r["gate_status"] == "ok", "raw-4 floor: %s" % r)
    # attempts: early has one; after it, no extra offer, the refused close (notes are off in raw-4)
    r = run(pol, "attempt_gate", r, gate_product="p1", gate_event="first")
    # the bridged plan says date_rule=customer_named (no named day yet): the reducer's fallback, a business day inside the deadline
    check(r["gate_status"] == "offer" and r["gate_out_amount"] == "420.00" and r["gate_out_date"] == "2026-10-15" and r["gate_attempts"] == "1", "raw-4 offer 1: %s" % r)
    r = run(pol, "attempt_gate", r, gate_event="flat")
    check(r["gate_status"] == "exhausted" and r["gate_close_outcome"] == "no_promise" and r["gate_close_reason"] == "refused"
          and r["gate_note_reason"] == "", "raw-4 exhausted: %s" % r)
    r = run(pol, "attempt_gate", r, gate_event="first")
    check(r["gate_status"] == "exhausted" and not r["gate_say"], "raw-4 no extra offer: %s" % r)
    # late: too much -> the floor on the deadline, without an attempt
    r = run(pol, "attempt_gate", r, gate_product="p2", gate_event="first")
    check(r["gate_status"] == "offer" and r["gate_out_amount"] == "780.00" and r["gate_attempts"] == "1", "raw-4 late offer: %s" % r)
    r = run(pol, "attempt_gate", r, gate_event="too_much")
    check(r["gate_status"] == "offer" and r["gate_out_amount"] == "234.00" and r["gate_out_date"] == "2026-10-15" and r["gate_attempts"] == "1", "raw-4 floor offer: %s" % r)
    seen = set()
    for _ in range(4):
        r = run(pol, "attempt_gate", r, gate_event="flat")
        if r["gate_status"] == "offer":
            key = (r["gate_out_amount"], r["gate_out_date"])
            check(key not in seen and key != ("234.00", "2026-10-15"), "raw-4 a refused offer again: %s" % r)
            seen.add(key)
    check(r["gate_status"] == "exhausted", "raw-4 late exhausted: %s" % r)
    return True


def raw5():
    pol = bridged(5)
    acc = [dict(product_id="p1", type="credit_card", past_due=220.0, days_late=9, minimum_payment=66.0),
           dict(product_id="p2", type="personal_loan", past_due=640.0, days_late=9, instalment_amount=213.0),
           dict(product_id="p3", type="car_loan", past_due=75.0, days_late=3, instalment_amount=25.0)]
    v = base(acc)
    r = run(pol, "date_amount_gate", v, gate_product="p3", gate_date="2026-10-19")
    check(r["gate_status"] == "route" and r["gate_queue"] == "restructuring" and r["gate_ok"] == "no", "raw-5 car route: %s" % r)
    r = run(pol, "attempt_gate", r, gate_product="3", gate_event="first")
    check(r["gate_status"] == "route" and not r["gate_say"], "raw-5 car no offer: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_product="p1", gate_date="2026-10-16", gate_amount="")
    check(r["gate_status"] == "non_business" and r["gate_out_date"] == "2026-10-19" and r["gate_deadline"] == "2026-10-20", "raw-5 holiday: %s" % r)
    # read-back: the car can never be read back; a holiday term is refused with the reason
    r = run(pol, "confirm_gate", r, gate_action="readback", gate_terms="p1:220:2026-10-19|p3:75:2026-10-19")
    check(r["gate_status"] == "invalid" and r["gate_ok"] == "no", "raw-5 car read back: %s" % r)
    r = run(pol, "confirm_gate", r, gate_action="readback", gate_terms="p1:220:2026-10-16|p2:640:2026-10-19")
    check(r["gate_status"] == "invalid" and "Friday 16 October" in r["gate_say"], "raw-5 holiday read back: %s" % r)
    r = run(pol, "confirm_gate", r, gate_action="yes")
    check(r["gate_status"] == "stale" and r["gate_ok"] == "no", "raw-5 a yes with no read-back: %s" % r)
    r = run(pol, "confirm_gate", r, gate_action="readback", gate_terms="p1:220:2026-10-19|p2:640:2026-10-19")
    check(r["gate_status"] == "readback" and r["gate_say"].count("?") == 1 and "220.00 on Monday 19 October" in r["gate_say"]
          and "640.00 on Monday 19 October" in r["gate_say"] and r["gate_say"].endswith("Do you confirm?"), "raw-5 read-back: %s" % r)
    rid = r["gate_rb_id"]
    r = run(pol, "confirm_gate", r, gate_action="readback", gate_terms="2:640:2026-10-19|1:220:2026-10-19")
    check(r["gate_status"] == "repeat" and r["gate_rb_id"] == rid, "raw-5 same terms: %s" % r)
    # any change voids it: a yes after a new day is stale
    s = run(pol, "date_amount_gate", r, gate_product="p1", gate_date="2026-10-20", gate_amount="220")
    s = run(pol, "confirm_gate", s, gate_action="yes")
    check(s["gate_status"] == "stale" and s["gate_ok"] == "no", "raw-5 changed then yes: %s" % s)
    # the explicit yes grants exactly those terms, once; then the writes one by one
    r = run(pol, "confirm_gate", r, gate_action="yes")
    check(r["gate_status"] == "granted" and r["gate_ok"] == "yes" and json.loads(r["gate_promises"]) ==
          [dict(product_id="p1", amount=220.0, date="2026-10-19"), dict(product_id="p2", amount=640.0, date="2026-10-19")], "raw-5 granted: %s" % r)
    r2 = run(pol, "confirm_gate", r, gate_action="yes")
    check(r2["gate_status"] == "stale" and r2["gate_ok"] == "no", "raw-5 a second yes: %s" % r2)
    w = run(pol, "confirm_gate", r, gate_action="next")
    check(w["gate_ok"] == "yes" and w["gate_write_product_id"] == "p1" and w["gate_write_amount"] == "220.00" and w["gate_write_date"] == "2026-10-19", "next 1: %s" % w)
    w = run(pol, "confirm_gate", w, gate_action="next")
    check(w["gate_write_product_id"] == "p2", "next 2: %s" % w)
    w = run(pol, "confirm_gate", w, gate_action="next")
    check(w["gate_status"] == "done" and w["gate_ok"] == "no", "next done: %s" % w)
    # per-type floors (PUB-13): card 40 percent, loan 25 percent
    v = base([dict(product_id="p1", type="credit_card", past_due=300.0, days_late=4, minimum_payment=90.0),
              dict(product_id="p2", type="personal_loan", past_due=900.0, days_late=20, instalment_amount=300.0)])
    r = run(pol, "date_amount_gate", v, gate_product="p1", gate_date="2026-10-20", gate_amount="90")
    check(r["gate_status"] == "below_floor" and r["gate_floor"] == "120.00", "raw-5 card floor: %s" % r)
    r = run(pol, "date_amount_gate", r, gate_product="p2", gate_date="2026-10-19", gate_amount="225")
    check(r["gate_status"] == "ok" and r["gate_floor"] == "225.00" and r["gate_deadline"] == "2026-10-19", "raw-5 loan floor: %s" % r)
    return True


def never_raises():
    pol = POL["A"]
    v = dict(now=NOW)
    for name in G.GATES:
        x = dict(v)
        exec(G.gate_source(pol, name), dict(vars=x))
        check(x["gate_status"] == "error" and x["gate_ok"] == "no", "%s without products: %s" % (name, x))
    x = dict(base([dict(product_id="p1", type="personal_loan", past_due=540.0, days_late=5)]), gate_action="readback", gate_terms="garbage")
    G.confirm_gate(x, pol)
    check(x["gate_status"] == "invalid", "bad terms: %s" % x)
    sizes = dict((n, len(G.gate_source(pol, n))) for n in G.GATES)
    check(all(s < 60000 for s in sizes.values()), "sizes: %s" % sizes)
    return sizes


if __name__ == "__main__":
    print("Brief A:", brief_a())
    print("raw-4 per-band deadline, holiday, floor, attempts:", raw4())
    print("raw-5 route_by_type, read-back, stale yes, writes:", raw5())
    print("never raises; packed sizes:", never_raises())
