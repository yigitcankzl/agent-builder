"""Bridge v2 snippets: brief -> extracted policy (real Claude extraction, cached) -> bridged policy -> greet + fields.

    python3 tests/bridge_v2/run_snippets.py [--fresh] [snippet ...]
The extracted policy is cached in tests/bridge_v2/out/<snippet>.policy.json (--fresh re-extracts). No Freya calls.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from builder.generator import generate
from builder.policy_bridge import to_reducer
from builder.policy_extract import extract
from builder.validate_workflow import validate

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SNIPPETS = {"snippet-hooks-id": os.path.join(HERE, "openapi-snippet.json"),
            "snippet-floor-dates": os.path.join(ROOT, "tools", "openapi.json")}


def run(name, fresh=False):
    oas = SNIPPETS[name]
    cache = os.path.join(OUT, name + ".policy.json")
    if fresh or not os.path.exists(cache):
        pol, rep = extract([os.path.join(HERE, name + ".md")], oas)
        os.makedirs(OUT, exist_ok=True)
        json.dump(pol, open(cache, "w"), indent=1)
        print(f"extracted {name}: {rep['seconds']} s, quotes rejected {rep['quotes_rejected']}, unverified {rep['quotes_unverified']}")
    pol = json.load(open(cache))
    rp, brep = to_reducer(pol, oas, [])
    wf = generate(rp, oas)
    json.dump(rp, open(os.path.join(OUT, name + ".reducer_policy.json"), "w"), indent=1)
    errs = validate(wf, rp, oas)
    print(f"== {name}  validator: {'PASS' if not errs else errs}")
    print("extracted hooks:", json.dumps([{k: h.get(k) for k in ("id", "point", "condition", "expects_answer")} | {"quote": (h.get("source") or [{}])[0].get("quote")} for h in pol.get("hooks") or []], indent=1))
    print("greet:", wf["nodes"]["greet"]["on_enter"]["text"])
    for h in rp.get("hooks") or []:
        print(f"  HOOK {h['point']:20} cond={h['condition']!s:20} ans={h['expects_answer']!s:5} {h['text']!r}")
    for u in rp.get("unplaced_hooks") or []:
        print(f"  UNPLACED ({u['why']}): {u['quote'][:90]!r}")
    for q in (rp.get("identity") or {}).get("questions") or []:
        print(f"  ID {q['field']:15} format={q['format']:10} ({q.get('format_how')}; extractor said {q.get('format_brief')!r})")
    print("  floor_by_type:", json.dumps({t: {k: v for k, v in f.items() if k != "source"} for t, f in (rp.get("products") or {}).get("floor_by_type", {}).items()}))
    print("  acceptance:", json.dumps((rp.get("amounts") or {}).get("acceptance")))
    for sit, r in (rp.get("date_rules") or {}).items():
        print(f"  date_rules.{sit:18} {r['action']:24} from={r.get('from'):17} say={r.get('say')!r}")
    print("  notes:", [n for n in brep["notes"] if "date_rules" in n or "acceptance" in n or "hook" in n])
    if brep["api_mismatch"]:
        print("  api_mismatch:", json.dumps(brep["api_mismatch"])[:400])
    return rp


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or [n for n in SNIPPETS if os.path.exists(os.path.join(HERE, n + ".md"))]
    for n in names:
        run(n, fresh)
