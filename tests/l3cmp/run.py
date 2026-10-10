"""L3 comparison builds: build.py's own L3 path, forced by a failing extractor (signal EXTRACT), real save.

    python3 tests/l3cmp/run.py <slot> <brief> <openapi.json>
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya
from builder import build as B, fallback_llm as L


def no_extract(*a, **k):
    raise RuntimeError("forced L3 (comparison experiment)")


if __name__ == "__main__":
    slot, brief, oas = sys.argv[1:4]
    out = os.path.join(ROOT, "tests", "l3cmp", "out")
    r = B.build([brief], oas, slot, freya, out, out, 2, 25 * 60, no_extract,
                fallback=lambda b, o, log: L.Fallback(b, o, log=log))
    p = os.path.join(out, f"{slot}.l3.workflow.json")
    if os.path.exists(p):
        r["l3_check"] = L.check(json.load(open(p)), L.oas_ops(oas))
    json.dump(r, open(os.path.join(out, f"{slot}.result.json"), "w"), indent=1, default=str)
    print(json.dumps(r, default=str))
