"""The bridge always emits the fixed sentence keys and the who vocabulary, whatever ids the extractor used.
Uses saved extractions (no model calls).   python3 tests/test_bridge_keys.py"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.policy_bridge import FIXED_SENTENCES, PARTY_VOCAB, WHO_VOCAB, to_reducer

OAS = os.path.join(ROOT, "tools", "openapi.json")
V3 = os.path.join(ROOT, "tests", "policy_eval", "v3")


def check(c, m):
    if not c:
        raise AssertionError(m)


if __name__ == "__main__":
    for b in ("brief-a", "brief-ab", "mut-01", "mut-02", "mut-03", "mut-04", "mut-05", "raw-a"):
        for r in ("run4", "run5"):
            p = json.load(open(os.path.join(V3, r, b + ".json")))
            rp, _ = to_reducer(p, OAS)
            check(set(FIXED_SENTENCES) <= set(rp["sentences"]), f"{b} {r}: keys missing")
            check(all(w["who"] in WHO_VOCAB and w.get("party", "") in PARTY_VOCAB for w in rp["who_rules"]), f"{b} {r}: who vocab")
            # the extractor's own ids are irrelevant: drop every sentence the extractor gave and re-bridge
            q = copy.deepcopy(p)
            q["sentences"] = {}
            rq, _ = to_reducer(q, OAS)
            check(set(FIXED_SENTENCES) <= set(rq["sentences"]), f"{b} {r}: keys missing without extractor sentences")
        print("ok", b)
    print("PASS")
