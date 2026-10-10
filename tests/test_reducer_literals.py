"""No brief literals in the reducer: a grep, plus a behavioural check with renamed policy values.

    python3 tests/test_reducer_literals.py
1. grep: brief outcome / reason / field names must not appear in builder/engine/reducer.py or event_field.py.
   Allowed (contract vocabulary, not brief values): product statuses (refused, paid, failed, ...), event kinds and
   topics, the ev payload value who.party=wrong_number, slot names (unclear, declined, ...), bridge keys.
2. rename: every outcome, reason, note reason, queue and floor field in the bridged policy (and the account rows) gets
   a new name; the 13 public sequences are replayed and every value the reducer sends (close outcome/reason, add_note
   reason, transfer queue) must be one of the NEW names, never an original one.
"""
import copy, json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import FIX, POL, TOPICS

BANNED = ["not_reached", "no_promise", "service_error", "no_callback", "minimum_payment", "instalment_amount",
          "not_verified", "transferred"]
# not banned on purpose: 'refused' and 'paid' (product statuses of contract §2), 'wrong_number' (ev payload value of
# contract §1.2), 'callback'/'promise' (event kind and operation names), slot names. The rename replay below proves
# none of them is ever SENT as a brief value.


def grep():
    bad = []
    for f in ("reducer.py", "event_field.py"):
        src = open(os.path.join(ROOT, "builder", "engine", f)).read()
        for b in BANNED:
            for m in re.finditer(re.escape(b), src):
                if src[max(0, m.start() - 3):m.start()] == "on_":   # the contract hook point on_no_promise
                    continue
                line = src[:m.start()].count("\n") + 1
                bad.append(f"{f}:{line}: {b}")
    return bad


def renamed(policy):
    """Rename every brief value the reducer may send; returns (policy', mapping old->new)."""
    p = copy.deepcopy(policy)
    mp = dict()
    def nm(v):
        if v in (None, "", "none", "null"):
            return v
        mp.setdefault(v, "zz_" + str(v))
        return mp[v]
    for row in (p.get("closing") or {}).get("table") or []:
        row["outcome"], row["reason"] = nm(row.get("outcome")), nm(row.get("reason"))
    for k, v in ((p.get("closing") or {}).get("slots") or {}).items():
        if isinstance(v, dict):
            v["outcome"], v["reason"] = nm(v.get("outcome")), nm(v.get("reason"))
    for sec in ("events", "who_rules"):
        for row in p.get(sec) or []:
            row["outcome"], row["reason"], row["note_reason"] = nm(row.get("outcome")), nm(row.get("reason")), nm(row.get("note_reason"))
    for k in ("before_who", "before_verified"):
        h = (p.get("hangup_default") or {}).get(k)
        if isinstance(h, dict):
            h["outcome"], h["reason"] = nm(h.get("outcome")), nm(h.get("reason"))
    for sec in ("transfer",):
        qm = (p.get(sec) or {}).get("queue_map") or {}
        for k in list(qm):
            qm[k] = nm(qm[k])
        p[sec]["pre_verification_queues"] = [nm(q) for q in (p[sec].get("pre_verification_queues") or [])]
    for t, fb in ((p.get("products") or {}).get("floor_by_type") or {}).items():
        if isinstance(fb, dict) and fb.get("field"):
            fb["field"] = "zz_" + fb["field"]
    return p, mp


def replay_renamed():
    problems = []
    for c in FIX["cases"]:
        pol, mp = renamed(POL[c["policy"]])
        old = set(mp)
        new = set(mp.values())
        cv = c["call_variables"]
        st = R.init_state(pol, cv)
        for s in c["steps"]:
            if s["source"] == "user":
                st["tok"] = s["event_fields"]["n"]
                ev = R.parse_event(s["event"], st, TOPICS)
                st, act = R.step(pol, st, ev, None, c["now"], cv)
                st["last_tok"] = s["event_fields"]["n"]
            else:
                te = copy.deepcopy(s["tool_event"])
                if isinstance(te.get("data"), dict) and te["data"].get("products"):
                    for row in te["data"]["products"]:
                        for f in ("minimum_payment", "instalment_amount"):
                            if f in row:
                                row["zz_" + f] = row.pop(f)
                st, act = R.step(pol, st, None, te, c["now"], cv)
            sent = []
            if act["type"] == "close":
                sent = [act.get("outcome"), act.get("reason")]
            if act["type"] == "call_tool" and act["tool"] in ("add_note", "transfer_to_agent"):
                sent = [act["args"].get("reason"), act["args"].get("queue")]
            if act["type"] == "call_tool" and act["tool"] == "create_promise":
                exp = s["action"]["args"]["amount"]
                if abs(float(act["args"]["amount"]) - float(exp)) > 0.005:
                    problems.append(f"{c['id']} step {s['step']}: floor not read from the renamed field ({act['args']['amount']} != {exp})")
            for v in sent:
                if v is None:
                    continue
                if v in old or v not in new:
                    problems.append(f"{c['id']} step {s['step']}: sent {v!r}, not a renamed policy value")
    return problems


if __name__ == "__main__":
    g = grep()
    print("grep:", "clean" if not g else g)
    r = replay_renamed()
    print("renamed-policy replay:", "clean" if not r else "")
    for x in r[:20]:
        print("   ", x)
    sys.exit(1 if g or r else 0)
