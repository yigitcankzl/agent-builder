"""Replay Cursor's public sequences (fixtures-briefs ff2b94b, read-only copy in tests/fixtures/reducer/) through
builder.engine.reducer.step with the bridged policies (policy-extract tests/generated/*.reducer_policy.json).

    python3 tests/test_reducer_sequences.py [PUB-07 ...] [-v]
Per step: the action (type; contains / must_not_contain / exact text; tool + args; close outcome/reason/farewell) and
every key of the fixture's state snapshot. Per case: the ledger built from the actions and tool results.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R

FIX = json.load(open(os.path.join(ROOT, "tests", "fixtures", "reducer", "public_sequences.json")))
PDIR = os.path.join(ROOT, os.environ.get("POLICY_DIR", os.path.join("tests", "generated")))   # e.g. tests/generated/e2e8
POL = {"A": json.load(open(os.path.join(PDIR, "brief-a.reducer_policy.json"))),
       "A+B": json.load(open(os.path.join(PDIR, "brief-ab.reducer_policy.json")))}
TOPICS = ["injection", "hardship", "dispute", "paid", "restructure", "human", "stop", "decline", "purpose",
          "change_promise", "terms", "scam", "robot", "unknown_info", "other"]


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 0.005
        except (TypeError, ValueError):
            return False
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def check_action(exp, act):
    bad = []
    if act.get("type") != exp["type"]:
        return [f"type {act.get('type')} != {exp['type']}"]
    if exp["type"] == "say_exact":
        text = act.get("text", "")
        if exp.get("text") is not None and text != exp["text"]:
            bad.append(f"text {text!r} != {exp['text']!r}")
        for s in exp.get("contains", []):
            if s not in text:
                bad.append(f"missing {s!r} in {text!r}")
        for s in exp.get("must_not_contain", []):
            if s in text:
                bad.append(f"forbidden {s!r} in {text!r}")
    elif exp["type"] == "call_tool":
        if act.get("tool") != exp["tool"] or not same(act.get("args"), exp["args"]):
            bad.append(f"call {act.get('tool')} {act.get('args')} != {exp['tool']} {exp['args']}")
    elif exp["type"] == "close":
        if act.get("outcome") != exp["outcome"] or act.get("reason") != exp.get("reason"):
            bad.append(f"close {act.get('outcome')}/{act.get('reason')} != {exp['outcome']}/{exp.get('reason')}")
        fw = act.get("farewell", "")
        if exp.get("farewell_exact") and fw != exp["farewell"]:
            bad.append(f"farewell {fw!r} != {exp['farewell']!r}")
        for s in exp.get("farewell_contains", []):
            if s not in fw:
                bad.append(f"farewell missing {s!r}: {fw!r}")
    return bad


def check_state(exp, st):
    return [f"state.{k}: {json.dumps(st.get(k))} != {json.dumps(v)}" for k, v in exp.items() if not same(st.get(k), v)]


def run_case(c, verbose=False):
    pol = POL[c["policy"]]
    cv = c["call_variables"]
    st = R.init_state(pol, cv)
    problems = [f"bootstrap {x}" for x in check_state(c["bootstrap"]["state"], st)]
    ledger = dict(outcome=None, reason=None, promises=[], notes=[], callbacks=[], transfers=[])
    last_call = None
    expected_state = c["bootstrap"]["state"]
    for s in c["steps"]:
        if s["source"] == "user":
            st["tok"] = s["event_fields"]["n"]
            ev = R.parse_event(s["event"], st, TOPICS)
            st, act = R.step(pol, st, ev, None, c["now"], cv)
            st["last_tok"] = s["event_fields"]["n"]
        else:
            te = dict(s["tool_event"])
            st, act = R.step(pol, st, None, te, c["now"], cv)
            if last_call and te.get("delta_success", 0) > 0 and str(te.get("ok")).lower() == "true":
                t, a = last_call
                if t == "create_promise":
                    ledger["promises"].append(dict(product_id=a["product_id"], amount=a["amount"], date=a["date"]))
                elif t == "add_note":
                    ledger["notes"].append(dict(product_id=a["product_id"], reason=a["reason"]))
                elif t == "schedule_callback":
                    ledger["callbacks"].append(dict(date=a["date"], time=a["time"]))
                elif t == "transfer_to_agent":
                    ledger["transfers"].append(dict(queue=a["queue"]))
        if act.get("type") == "call_tool":
            last_call = (act["tool"], act["args"])
        if act.get("type") == "close":
            ledger["outcome"], ledger["reason"] = act["outcome"], act.get("reason")
        bad = check_action(s["action"], act)
        if s.get("state") is not None and not s.get("state_unchanged"):
            expected_state = s["state"]
        bad += check_state(expected_state, st)
        if verbose:
            print(f"   [{s['step']}] {json.dumps(act)[:200]}")
        for b in bad:
            problems.append(f"step {s['step']}: {b}")
    lexp = c["ledger"]
    for k in ("outcome", "reason", "promises", "notes", "callbacks", "transfers"):
        if not same(ledger[k], lexp[k]):
            problems.append(f"ledger.{k}: {ledger[k]} != {lexp[k]}")
    return problems


if __name__ == "__main__":
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv
    n_ok = 0
    for c in FIX["cases"]:
        if only and c["id"] not in only:
            continue
        probs = run_case(c, verbose)
        n_ok += not probs
        print(("PASS " if not probs else "FAIL ") + c["id"] + ("" if not probs else f"  ({len(probs)} problems)"))
        for p in probs[:12]:
            print("     ", p[:300])
    total = len(only) if only else len(FIX["cases"])
    print(f"{n_ok}/{total} sequences exact")
