"""Freya dry-run validation of the generated workflows: validate_workflow only (dryRun=true). No save, no chat,
no simulation, no retry on 503/504.   python3 tests/dryrun_generated.py"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya

BRIEFS = ["brief-a", "brief-ab", "mut-01", "mut-02", "mut-03", "mut-04", "mut-05", "raw-a"]

if __name__ == "__main__":
    out = {}
    for b in BRIEFS:
        wf = json.load(open(os.path.join(ROOT, "tests", "generated", b + ".workflow.json")))
        try:
            r = freya.validate_workflow("dryrun-" + b, wf)
            out[b] = {"valid": bool(r.get("valid")), "result": r}
        except RuntimeError as e:  # one attempt only; a 503/504 is reported, not re-sent
            out[b] = {"valid": False, "error": str(e)[:1500]}
        print(b, "VALID" if out[b]["valid"] else "INVALID", json.dumps(out[b].get("result") or out[b].get("error"))[:600], flush=True)
        time.sleep(1)
    json.dump(out, open(os.path.join(ROOT, "tests", "generated", "dryrun.json"), "w"), indent=1)
