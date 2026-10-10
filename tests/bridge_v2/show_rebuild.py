"""Print the bridge-v2 fields of a rebuild (hooks, formats, floor, acceptance, date rules).

    python3 tests/bridge_v2/show_rebuild.py [out_dir]
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "e2e8"), "submission")
for s in ("brief-a", "brief-ab", "ins-clean", "raw-b", "mut-03"):
    rp = json.load(open(os.path.join(D, s + ".policy.json")))
    wf = json.load(open(os.path.join(D, s + ".workflow.json")))
    wf = wf.get("workflow", wf)
    print("=====", s)
    print(" greet:", wf["nodes"]["greet"]["on_enter"]["text"])
    for h in rp.get("hooks") or []:
        print(f"  HOOK {h['point']:20} cond={h['condition']!s:14} ans={h['expects_answer']!s:5} {h['text']!r}" + (" [placed]" if h.get("placed") else ""))
    for u in rp.get("unplaced_hooks") or []:
        print(f"  UNPLACED ({u['why']}): {u['quote'][:80]!r}")
    print("  formats:", [(q["field"], q["format"]) for q in rp["identity"]["questions"]])
    print("  floor:", {t: {k: v for k, v in f.items() if k != "source"} for t, f in rp["products"]["floor_by_type"].items()})
    print("  acceptance:", rp["amounts"].get("acceptance"))
    print("  date_rules:", {k: (r["action"], r.get("say")) for k, r in rp["date_rules"].items()})
    print("  unmapped_topics:", rp.get("unmapped_topics"))
