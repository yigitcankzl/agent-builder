"""Measure the hub's printed code_exec payload. Local only: no Freya, no network.

The sandbox prints __CODE_EXEC_RESULT__ plus the vars JSON and cuts that stdout near 10,000
characters. This replays a fat variable table (response headers and stored sandbox errors, the
shape in sw-A-corrects PUB-06) through hub_reset and through 40 talkative hub turns.

    python3 probe/payload_budget.py [export.json]

An export is optional. When given, the largest vars dict on its messages is measured before and
after the same blanking the hub applies. Nothing is uploaded.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from builder.engine.reducer import RETURN_BUDGET, returned_len, hub_main, init_state, _dump
from builder.generator import hub_reset_code


def _vars_of(msg):
    v = msg.get("vars")
    return v if isinstance(v, dict) and "st" in v else None


def measure_export(path):
    c = json.load(open(path))
    best = None
    for m in c.get("messages") or []:
        v = _vars_of(m)
        if not v:
            continue
        n = returned_len(v)
        if best is None or n > best[0]:
            best = (n, v)
    if not best:
        print("export: no vars snapshots")
        return
    raw, v = best
    # the same blanks hub_main applies, without stepping the call
    from builder.engine.reducer import enforce_budget
    slim = dict(v)
    enforce_budget(slim)
    print("export %s" % os.path.basename(path))
    print("   largest printed payload before blanking: %d" % raw)
    print("   after enforce_budget: %d (budget %d)" % (returned_len(slim), RETURN_BUDGET))


def measure_turns(turns=40):
    pol = json.load(open(os.path.join(ROOT, "tests/generated/brief-a.reducer_policy.json")))
    tools = ["verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent"]
    promise = (((pol.get("closing") or {}).get("slots") or {}).get("promise") or {}).get("outcome") or ""
    code = hub_reset_code(tools, promise)
    st = init_state(pol, dict(customer_id="c_r", first_name="Ann", last_name="Lee", title="Ms", now="2026-10-14T11:00"))
    vars_ = dict(st=_dump(st, (",", ":")), route="say", route_ok="yes", ev_tok="kstart",
                 say_next="", farewell="Thank you. Goodbye.", close_outcome="not_reached", close_reason="unclear",
                 promise_recorded="no", promise_word=promise, now="2026-10-14T11:00", customer_id="c_r",
                 first_name="Ann", last_name="Lee", title="Ms",
                 **{"t_create_promise_response.data.ok": "true"})
    before = None
    worst = 0
    for i in range(turns):
        vars_["t_verify_identity_response.header.Report-To"] = "H" * 300
        vars_["t_get_account_response.header.Report-To"] = "H" * 300
        vars_["t_get_account_response.header.Nel"] = "N" * 80
        vars_["hub_response.message"] = "M" * 630
        vars_["hub_reset_response.message"] = "M" * 630
        vars_["hub_response.error"] = "E" * 120
        if before is None:
            before = returned_len(vars_)
        exec(compile(code, "hub_reset", "exec"), dict(vars=vars_, __name__="hub"))
        tok = str(vars_.get("ev_tok") or "kstart")
        vars_["ev"] = "n=%s;src=user;kind=other;also=none;st=none;prod=" % tok
        hub_main(vars_, pol)
        worst = max(worst, returned_len(vars_))
    print("simulated %d talkative turns (headers and error text restored every turn)" % turns)
    print("   fat table before hub_main blanks it: %d" % before)
    print("   worst printed payload after hub_main: %d (budget %d)" % (worst, RETURN_BUDGET))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        measure_export(sys.argv[1])
    measure_turns()
