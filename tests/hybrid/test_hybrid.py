"""Offline check of the wired gate tools, run the way the platform runs them (args in vars['<tool>_args.<name>'],
get_account flattened into get_account_response.data.*), plus the create_promise pre hook.

    python3 tests/hybrid/test_hybrid.py
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from builder import hybrid

WF = json.load(open(os.path.join(ROOT, "tests", "hybrid", "hybrid-raw-4.workflow.json")))
HOST = next(n for n in WF["nodes"].values() if any(t["function"]["name"] == "confirm" for t in n.get("tools") or []))
CODE = {t["function"]["name"]: t["function"]["parameters"]["properties"]["code"]["default"] for t in HOST["tools"] if "code" in t["function"]["parameters"]["properties"]}
CP = next(t for t in HOST["tools"] if t["function"]["name"] == "create_promise")

# raw-4: now Wed 14 Oct 2026; late band (11-40 days): deadline Thu 15 Oct, two attempts, floor 30% (2125.10 -> 637.53)
V = {"now": "2026-10-14T11:00", "get_account_response.data.ok": True}
for k, x in dict(product_id="p1", type="personal_loan", past_due=2125.10, days_late=20, instalment_amount=400).items():
    V["get_account_response.data.products.0." + k] = x
for k, x in dict(product_id="p2", type="credit_card", past_due=420.0, days_late=5, minimum_payment=35).items():
    V["get_account_response.data.products.1." + k] = x      # early band: deadline Wed 21 Oct, one attempt


def call(tool, **args):
    for k in hybrid.GATE_IN[tool]:
        V.pop(f"{tool}_args.{k}", None)
    V.update({f"{tool}_args.{k}": v for k, v in args.items()})
    exec(CODE[tool], {"vars": V})
    return {k: V.get(k) for k in ("gate_status", "gate_ok", "gate_say", "gate_out_date", "gate_out_amount", "gate_new", "gate_error")}


def pre():
    cfg = {"url": "https://freya-bank-mock.freyavoice.workers.dev/v1/create_promise", "body": {"customer_id": "c", "product_id": "x", "amount": 1, "date": "2026-01-01"}}
    exec(CP["pre_process_code"], {"vars": V, "config": cfg})
    return cfg


checks = []
def ok(name, cond, got):
    checks.append(cond)
    print("ok  " if cond else "FAIL", name, "" if cond else json.dumps(got)[:300])


r = call("check_terms", gate_product="p2", gate_date="2026-10-16", gate_amount="420")
ok("early: holiday Fri 16 Oct is blocked, Mon 19 Oct said", r["gate_status"] == "non_business" and r["gate_out_date"] == "2026-10-19" and r["gate_new"] == "yes" and "16 October" in r["gate_say"], r)
r = call("check_terms", gate_product="p1", gate_date="2026-10-16", gate_amount="2125.10")
ok("late: Fri 16 Oct is after the late deadline -> Thu 15 Oct", r["gate_status"] == "after_deadline" and r["gate_out_date"] == "2026-10-15", r)
r = call("check_terms", gate_product="p1", gate_date="2026-11-06", gate_amount="2125.10")
ok("after the late deadline -> the deadline Thu 15 Oct", r["gate_status"] == "after_deadline" and r["gate_out_date"] == "2026-10-15", r)
r = call("check_terms", gate_product="p1", gate_date="2026-10-15", gate_amount="2125.10")
ok("Thu 15 Oct full amount passes, nothing to say", r["gate_status"] == "ok" and r["gate_ok"] == "yes" and r["gate_new"] == "no", r)
offers = [call("next_offer", gate_product="p1", gate_event=e) for e in ("first", "flat", "flat", "flat")]
ok("late band: two offers, then exhausted, no extra offer", [o["gate_status"] for o in offers][:2] == ["offer", "offer"] and offers[2]["gate_status"] == "exhausted" and offers[3]["gate_status"] == "exhausted" and not offers[3]["gate_say"], offers)
ok("create_promise with no read-back is blocked", "blocked.invalid" in pre()["url"], V.get("gate_status"))
r = call("confirm", gate_action="readback", gate_terms="p1:2125.10:2026-10-15")
ok("read-back spoken with the confirm question", r["gate_status"] == "readback" and r["gate_new"] == "yes" and V["rb_answer"] == "other", r)
r = call("confirm", gate_action="yes")
ok("confirm yes with no yes heard is stale", r["gate_status"] == "stale" and r["gate_ok"] == "no", r)
call("confirm", gate_action="next")
ok("then create_promise is still blocked", "blocked.invalid" in pre()["url"], V.get("gate_status"))
V["rb_answer"] = "yes"          # the extraction heard the customer's yes
r = call("confirm", gate_action="yes")
ok("yes after the read-back is granted", r["gate_status"] == "granted" and r["gate_ok"] == "yes", r)
r = call("confirm", gate_action="next")
cfg = pre()
ok("next -> create_promise passes with the granted terms", "blocked" not in cfg["url"] and cfg["body"]["amount"] == 2125.10 and cfg["body"]["date"] == "2026-10-15" and cfg["body"]["product_id"] == "p1", cfg)
r = call("confirm", gate_action="yes")
ok("a second yes is stale (granted once)", r["gate_status"] == "stale", r)
call("check_terms", gate_product="p1", gate_date="2026-10-15", gate_amount="2125.10")
ok("any later gate run closes the write permission", "blocked.invalid" in pre()["url"], V.get("gate_status"))
print("PASS" if all(checks) else "FAIL")
sys.exit(0 if all(checks) else 1)
