"""The hub's printed code_exec result on a long call (791ace3 live: raw-4/raw-5 closed right after get_account because the
6,000 cap dropped st and forced a close with an empty outcome).

    python3 -m tests.test_payload_budget
For the 5 rehearsal policies + A + A+B: a freshly generated workflow walked through a long call (identity, get_account
with 3 products, a long negotiation with chatter), with the platform's own vars added before every hub run (response
headers, clock strings, turn counters, messages). After every hub run: printed result <= RETURN_BUDGET, st intact, no
forced close (hub_error), and the engine never closes with an empty outcome.
"""
import builtins, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import graph_walk as G
from builder.generator import generate
from builder.engine.reducer import RETURN_BUDGET, returned_len
from tests.test_rehearsal import policy_for, W, YES, NO, FLAT, TOO, OTHER, DT, WD, CB

REHEARSAL = ["nightmare-1", "biz-1", "clean-1", "raw-2", "raw-1"]
HEADERS = {"Date": "Sat, 10 Oct 2026 23:46:16 GMT", "Content-Type": "application/json; charset=UTF-8",
           "Transfer-Encoding": "chunked", "Connection": "keep-alive", "Server": "cloudflare",
           "CF-RAY": "9a1b2c3d4e5f6a7b-IST", "Content-Encoding": "gzip", "alt-svc": 'h3=":443"; ma=86400',
           "Nel": '{"report_to":"cf-nel","success_fraction":0.0,"max_age":604800}',
           "Report-To": '{"group":"cf-nel","max_age":604800,"endpoints":[{"url":"https://a.nel.cloudflare.com/report/v4?s='
                        + "x" * 220 + '"}]}'}
SYSTEM = {"system.todays_date_en_est": "Saturday, October 10, 2026 at 7:46 PM EDT", "system.todays_date_en_cst":
          "Saturday, October 10, 2026 at 6:46 PM CDT", "system.iso_utc_now": "2026-10-10T23:46:16Z",
          "system.uuid4()": "0f0e0d0c-0b0a-4908-8706-050403020100", "system.todays_date_tr": "11 Ekim 2026 Pazar"}
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def platform_noise(wf, vars_):
    """What the platform keeps in vars and hands to every code_exec: per tool node its headers and message, per node
    its turn counters, the clock strings."""
    for nid in wf["nodes"]:
        vars_.setdefault(nid + ".current_turns", 0)
        vars_.setdefault(nid + ".total_turns", 3)
        vars_.setdefault(nid + "_response.message", "Successfully executed POST request")
        if nid.startswith("t_") and (nid + "_status_code") in vars_:
            for k, v in HEADERS.items():
                vars_.setdefault(nid + "_response.header." + k, v)
    vars_.update(SYSTEM)


def long_call(rp, case):
    idt = case["identity"]
    fields = [q["field"] for q in (rp.get("identity") or dict()).get("questions") or []]
    ids = ["kind=identity;also=none;st=complete;prod=;field=%s;ans=%s" % (f, idt.get(f, "")) for f in fields]
    talk = [NO, OTHER, OTHER, TOO, OTHER, WD("fri", also="reject"), OTHER, OTHER, FLAT, OTHER, DT(26, 10, also="reject"),
            OTHER, OTHER, YES, OTHER, YES, OTHER, OTHER]
    return ["n=kx;src=user;" + e for e in [W, YES] + ids + talk + [OTHER] * 6]


def run(name, rp, oas_path, case):
    wf = generate(rp, oas_path)
    w = wf.get("workflow", wf)
    rows = [dict(p, product_id="p%d" % i) for i, p in enumerate((case["products"] * 3)[:3], 1)]

    def bank(tool, body):
        if tool == "verify_identity":
            return 200, dict(ok=True, verified=True, all_verified=True, wrong_answers_left=3)
        if tool == "get_account":
            return 200, dict(ok=True, products=rows)
        return 200, dict(ok=True)

    worst, runs, probs = [0, 0], [0], []
    real = builtins.exec

    def hub_exec(code, env=None, *a):
        hub = isinstance(env, dict) and env.get("__name__") == "hub" and isinstance(env.get("vars"), dict)
        if hub:
            platform_noise(w, env["vars"])
            worst[1] = max(worst[1], returned_len(env["vars"]))
        r = real(code, env, *a) if env is not None else real(code)
        if hub and getattr(code, "co_filename", "") == "hub":
            v = env["vars"]
            runs[0] += 1
            n = returned_len(v)
            worst[0] = max(worst[0], n)
            st = v.get("st")
            if n > RETURN_BUDGET:
                probs.append("run %d printed %d > %d" % (runs[0], n, RETURN_BUDGET))
            if not (isinstance(st, str) and st.startswith("{")):
                probs.append("run %d: st lost (%r)" % (runs[0], str(st)[:40]))
            if v.get("route") == "close" and not v.get("close_outcome"):
                probs.append("run %d: close with an empty outcome" % runs[0])
        return r

    G.exec = hub_exec
    try:
        rep = G.walk(wf, json.load(open(oas_path)), dict(case["variables"], customer_id="c1"), long_call(rp, case), bank)
    finally:
        G.exec = real
    forced = [e for e in rep["errors"] if "over budget" in e]
    gets = [c for c in rep["calls"] if c["tool"] == "get_account"]
    check(not probs and not forced and gets and runs[0] > 10,
          "%s: %d hub runs, get_account %d, printed worst %d (in %d), budget %d %s" % (
              name, runs[0], len(gets), worst[0], worst[1], RETURN_BUDGET, (probs + forced)[:3]))
    return worst


if __name__ == "__main__":
    big = 0
    for b in REHEARSAL:
        rp = policy_for(b)
        cases = json.load(open(os.path.join(ROOT, "tests/fixtures/rehearsal/%s/cases.json" % b)))
        cases = cases if isinstance(cases, list) else cases["cases"]
        case = max(cases, key=lambda c: (len(c.get("products") or []), c["id"] != "PUB-02"))
        big = max(big, run(b, rp, os.path.join(ROOT, "tests/fixtures/rehearsal/%s/openapi.json" % b), case)[1])
    seq = json.load(open(os.path.join(ROOT, "tests/fixtures/reducer/public_sequences.json")))["cases"]
    case11 = next(c for c in seq if c["id"] == "PUB-11")
    acct = next(s["tool_event"]["data"] for s in case11["steps"] if s["source"] == "tool" and s["tool_event"]["node"] == "t_get_account")
    case = dict(variables=case11["call_variables"], identity=dict(date_of_birth="1985-03-14", phone_last4="4471"),
                products=[dict((k, v) for k, v in p.items() if k != "product_id") for p in acct["products"]])
    for name in ("brief-a", "brief-ab"):
        rp = json.load(open(os.path.join(ROOT, "tests/e2e-hon/submission/%s.policy.json" % name)))
        big = max(big, run(name, rp, os.path.join(ROOT, "tests/generated/walk/openapi.json"), case)[1])
    # the platform vars alone are over the old 6,000 cap: the replay is the live shape, not a toy
    check(big > 6000, "the hub's input with the platform vars reaches %d (> 6000)" % big)
    print("RESULT:", "PASS" if not fails else "FAIL (%d)" % len(fails))
    sys.exit(1 if fails else 0)
