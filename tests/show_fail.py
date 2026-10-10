"""Compact view of exported failures: transcript, the ev per turn and the tool calls.
    python3 tests/show_fail.py results/<run>/fails/<case>.json [...]"""
import json, sys

for path in sys.argv[1:]:
    d = json.load(open(path))
    print("=====", d["case"], d["call_id"], d.get("ended"))
    for f in d.get("failed") or []:
        print("  !", f[:300])
    for m in d["messages"]:
        msg = str(m.get("message") or "")
        if m["role"] in ("user", "assistant"):
            print(m["role"][:4], "|", msg[:200])
        elif m["role"] == "system" and "variable_extracted" in msg and '"ev"' in msg:
            print("   ev", json.loads(msg)["value"][:150])
        elif m["role"] == "system" and "function_call_complete" in msg and "api_call" in msg:
            e = json.loads(msg)
            print("   tool->", json.dumps((e.get("result") or {}).get("data"))[:160])
