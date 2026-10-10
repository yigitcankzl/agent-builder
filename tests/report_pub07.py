"""Per-run report of a PUB-07 regression: every date-engine decision in the call (from the variable table), the
ledger promise and the scorer/judge verdict.   python3 tests/report_pub07.py results/pub07-plain.json [...]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya


def decisions(call_id):
    out, last = [], None
    for m in freya.get_call(call_id).get("messages", []):
        vt = (m.get("workflowSnapshot") or {}).get("variableTable") or {}
        val = lambda k: (vt.get(k) or {}).get("value")
        key = (val("date_handled"), val("date_reason"), val("accepted_date"))
        if val("date_handled") and key != last:
            out.append({"iso": val("date_iso"), "spec": val("date_spec"), "date_reason": val("date_reason"),
                        "accepted_date": val("accepted_date"), "say_next": val("say_next") if val("route_date") == "say" else ""})
            last = key
    return out


if __name__ == "__main__":
    for path in sys.argv[1:]:
        r = json.load(open(path))
        print(f"== {os.path.basename(path)}: {r['passed']}/{r['total']} (a customer counts with {r['runs']} of {r['runs']} runs)")
        for i, rows in enumerate(r["all_rows"], 1):
            for row in rows:
                print(f"  run {i}: {'PASS' if row['pass'] else 'FAIL'}  tools: {' > '.join(row['tools'])}")
                for d in decisions(row["call_id"]):
                    print(f"     engine: reason={d['date_reason']} accepted={d['accepted_date']} iso={d['iso']} spec={d['spec']}"
                          + (f" | say_next: {d['say_next']!r}" if d["say_next"] else ""))
                for f in row["failed"]:
                    print("     failed:", f[:400])
