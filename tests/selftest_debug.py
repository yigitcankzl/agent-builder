"""Print the action trace of one self-test scenario.   python3 tests/selftest_debug.py <policy.json> <scenario> [oas]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import builder.selftest as S

pol = json.load(open(sys.argv[1]))
oas = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "tools", "openapi.json")
R = S.load_reducer()
S.NOW = S.pick_now(pol)
sc = S.scenarios(pol)
idq = sc.pop("_idq")
orig = R.step
log = []


def step(policy, st, ev, te, now, cv=None):
    st2, act = orig(policy, st, ev, te, now, cv)
    log.append((st.get("q"), (ev or {}).get("kind"), (ev or {}).get("t"), te and te.get("node"), act.get("type"),
                act.get("tool") or act.get("node") or "", (act.get("text") or act.get("hint") or act.get("outcome") or "")[:70], st2.get("q")))
    return st2, act


R.step = step
print(S.run_scenario(R, pol, sys.argv[2], sc[sys.argv[2]], oas, idq))
for row in log[:30]:
    print(row)
