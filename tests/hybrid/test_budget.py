"""Offline check of the v8 payload budget: every hook / gate print stays <= 9,000 chars and nothing the gates or the
workflow read is trimmed.

Tables: (1) the real var table of v6 PUB-06 8c4f0608 just before its first failing hook (7.1k, + the bank's response);
(2) a long talkative 3-product table (every tool called, headers, long extractor strings, system clocks).

    python3 tests/hybrid/test_budget.py
"""
import copy, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

WF = json.load(open(os.path.join(ROOT, "tests", "hybrid", "hybrid-raw-4.workflow.json")))
HOST = next(n for n in WF["nodes"].values() if any(t["function"]["name"] == "confirm" for t in n.get("tools") or []))
TOOLS = {t["function"]["name"]: t for t in HOST["tools"]}
CP = TOOLS["create_promise"]
CODE = {k: t["function"]["parameters"]["properties"]["code"]["default"] for k, t in TOOLS.items() if "code" in t["function"]["parameters"]["properties"]}
LIMIT = 9000
HEADERS = {"CF-RAY": "a48bf4eafbecd2a8-FRA", "Connection": "keep-alive", "Content-Length": "44", "Content-Type": "application/json",
           "Date": "Sun, 11 Oct 2026 06:55:00 GMT", "Server": "cloudflare", "alt-svc": 'h3=":443"; ma=86400',
           "Nel": '{"report_to":"cf-nel","success_fraction":0.0,"max_age":604800}',
           "Report-To": '{"group":"cf-nel","max_age":604800,"endpoints":[{"url":"a.nel.cloudflare.com/report/v4?s=' + "x" * 260 + '"}]}'}


def printed(vs, extra=None):
    return len("__CODE_EXEC_RESULT__") + len(json.dumps(dict(vars=vs, **(extra or {})), default=str))


def replay_table():
    c = json.load(open(os.path.join(ROOT, "tests", "hybrid", "fail-v6-pub06.json")))
    vt = None
    for k, x in enumerate(c["messages"]):
        if x.get("role") == "system":
            e = json.loads(x.get("message") or "{}")
            if e.get("event") == "function_call_error":
                break
            if e.get("variable_table"):
                vt = e["variable_table"]
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in vt.items()}


def long_table(base):
    vs = copy.deepcopy(base)
    for i, (pid, typ, due) in enumerate((("p1", "credit_card", 420.0), ("p2", "personal_loan", 2125.1), ("p3", "car_loan", 1250.0))):
        for f, v in dict(product_id=pid, type=typ, past_due=due, days_late=5 + i * 9, card_last4="48%02d" % i, minimum_payment=35.0,
                         instalment_amount=400, floor=due * 0.3, band="early", latest_promise_date="2026-10-21").items():
            vs[f"get_account_response.data.products.{i}.{f}"] = v
            vs[f"t_get_account_response.data.products.{i}.{f}"] = v
    for tool in ("verify_identity", "get_account", "create_promise", "schedule_callback", "transfer_to_agent", "check_terms", "next_offer", "confirm"):
        for h, v in HEADERS.items():
            vs[f"{tool}_response.header.{h}"] = v
        vs[f"{tool}_response.message"] = "Successfully executed POST request" if tool[0] != "c" else "Code executed successfully"
        vs[f"{tool}_response.data.what_to_do_next"] = "The account is loaded. Tell the customer each product and ask when they can pay. " * 2
        vs[f"{tool}_args.note"] = "x" * 120
    for k in range(40):
        vs[f"system.clock_{k}"] = "Sunday, October 11, 2026 at 09:55:00 AM Eastern Standard Time"
    vs["extractor.conversation"] = "user: I've been so busy with these deadlines that I haven't had a chance to look at my finances. " * 60
    vs["extractor.speech"] = "Yes, I confirm."
    return vs


ok_all = []
def ok(name, cond, got=""):
    ok_all.append(cond)
    print(("ok  " if cond else "FAIL"), name, "" if cond else str(got)[:300])


base = replay_table()
ok("the replayed 8c4f0608 table is the failing size (> 7,000 chars of vars)", printed(base) > 7000, printed(base))
must = {k: base[k] for k in base if k.startswith("gate_") and k != "gate_account"} | {k: base[k] for k in ("rb_answer", "customer_id", "now") if k in base}
for name, table in (("8c4f0608 replay", base), ("long talkative 3-product", long_table(base))):
    print(f"-- {name}: vars print {printed(table)} chars")
    # create_promise pre hook (prints config) and post hook (prints the bank's result with its headers)
    vs = copy.deepcopy(table)
    cfg = {"url": "https://freya-bank-mock.freyavoice.workers.dev/v1/create_promise", "method": "POST", "headers": {"Content-Type": "application/json"},
           "body": {"customer_id": vs.get("customer_id"), "product_id": "p1", "amount": 637.53, "date": "2026-10-15"}}
    exec(CP["pre_process_code"], {"vars": vs, "config": cfg})
    ok(f"{name}: create_promise pre hook print <= {LIMIT}", printed(vs, dict(config=cfg)) <= LIMIT, printed(vs, dict(config=cfg)))
    ok(f"{name}: gate vars, rb_answer, call vars kept", all(vs.get(k) == v for k, v in must.items() if k not in ("gate_written", "gate_failed", "gate_writing")),
       [k for k, v in must.items() if vs.get(k) != v])
    res = {"status": "success", "data": {"ok": True, "promise_id": "pr1", "what_to_do_next": "The promise is recorded. Say exactly: A confirmation email will be sent to the address on file."},
           "message": "Successfully executed POST request", "status_code": 200, "header": dict(HEADERS)}
    exec(CP["post_process_code"], {"vars": vs, "result": res})
    ok(f"{name}: create_promise post hook print <= {LIMIT}", printed(vs, dict(result=res)) <= LIMIT, printed(vs, dict(result=res)))
    ok(f"{name}: the write is marked (gate_written=p1) after the budget", vs.get("gate_written") == "p1", vs.get("gate_written"))
    # a gate run and an L3 api hook (close_call is a workflow-level tool)
    vs = copy.deepcopy(table)
    exec(CODE["check_terms"], {"vars": vs, "params": {"gate_product": "p1", "gate_date": "2026-10-15", "gate_amount": "637.53"}})
    ok(f"{name}: check_terms print <= {LIMIT} and the gate still answers", printed(vs) <= LIMIT and vs.get("gate_status") not in ("", "error"), (printed(vs), vs.get("gate_status"), vs.get("gate_error")))
    close = next(t for t in WF["tools"] if t["function"]["name"] == "close_call")
    vs = copy.deepcopy(table)
    cfg = {"url": "https://freya-bank-mock.freyavoice.workers.dev/v1/close_call", "body": {"customer_id": "c", "outcome": "promise"}}
    exec(close["pre_process_code"], {"vars": vs, "config": cfg})
    ok(f"{name}: close_call pre hook print <= {LIMIT}", printed(vs, dict(config=cfg)) <= LIMIT, printed(vs, dict(config=cfg)))
    for k in ("customer_id", "now"):
        ok(f"{name}: call var {k} kept", vs.get(k) == table.get(k), vs.get(k))
print("PASS" if all(ok_all) else "FAIL")
sys.exit(0 if all(ok_all) else 1)
