"""Binding assist (builder/binding_assist.py) and signal S3.

    python3 tests/test_binding_assist.py [--live]
A kit-OAS variant renames the product's past_due to 'outstanding' and days_late to 'age' (names no shape rule binds).
Offline: a proposal is accepted only when the path exists with the right shape; a wrong shape and a missing path are
rejected; build() saves after an accepted assist and exits 2 with S3 when facts stay unbound. --live: one real call.
"""
import copy, json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import binding_assist as BA
from builder.policy_bridge import to_reducer

OAS = os.path.join(ROOT, "tools", "openapi.json")
POLICY = json.load(open(os.path.join(ROOT, "tests", "e2e-int", "submission", "brief-a.extracted.json")))
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def variant(path):
    d = json.load(open(OAS))
    for p, ops in d["paths"].items():
        if p.endswith("get_account"):
            for op in ops.values():
                rs = op["responses"]
                s = rs[next(c for c in rs if str(c).startswith("2"))]["content"]["application/json"]["schema"]
                arr = next(v for v in s["properties"].values() if v.get("type") == "array")
                ip = arr["items"]["properties"]
                ip["outstanding"] = dict(ip.pop("past_due"), description="what the customer owes on this product now")
                ip["age"] = dict(ip.pop("days_late"), description="days since the due date")
    json.dump(d, open(path, "w"), indent=1)
    return path


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    try:
        oas = variant(os.path.join(tmp, "renamed.json"))
        rp, _ = to_reducer(copy.deepcopy(POLICY), oas, [])
        miss = BA.core_missing(rp)
        check(("get_account", "past_due") in miss and ("get_account", "days_late") in miss, f"shape rules leave them unbound: {miss}")
        good = lambda prompt: json.dumps({"paths": {"get_account.past_due": "item.outstanding", "get_account.days_late": "item.age"}})
        rp2, rep = BA.assist(rp, oas, "", ask=good)
        check(rep["accepted"] == {"get_account.past_due": "item.outstanding", "get_account.days_late": "item.age"} and not rep["still_missing"],
              f"good proposals accepted: {rep}")
        bad = lambda prompt: json.dumps({"paths": {"get_account.past_due": "item.product_id", "get_account.days_late": "item.nope"}})
        rp3, rep3 = BA.assist(rp, oas, "", ask=bad)
        check(set(rep3["rejected"]) == {"get_account.past_due", "get_account.days_late"} and len(rep3["still_missing"]) == 2,
              f"a wrong shape and a missing path are rejected: {rep3['rejected']}")
        from builder.generator import generate
        from builder.selftest import run_selftest
        from builder.validate_workflow import validate
        check(not validate(generate(rp2, oas), rp2, oas), "the assisted policy passes the validator")
        st = run_selftest(rp2, oas)
        check(st["passed"] == st["scenarios"], f"self-test with a bank answering only 'outstanding'/'age': {st['passed']}/{st['scenarios']}"
              f" {json.dumps(st.get('failures'))[:200]}")
        d = json.load(open(oas))
        for p_, ops in d["paths"].items():          # past_due renamed only: the self-test must be green
            if p_.endswith("get_account"):
                for op in ops.values():
                    rs = op["responses"]
                    s = rs[next(c for c in rs if str(c).startswith("2"))]["content"]["application/json"]["schema"]
                    ip = next(v for v in s["properties"].values() if v.get("type") == "array")["items"]["properties"]
                    ip["days_late"] = ip.pop("age")
        oas_pd = os.path.join(tmp, "pd_only.json")
        json.dump(d, open(oas_pd, "w"))
        rp5, _ = to_reducer(copy.deepcopy(POLICY), oas_pd, [])
        rp5, _ = BA.assist(rp5, oas_pd, "", ask=lambda pr: json.dumps({"paths": {"get_account.past_due": "item.outstanding"}}))
        st5 = run_selftest(rp5, oas_pd)
        check(st5["passed"] == st5["scenarios"], f"self-test, past_due bound by the assist to 'outstanding': {st5['passed']}/{st5['scenarios']}")
        # build(): assist accepted -> exit 0; assist useless -> S3, exit 2
        from builder.build import MockFreya, build
        import builder.binding_assist as mod
        V3 = os.path.join(ROOT, "tests", "policy_eval", "v3")
        ex = lambda b, o, tp, r_, sink, dl: (copy.deepcopy(POLICY), json.load(open(os.path.join(V3, "run4", "brief-a.report.json"))))
        real = mod.assist
        try:
            mod.assist = lambda rp_, o, bt, sink, dl: real(rp_, o, bt, ask=good)
            r = build([os.path.join(ROOT, "briefs", "brief-a.md")], oas, "ba", MockFreya(), os.path.join(tmp, "sub"), os.path.join(tmp, "tr"), 2, 1500, ex)
            check(r["exit_code"] == 0, f"build: assist accepted -> exit 0 ({r.get('fallback_reason')})")
            mod.assist = lambda rp_, o, bt, sink, dl: real(rp_, o, bt, ask=bad)
            r = build([os.path.join(ROOT, "briefs", "brief-a.md")], oas, "ba2", MockFreya(), os.path.join(tmp, "sub2"), os.path.join(tmp, "tr"), 2, 1500, ex)
            check(r["exit_code"] == 2 and r["signal"] == "S3" and r["next"] == "L3", f"build: still unbound -> S3, next L3 ({r.get('core_unbound')})")
        finally:
            mod.assist = real
        if "--live" in sys.argv:
            rp4, rep4 = BA.assist(rp, oas, open(os.path.join(ROOT, "briefs", "brief-a.md")).read())
            print("   live:", json.dumps(rep4))
            check(rep4["accepted"].get("get_account.past_due") == "item.outstanding" and rep4["accepted"].get("get_account.days_late") == "item.age",
                  "live: the real call binds outstanding/age")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
