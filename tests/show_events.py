"""Show the bridged event rows (topic, outcome, reason, note, say) and absent topics for policies in tests/generated.
    python3 tests/show_events.py [slot ...]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for slot in sys.argv[1:] or ["brief-a", "brief-ab", "raw-b", "ins-clean"]:
    p = json.load(open(os.path.join(ROOT, "tests", "generated", slot + ".reducer_policy.json")))
    print(f"== {slot}: absent {p.get('topics_absent')}")
    for e in p.get("events") or []:
        print(f"   {e['topic']:<14} out={e.get('outcome')!s:<16} reason={e.get('reason')!s:<14} note={e.get('note_reason')!s:<10} "
              f"say={str(e.get('say'))[:60]!r}" + (f"  (dropped: {str(e.get('say_dropped'))[:50]!r})" if e.get("say_dropped") else ""))
    print("   tool_args.create_promise:", (p.get("tool_args") or {}).get("create_promise"), "| results get_account:",
          json.dumps((p.get("tool_results") or {}).get("get_account"))[:200])
