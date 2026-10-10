"""Unit tests for builder/selftest.py: each invariant must fire on a deliberately broken reducer.
The broken reducers WRAP the real one and corrupt one output each; no reducer logic is written here.

    python3 tests/test_selftest.py
"""
import copy, datetime, json, os, sys, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.selftest import load_reducer, run_selftest

OAS = os.path.join(ROOT, "tools", "openapi.json")
POL = json.load(open(os.path.join(ROOT, "tests", "generated", "brief-a.reducer_policy.json")))
R = load_reducer()


def broken(name, mutate):
    """A module-like reducer whose step() output is corrupted by mutate(st_in, ev, st_out, act) -> (st_out, act)."""
    def step(policy, st, ev, te, now, cv=None):
        st2, act = R.step(policy, st, ev, te, now, cv)
        return mutate(st, ev, st2, act)
    return types.SimpleNamespace(step=step, init_state=R.init_state, __name__=name)


def saturday():
    d = datetime.date(2026, 10, 14)
    return (d + datetime.timedelta(days=(5 - d.weekday()) % 7)).isoformat()


def first_promise(st, ev, st2, act, _done=[False]):
    if st2.get("verified") == "yes" and act.get("type") == "say_exact" and not _done[0]:
        _done[0] = True
        return st2, dict(type="call_tool", tool="create_promise", args=dict(customer_id="c", product_id="p1", amount=1, date="2026-10-16"))
    return st2, act


def bad_date(st, ev, st2, act):
    if act.get("type") == "call_tool" and act.get("tool") == "create_promise":
        act = dict(act, args=dict(act["args"], date=saturday()))
    return st2, act


CASES = {
    "one action": lambda st, ev, st2, act: (st2, None),
    "empty say": lambda st, ev, st2, act: (st2, dict(act, text="") if act.get("type") == "say_exact" else act),
    "read-back before write": first_promise,
    "verification gate": lambda st, ev, st2, act: (st2, dict(type="call_tool", tool="get_account", args=dict(customer_id="c"))
                                                    if st2.get("verified") != "yes" and act.get("type") == "say_exact" else act),
    "caps": lambda st, ev, st2, act: (dict(st2, products=[dict(p, attempts=99) for p in st2.get("products") or []]), act),
    "honesty": lambda st, ev, st2, act: (st2, dict(act, text="Your promise is recorded.") if act.get("type") == "say_exact" else act),
    "close outcome": lambda st, ev, st2, act: (st2, dict(act, outcome="bogus_outcome") if act.get("type") == "close" else act),
    "dates": bad_date,
    "partial": lambda st, ev, st2, act: (dict(st2, counters=dict(st2.get("counters") or {}, clarify=7)) if ev and ev.get("st") == "partial" else st2, act),
}

if __name__ == "__main__":
    assert R is not None, "the reducer module is required for these tests"
    clean = run_selftest(POL, OAS)
    assert clean["failed"] == 0, clean["failures"]
    print(f"ok real reducer: {clean['scenarios']} scenarios pass in {clean['seconds']} s")
    bad = 0
    for inv, mut in CASES.items():
        r = run_selftest(POL, OAS, broken(inv, mut))
        fired = r["invariants"].get(inv, [0, 0])[1] > 0
        bad += not fired
        print(f"{'ok' if fired else 'MISSED'} invariant {inv!r} fires on the broken reducer ({r['failed']} scenarios fail)")
    print("PASS" if not bad else f"FAIL ({bad} invariants did not fire)")
    sys.exit(1 if bad else 0)
