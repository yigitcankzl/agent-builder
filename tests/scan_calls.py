"""Scan every call of run_cases --out files for code_exec errors (e.g. the size limit), hub_error, end reasons.
    python3 tests/scan_calls.py <out.json> [...]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya

for path in sys.argv[1:]:
    r = json.load(open(path))
    print(f"== {os.path.basename(path)}: {r['passed']}/{r['total']}")
    for row in r["rows"]:
        try:
            c = freya.get_call(row["call_id"])
        except Exception as e:
            print(f"   {row['id']} call {row['call_id']}: get_call failed {str(e)[:120]}")
            continue
        errs, hub_err = [], None
        for m in c.get("messages") or []:
            if m.get("role") == "system" and "function_call_error" in str(m.get("message")):
                errs.append(str(m.get("message"))[:200])
            vt = (m.get("workflowSnapshot") or {}).get("variableTable") or {}
            if (vt.get("hub_error") or {}).get("value"):
                hub_err = vt["hub_error"]["value"]
        print(f"   {'PASS' if row['pass'] else 'FAIL'} {row['id']} call {row['call_id']} ended={c.get('endedReason')} "
              f"code_errors={len(errs)} hub_error={hub_err!r}")
        for e in errs[:3]:
            print("      ", e)
        for f in row["failed"]:
            print("       -", f[:300])
