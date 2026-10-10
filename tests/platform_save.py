"""Dry-run + save a built workflow to a slot (lane-granted platform step). No retries on 503/504.
    python3 tests/platform_save.py <export.workflow.json> <slot>"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya

wf = json.load(open(sys.argv[1]))
wf = wf.get("workflow", wf)
slot = sys.argv[2]
try:
    print("dry run:", freya.validate_workflow(slot, wf))
    ids = freya.save_workflow(slot, wf, os.path.join(ROOT, "tests", ".platform-agents.json"))
    print(json.dumps(ids))
except RuntimeError as e:
    print("ERROR (not re-sent):", str(e)[:800])
    sys.exit(1)
