"""Export every FAILED call of a run_cases --out file (or given call ids) for diagnosis:
results/<run>/fails/<case>.json with the full messages (transcript, tool calls, variable_extracted and other system
events, per-message variable snapshots), the judge reason, the ledger diff and the expected ledger.

    python3 tests/export_fails.py <out.json> [<run name>]          # all failed rows of that run
    python3 tests/export_fails.py --call <call_id> <case> <run>    # one call
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya

CASES = {c["id"]: c for c in json.load(open(os.path.join(ROOT, "public-test-set.json")))}


def export(call_id, case, run, failed=None, row=None):
    c = freya.get_call(call_id)
    events = []
    for m in c.get("messages") or []:
        e = {"role": m.get("role"), "node": m.get("nodeId"), "message": m.get("message"), "t": m.get("secondsFromStart")}
        if m.get("role") == "system":
            try:
                e["event"] = json.loads(m.get("message") or "{}")
            except Exception:
                pass
        vt = (m.get("workflowSnapshot") or {}).get("variableTable")
        if vt:
            e["vars"] = {k: x.get("value") for k, x in vt.items()}
        events.append(e)
    out = {"case": case, "call_id": call_id, "ended": c.get("endedReason"), "failed": failed or [],
           "expected": (CASES.get(case) or {}).get("expected"), "checks": (CASES.get(case) or {}).get("checks"),
           "tools": (row or {}).get("tools"), "customer_id": (row or {}).get("customer_id"), "messages": events}
    d = os.path.join(ROOT, "results", run, "fails")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{case}.json")
    json.dump(out, open(path, "w"), indent=1, default=str)
    return path


if __name__ == "__main__":
    if sys.argv[1] == "--call":
        print(export(sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        r = json.load(open(sys.argv[1]))
        run = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(os.path.basename(sys.argv[1]))[0]
        for rows in r.get("all_rows") or [r["rows"]]:
            for row in rows:
                if not row["pass"] and row.get("call_id"):
                    print(export(row["call_id"], row["id"], run, row["failed"], row))
