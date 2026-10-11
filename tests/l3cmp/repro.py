"""python3 tests/l3cmp/repro.py: how much the four L3 raw-4 workflows differ (nodes, prompt size, which key rules they state)."""
import json, os, re
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
RULES = {   # raw-4 README rule table -> a regex on the workflow text
    "greeting recorded": r"call is recorded",
    "3 wrong answers": r"three|3 (wrong|incorrect|failed)",
    "callback 10-18": r"10:00.{0,40}18:00|10 ?am.{0,30}6 ?pm",
    "early deadline 2026-10-21": r"2026-10-21|21 October",
    "late deadline 2026-10-15": r"2026-10-15|15 October",
    "holiday 2026-10-16": r"2026-10-16|16 October",
    "next bd 2026-10-19": r"2026-10-19|19 October",
    "floor 30%": r"30 ?%|30 percent|0\.3\b",
    "floor 50% (withdrawn) present": r"50 ?%|50 percent|0\.5\b",
    "637.53": r"637\.53",
    "Do you confirm?": r"Do you confirm\?",
    "confirmation email line": r"confirmation email will be sent",
    "no add_note": r"add_note",
    "payday 5th": r"\b5th|fifth",
    "1 / 2 attempts": r"(one|1) attempt.{0,200}(two|2) attempts|(two|2) attempts.{0,200}(one|1) attempt",
}
rows = []
for s in ("l3-raw-4", "l3-raw-4-b", "l3-raw-4-c", "l3-raw-4-d"):
    w = json.load(open(os.path.join(D, f"{s}.l3.workflow.json")))
    text = json.dumps(w, ensure_ascii=False)
    prompts = [n.get("prompt") or (n.get("agent") or {}).get("prompt") or "" for n in w["nodes"].values()]
    plen = sum(len(json.dumps(n, ensure_ascii=False)) for n in w["nodes"].values())
    hit = {k: bool(re.search(r, text, re.I | re.S)) for k, r in RULES.items()}
    rows.append((s, len(w["nodes"]), sorted(w["nodes"]), plen, hit))
for s, n, names, plen, hit in rows:
    print(f"{s}: {n} nodes {names}, node json {plen} chars")
print("rule".ljust(32), *(r[0][-1] if r[0][-2] == "-" else "a" for r in rows))
for k in RULES:
    print(k.ljust(32), *("x" if r[4][k] else "." for r in rows))
