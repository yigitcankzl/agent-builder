"""Rebuild the three hybrid workflows from the saved L3 workflows and policies (offline).

    python3 tests/hybrid/rewire.py
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from builder import hybrid

for s in ("raw-4", "raw-5", "brief-a"):
    rp = json.load(open(os.path.join(ROOT, "tests", "hybrid", "rp", f"{s}.policy.json")))
    w = hybrid.wire(json.load(open(os.path.join(ROOT, "tests", "l3cmp", "out", f"l3-{s}.l3.workflow.json"))), rp)
    json.dump(w, open(os.path.join(ROOT, "tests", "hybrid", f"hybrid-{s}.workflow.json"), "w"), indent=1)
    print(s, len(json.dumps(w)) // 1024, "KB", len(w["nodes"]), "nodes", "once:", list(hybrid.once_lines(rp)))
