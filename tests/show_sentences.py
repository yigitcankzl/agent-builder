"""Show the reducer-facing sentences and date templates the bridge provides for saved extractions (no model calls).
    python3 tests/show_sentences.py [brief ...]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.policy_bridge import consolidate_unmapped, to_reducer

for b in sys.argv[1:] or ["brief-a", "brief-ab", "raw-a"]:
    runs = [json.load(open(os.path.join(ROOT, "tests", "policy_eval", "v3", r, b + ".json"))) for r in ("run4", "run5")]
    st, _ = consolidate_unmapped(runs)
    rp, rep = to_reducer(runs[1], os.path.join(ROOT, "tools", "openapi.json"), st)
    s = rp["sentences"]
    print(b, {k: s[k]["text"] for k in ("debt_intro", "id_fail", "no_other_terms", "change_in_app", "farewell") if k in s})
    print("   date say:", rp["on_non_business_day"]["say"], "|", rp["on_after_deadline"]["say"])
    print("   notes:", [n for n in rep["notes"] if "sentence" in n or "template" in n])
