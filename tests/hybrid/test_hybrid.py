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
for k, x in dict(product_id="p2", type="credit_card", card_last4="4821", past_due=420.0, days_late=5, minimum_payment=35).items():
    V["get_account_response.data.products.1." + k] = x      # early band: deadline Wed 21 Oct, one attempt


def call(tool, **args):
    V.update({f"{tool}_args.{k}": "STALE" for k in hybrid.GATE_IN[tool]})    # the platform's lagging copy: ignored
    exec(CODE[tool], {"vars": V, "params": dict(args)})                      # the current args (probe2)
    return {k: V.get(k) for k in ("gate_status", "gate_ok", "gate_say", "gate_out_date", "gate_out_amount", "gate_new", "gate_error")}


def pre(pid="x"):
    cfg = {"url": "https://freya-bank-mock.freyavoice.workers.dev/v1/create_promise", "body": {"customer_id": "c", "product_id": pid, "amount": 1, "date": "2026-01-01"}}
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
ok("create_promise with no read-back is blocked", "not-confirmed" in pre()["url"], V.get("gate_status"))
r = call("confirm", gate_action="readback", gate_terms="p1:2125.10:2026-10-15")
ok("read-back spoken with the confirm question", r["gate_status"] == "readback" and r["gate_new"] == "yes" and V["rb_answer"] == "other", r)
ok("create_promise with no yes heard after the read-back is blocked", "not-confirmed" in pre()["url"], V.get("rb_answer"))
# live v6 PUB-07: the extractor's yes came at 0.593 and was discarded; the last utterance is the fallback
V["extractor.speech"] = "Yes, I confirm."
cfg = pre("p1")
ok("rb_answer still 'other' but the last utterance is a clear yes -> the write passes", "invalid" not in cfg["url"] and cfg["body"]["date"] == "2026-10-15", cfg)
V["extractor.speech"] = "Yes, but wait, can I change the date?"
ok("a yes with a change in it does not count", "not-confirmed" in pre("p1")["url"], V["extractor.speech"])
V["extractor.speech"] = "OK. Bye."
ok("'OK. Bye.' does not count", "not-confirmed" in pre("p1")["url"], V["extractor.speech"])
V.pop("extractor.speech")
ok("the min_confidence of rb_answer is 0.35", next(e for e in HOST["extraction_schema"] if e["name"] == "rb_answer")["min_confidence"] == 0.35, None)
r = call("confirm", gate_action="yes")
ok("a stray confirm yes/next is a no-op (live pieces: parallel yes+next raced)", r["gate_status"] == "noop" and not r["gate_say"], r)
call("confirm", gate_action="next")
ok("and grants nothing", "not-confirmed" in pre()["url"], V.get("gate_status"))
V["rb_answer"] = "yes"          # the extraction heard the customer's yes
cfg = pre("p1")
ok("yes heard -> create_promise passes with the read-back's terms (model's amount/date ignored)", "invalid" not in cfg["url"] and cfg["body"]["amount"] == 2125.10 and cfg["body"]["date"] == "2026-10-15" and cfg["body"]["product_id"] == "p1", cfg)
cfg = pre("p1")
ok("the bank-failure retry passes again with the same terms", "invalid" not in cfg["url"] and cfg["body"]["date"] == "2026-10-15", cfg)
call("check_terms", gate_product="p1", gate_date="2026-10-14", gate_amount="2125.10")
ok("different terms for that product void the read-back -> blocked", "not-confirmed" in pre("p1")["url"], V.get("gate_status"))
# live PUB-01 47b66117: read-back -> "a day later?" (change) -> "keep it as it was, yes I confirm" -> blocked -> read back again
r = call("confirm", gate_action="readback", gate_terms="p2:420:2026-10-19")
call("confirm", gate_action="change")
V["rb_answer"] = "yes"          # the extraction heard "yes, I confirm" right after the change
ok("a yes after a change (voided read-back) cannot write", "not-confirmed" in pre("p2")["url"], V.get("gate_status"))
r = call("confirm", gate_action="readback", gate_terms="p2:420:2026-10-19")
ok("read back again (as not_confirmed tells the model)", r["gate_status"] == "readback" and "19 October" in r["gate_say"] and V["rb_answer"] == "other", r)
V["rb_answer"] = "yes"
cfg = pre("p2")
ok("and the write goes through with p2 420 on 19 Oct", "invalid" not in cfg["url"] and cfg["body"]["product_id"] == "p2" and cfg["body"]["date"] == "2026-10-19", cfg)
call("confirm", gate_action="readback", gate_terms="p1:2125.10:2026-10-15|p2:420:2026-10-19")
V["rb_answer"] = "yes"
cfg = pre("credit_card")
ok("two products in the read-back + an unknown product_id -> wrong_product with the ids", "wrong-product-use-p1-or-p2.invalid" in cfg["url"], cfg)
# v8 write outcomes. post(vars, ok) runs the post hook; the platform's auto vars after a call are set by auto().
def post(vs, data_ok=None, code=200):
    res = {"status": "success", "status_code": code, "data": {"ok": data_ok}} if data_ok is not None else {"status": "error", "status_code": code}
    exec(CP["post_process_code"], {"result": res, "vars": vs})
    return res


