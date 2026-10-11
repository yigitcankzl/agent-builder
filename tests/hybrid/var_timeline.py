"""Timeline of a saved call: tool starts/errors and the variables that first appear at each event.

    python3 tests/hybrid/var_timeline.py <saved call json>
"""
import json, sys

c = json.load(open(sys.argv[1]))
prev = set()
for k, x in enumerate(c["messages"]):
    if x.get("role") != "system":
        print(k, x.get("role"), str(x.get("message"))[:80])
        continue
    try:
        e = json.loads(x.get("message") or "{}")
    except ValueError:
        continue
    if e.get("event") in ("function_call_start", "function_call_error", "function_call_complete"):
        print(k, e["event"], e.get("function"), str(e.get("error") or "")[:60])
    vt = e.get("variable_table")
    if vt:
        new = set(vt) - prev
        if new:
            print(k, "   new vars:", sorted(new)[:30])
            for n in sorted(new):
                v = vt[n].get("value") if isinstance(vt[n], dict) else vt[n]
                if not isinstance(v, (str, int, float, bool)) and v is not None:
                    print(k, "   non-scalar var:", n, type(v).__name__, json.dumps(v)[:120])
        prev |= set(vt)
