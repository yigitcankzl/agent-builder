"""Self-test every bridged policy in tests/generated with the current reducer.   python3 tests/selftest_all.py"""
import glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.selftest import run_selftest

for f in sorted(glob.glob(os.path.join(ROOT, "tests", "generated", "*.reducer_policy.json"))):
    name = os.path.basename(f).replace(".reducer_policy.json", "")
    oas = os.path.join(ROOT, "tests", "fixtures", "general", name, "openapi.json")
    oas = oas if os.path.exists(oas) else os.path.join(ROOT, "tools", "openapi.json")
    r = run_selftest(json.load(open(f)), oas)
    print(f"{name}: {r['passed']}/{r['scenarios']} in {r.get('seconds')} s", json.dumps(r.get("failures") or {})[:400])
