"""Save the three hybrid workflows to their slots (only when no simulation runs on them), export, print the versions.

    python3 tests/hybrid/save_slots.py
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import tests._env as E
E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
import freya
from builder import smoke

STATE = os.path.join(ROOT, "tests", ".platform-agents.json")
sims = smoke.running_sims(freya)
if sims is None or sims:
    sys.exit(f"NOT SAVED: simulation running or unknown ({sims})")
before = json.load(open(STATE))
for s in ("raw-4", "raw-5", "brief-a"):
    w = json.load(open(os.path.join(ROOT, "tests", "hybrid", f"hybrid-{s}.workflow.json")))
    ids = freya.save_workflow("hybrid-" + s, w, STATE)
    freya.export_workflow(ids["workflow_id"], os.path.join(ROOT, "tests", "hybrid", f"hybrid-{s}.export.json"))
    same = ids["agent_id"] == before["hybrid-" + s]["agent_id"]
    print("hybrid-" + s, ids["agent_id"], "same" if same else "CHANGED", "version", ids.get("version"))