def auto(vs, pid, data_ok=None, err=""):          # what the platform writes after the call (persisted by the platform)
    vs["create_promise_args.product_id"] = pid
    vs.pop("create_promise_response.data.ok", None)
    if data_ok is not None:
        vs["create_promise_response.data.ok"] = data_ok
        vs["create_promise_success_count"] = int(vs.get("create_promise_success_count") or 0) + 1
    vs["create_promise_response.error"] = err


def pre_on(vs, pid):
    cfg = {"url": "https://freya-bank-mock.freyavoice.workers.dev/v1/create_promise", "body": {"customer_id": "c", "product_id": pid, "amount": 1, "date": "2026-01-01"}}
    exec(CP["pre_process_code"], {"vars": vs, "config": cfg})
    return cfg


import copy as _copy
call("confirm", gate_action="readback", gate_terms="p2:420:2026-10-19")
V["rb_answer"] = "yes"
base = _copy.deepcopy(V)
for persist in (True, False):          # False: hook writes are lost; only the platform's auto vars carry the state
    tag = "hooks persist" if persist else "hooks do NOT persist"
    on = (lambda vs: vs) if persist else (lambda vs: _copy.deepcopy(vs))     # where a hook's writes land
    vs = _copy.deepcopy(base)
    ok(f"[{tag}] confirmed write passes", "invalid" not in pre_on(on(vs), "p2")["url"], None)
    post(on(vs), True); auto(vs, "p2", True)
    ok(f"[{tag}] success -> a second create_promise for p2 is blocked as already-recorded (not a failure)",
       "already-recorded" in pre_on(on(vs), "p2")["url"], vs.get("gate_written"))
    vs = _copy.deepcopy(base)
    pre_on(on(vs), "p2"); r1 = post(on(vs), False); auto(vs, "p2", False)
    ok(f"[{tag}] bank ok:false -> the bank's answer says retry once, and the retry passes",
       "once more" in r1.get("what_to_do_next", "") and "invalid" not in pre_on(on(vs), "p2")["url"], (r1, vs.get("gate_failed")))
    post(on(vs), False); auto(vs, "p2", False)
    ok(f"[{tag}] bank ok:false again -> the next call is blocked: bank-failed-again (service_error)",
       "bank-failed-again" in pre_on(on(vs), "p2")["url"], (vs.get("gate_failed"), vs.get("create_promise_success_count")))
    vs = _copy.deepcopy(base)
    pre_on(on(vs), "p2"); auto(vs, "p2", None, "Sandbox did not return a parseable result (returncode=0)")
    cfg = pre_on(on(vs), "p2")
    ok(f"[{tag}] uncertain (no parseable answer) -> never retried, treated as recorded",
       "outcome-unknown-treat-as-recorded" in cfg["url"] and any(x in pre_on(on(vs), "p2")["url"] for x in ("outcome-unknown", "already-recorded")), cfg["url"])
vs = _copy.deepcopy(base)
auto(vs, "p2", None, "DNS resolution failed for 'not-confirmed-read-back-and-ask-again.invalid'")
ok("our own block (a .invalid host) is not an uncertain write", "invalid" not in pre_on(vs, "p2")["url"], vs.get("gate_written"))
# live v8 raw-4 PUB-10 12706780: the bank's designed first failure is a non-2xx, reported as a transport error
BANK503 = "API request failed: {'ok': False, 'error': 'service unavailable, nothing was recorded'}"
for persist in (True, False):
    tag = "hooks persist" if persist else "hooks do NOT persist"
    on = (lambda vs: vs) if persist else (lambda vs: _copy.deepcopy(vs))
    vs = _copy.deepcopy(base)
    fc0 = int(vs.get("gate_blocked") or 0)        # the platform counts our earlier own blocks as failures too
    vs["create_promise_failure_count"] = fc0
    pre_on(on(vs), "p2"); auto(vs, "p2", None, BANK503); vs["create_promise_failure_count"] = fc0 + 1
    cfg = pre_on(on(vs), "p2")
    ok(f"[{tag}] a non-2xx bank answer ('nothing was recorded') is a definite failure: the retry passes", "invalid" not in cfg["url"] and cfg["body"]["date"] == "2026-10-19", cfg["url"])
    auto(vs, "p2", None, BANK503); vs["create_promise_failure_count"] = fc0 + 2
    ok(f"[{tag}] the second bank failure blocks: bank-failed-again", "bank-failed-again" in pre_on(on(vs), "p2")["url"], vs.get("gate_failed"))
