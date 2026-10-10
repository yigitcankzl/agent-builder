"""Which state keys does the reducer change on a partial event?   python3 tests/partial_diff.py <policy.json>"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import builder.selftest as S

pol = json.load(open(sys.argv[1]))
R = S.load_reducer()
S.NOW = S.pick_now(pol)
orig = R.step


def step(policy, st, ev, te, now, cv=None):
    st2, act = orig(policy, st, ev, te, now, cv)
    if ev and ev.get("st") == "partial":
        ch = {k: (st.get(k), st2.get(k)) for k in set(st) | set(st2) if st.get(k) != st2.get(k)}
        print("partial ->", act, "\nchanged:", json.dumps(ch, default=str)[:800])
    return st2, act


R.step = step
sc = S.scenarios(pol)
idq = sc.pop("_idq")
S.run_scenario(R, pol, "partial_then_accept", sc["partial_then_accept"], os.path.join(ROOT, "tools", "openapi.json"), idq)
