"""Phase 2: Cursor's generalisation personas (fixtures-briefs 287034c) through the reducer with Fork 2's bridged
policies (policy-extract 701ebdc). Read-only copies in tests/fixtures/general and tests/generated.

    python3 tests/test_personas.py [ins-clean|raw-b] [persona-id ...]
Per step: action type, say contains / must_not_contain / exact, tool + args, close outcome/reason/farewell.
Args are compared by name and value; when only the names differ (canonical role vs the brief's OAS field) the step is
reported as ARGNAMES (the bridge's tool_args mapping), separately from real mismatches. Final ledger likewise.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import same

PDIR = os.environ.get("POLICY_DIR", "tests/generated")
FIXTURES = {
    "ins-clean": ("tests/fixtures/general/ins-clean/personas.json", PDIR + "/ins-clean.reducer_policy.json"),
    "raw-b": ("tests/fixtures/general/raw-b/personas.json", PDIR + "/raw-b.reducer_policy.json"),
}


def vals(d):
    return sorted(json.dumps(v, sort_keys=True) if not isinstance(v, float) else json.dumps(round(v, 2)) for v in (d or {}).values())


def cmp_args(exp, got):
    if same(exp, got):
        return None
    e = dict(exp); g = dict(got)
    for x in (e, g):
        for k, v in list(x.items()):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                x[k] = round(float(v), 2)
    if vals(e) == vals(g):
        return "ARGNAMES"
    return "MISMATCH"


def check(exp, act):
    out = []
    if act.get("type") != exp["type"]:
        return [("MISMATCH", f"type {act.get('type')} != {exp['type']} | got {json.dumps(act)[:160]}")]
    if exp["type"] == "say_exact":
        t = act.get("text", "")
        if exp.get("text") is not None and t != exp["text"]:
            out.append(("MISMATCH", f"text {t!r} != {exp['text']!r}"))
        for s in exp.get("contains", []):
            if s not in t:
                out.append(("CASE" if s.lower() in t.lower() else "MISMATCH", f"missing {s!r} in {t!r}"))
        for s in exp.get("must_not_contain", []):
            if s in t:
                out.append(("MISMATCH", f"forbidden {s!r} in {t!r}"))
    elif exp["type"] == "call_tool":
        if act.get("tool") != exp["tool"]:
            out.append(("MISMATCH", f"tool {act.get('tool')} != {exp['tool']}"))
        else:
            c = cmp_args(exp["args"], act.get("args"))
            if c:
                out.append((c, f"args {act.get('args')} vs {exp['args']}"))
    elif exp["type"] == "close":
        if (act.get("outcome"), act.get("reason")) != (exp["outcome"], exp.get("reason")):
            out.append(("MISMATCH", f"close {act.get('outcome')}/{act.get('reason')} != {exp['outcome']}/{exp.get('reason')}"))
        fw = act.get("farewell", "")
        if exp.get("farewell") and exp.get("farewell_exact", True) and fw != exp["farewell"]:
            out.append(("MISMATCH", f"farewell {fw!r} != {exp['farewell']!r}"))
        for s in exp.get("farewell_contains", []):
            if s not in fw:
                out.append(("MISMATCH", f"farewell missing {s!r}: {fw!r}"))
    return out


def run_persona(pol, p):
    cust = p["customer"]
    cv = dict(customer_id=cust["customer_id"], title=cust.get("title"), first_name=cust.get("first_name"),
              last_name=cust.get("last_name"), now=p["now"])
    st = R.init_state(pol, cv)
    counts = dict()
    ledger = dict(outcome=None, reason=None, promises=[], notes=[], callbacks=[], transfers=[])
    issues = []
    for i, s in enumerate(p["steps"], 1):
        if s["source"] == "user":
            n = s["ev"].split(";")[0].split("=")[1]
            st["tok"] = n
            ev = R.parse_event(s["ev"], st, R.CONTRACT_TOPICS)
            st, act = R.step(pol, st, ev, None, p["now"], cv)
            st["last_tok"] = n
        else:
            node = "t_" + s["tool"]
            ok = str(s["result"].get("ok")).lower() == "true"
            c = counts.setdefault(node, [0, 0])
            c[0 if ok else 1] += 1
            te = dict(node=node, success=c[0], failure=c[1], status_code=200 if ok else 500,
                      ok="true" if ok else None, data=s["result"])
            st, act = R.step(pol, st, None, te, p["now"], cv)
            if ok:
                a = {k: v for k, v in s["args"].items() if k != "customer_id"}
                key = dict(create_promise="promises", add_note="notes", schedule_callback="callbacks",
                           transfer_to_agent="transfers").get(s["tool"])
                if key:
                    ledger[key].append(a)
        if act.get("type") == "close":
            ledger["outcome"], ledger["reason"] = act.get("outcome"), act.get("reason")
        for kind, msg in check(s["action"], act):
            issues.append((kind, f"step {i} ({s['source']}{' ' + s.get('utterance', '')[:40] if s.get('utterance') else ''}): {msg}"))
    for k in ("outcome", "reason"):
        if ledger[k] != p["ledger"].get(k):
            issues.append(("MISMATCH", f"ledger.{k}: {ledger[k]} != {p['ledger'].get(k)}"))
    return issues


if __name__ == "__main__":
    which = [a for a in sys.argv[1:] if a in FIXTURES] or list(FIXTURES)
    ids = [a for a in sys.argv[1:] if a not in FIXTURES]
    total = ok = 0
    for f in which:
        pf, polf = FIXTURES[f]
        personas = json.load(open(os.path.join(ROOT, pf)))["personas"]
        pol = json.load(open(os.path.join(ROOT, polf)))
        print(f"===== {f}   vocab log: {R.vocab(pol)['log']}")
        for p in personas:
            if ids and p["id"] not in ids:
                continue
            iss = run_persona(pol, p)
            real = [x for x in iss if x[0] == "MISMATCH"]   # ARGNAMES (bridge tool_args) and CASE (letter case only) reported apart
            total += 1
            ok += not real
            print(("PASS" if not iss else ("PASS*" if not real else "FAIL")) + f" {p['id']:14} {p['title'][:50]}"
                  + (f"  ({len(real)} mismatches, {len(iss) - len(real)} arg-name only)" if iss else ""))
            for kind, msg in iss[:8]:
                print(f"      {kind:9} {msg[:260]}")
    print(f"{ok}/{total} personas with no real mismatch (PASS* = only argument names or letter case differ)")