vs = _copy.deepcopy(base)
fc0 = int(vs.get("gate_blocked") or 0)
vs["rb_answer"] = "no"; pre_on(vs, "p2"); vs["rb_answer"] = "yes"   # our own block (not confirmed): a transport error
vs["create_promise_failure_count"] = fc0 + 1
auto(vs, "p2", None, "DNS resolution failed for 'not-confirmed-read-back-and-ask-again.invalid'")
pre_on(vs, "p2"); auto(vs, "p2", None, BANK503); vs["create_promise_failure_count"] = fc0 + 2
ok("our own earlier block is not counted as a bank failure: the retry still passes", "invalid" not in pre_on(vs, "p2")["url"], (vs.get("gate_blocked"), vs.get("gate_failed")))
r = post(_copy.deepcopy(base), None, 503)
ok("a 5xx answered by the bank counts as a definite failure (retry message)", "once more" in r.get("what_to_do_next", ""), r)
# invented product ids (live proof 1): mapped to the real one, or rejected with the valid ids named
r = call("check_terms", gate_product="credit_card_4821", gate_date="2026-10-16", gate_amount="420")
ok("credit_card_4821 -> p2 (card_last4)", V["gate_product"] == "p2" and r["gate_status"] == "non_business", r)
r = call("check_terms", gate_product="personal loan", gate_date="2026-10-15", gate_amount="2125.10")
ok("'personal loan' -> p1 (type word)", V["gate_product"] == "p1" and r["gate_status"] == "ok", r)
r = call("check_terms", gate_product="2", gate_date="2026-10-19", gate_amount="420")
ok("'2' -> p2 (position)", V["gate_product"] == "p2", r)
r = call("check_terms", gate_product="prod_123", gate_date="2026-10-19", gate_amount="420")
ok("prod_123 -> rejected, gate_error names p1, p2", "p1, p2" in (r["gate_error"] or "") and r["gate_ok"] == "no", r)
r = call("confirm", gate_action="readback", gate_terms="cc_4821:420:2026-10-19")
ok("read-back terms cc_4821 -> p2", r["gate_status"] in ("readback", "repeat") and V["gate_terms"].startswith("p2:"), r)
# live brief-a talkative fails (PUB-05 3c70f50b, PUB-06 89957a2d): once-only lines, no persuasion after hardship, offer cap
offers = [call("next_offer", gate_product="p2", gate_event="first") for _ in range(3)]
ok("an open offer is re-said once, the next 'first' moves on (early band: exhausted, no third say)",
   [o["gate_status"] for o in offers] == ["offer", "offer", "exhausted"] and not offers[2]["gate_say"], offers)
exec(CODE["say_once"], {"vars": V, "params": {"line": "hardship"}})
ok("say_once hardship: allowed the first time", V["gate_status"] == "once_ok" and V["gate_np"] == "hardship", V["gate_status"])
exec(CODE["say_once"], {"vars": V, "params": {"line": "hardship"}})
ok("say_once hardship again: refused, told the close instead", V["gate_status"] == "already_said" and "no_promise/hardship" in V["gate_error"], V["gate_error"])
st_before = V["gate_st"]
r = call("next_offer", gate_product="p1", gate_event="first")
ok("next_offer after hardship: NO OFFER, nothing said, gate state unchanged", r["gate_status"] == "no_persuasion" and not r["gate_say"]
   and V["gate_st"] == st_before and "no_promise/hardship" in r["gate_error"], r)
V.pop("gate_np"); V["np_topic"] = "yes"          # the extraction heard job loss, the model never called say_once
r = call("next_offer", gate_product="p1", gate_event="first")
ok("np_topic=yes from the extraction alone also blocks the offer", r["gate_status"] == "no_persuasion", r)
spoken = [n["on_enter"]["text"] for n in WF["nodes"].values() if (n.get("on_enter") or {}).get("type") == "tts"]
ok("no 'call is recorded' in spoken lines (PUB-10 6ffe9fde judge: honesty word)", not any("call is recorded" in t.lower() for t in spoken), spoken)
# live v6 PUB-06 8c4f0608: after vars named _np_block/_st_backup appeared, every api_call hook failed to return
bad = [k for k, v in V.items() if k.startswith("_") or (isinstance(v, str) and v.startswith("{") and k not in ("gate_st", "gate_account"))]
ok("the gates write no var named _x and no JSON-object strings besides gate_st", not bad, bad)
print("PASS" if all(checks) else "FAIL")
sys.exit(0 if all(checks) else 1)
