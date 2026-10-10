"""Policy -> reducer bridge evaluation. No model calls: uses the saved extractions of two runs per brief
(tests/policy_eval/*.policy.json = run 2, tests/policy_eval/run3/*.policy.json = run 3).

    python3 tests/eval_bridge.py
1. Cross-check the bridged A and A+B policies against Cursor's tests/fixtures/reducer/public_sequences.json:
   per product band, deadline, attempts cap, floor and spoken name (`derived`), and the ledger's outcome/reason,
   transfer queues, note reasons and callback times.
2. Unmapped rules per brief: normalised, de-duplicated, stable across both runs or not.
3. api_mismatch entries per brief.
"""
import datetime, json, math, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine.dates import deadline_for
from builder.policy_bridge import consolidate_unmapped, to_reducer
from builder.policy_extract import oas_summary

OAS = os.path.join(ROOT, "tools", "openapi.json")
EV = os.path.join(ROOT, "tests", "policy_eval")
BRIEFS = ["brief-a", "brief-ab", "mut-01", "mut-02", "mut-03", "mut-04", "mut-05", "raw-a"]


RUN_DIRS = [d for d in sys.argv[1:] if not d.startswith("-")] or [EV, os.path.join(EV, "run3")]


def runs(name):
    """One policy per run directory (default: run 2 and run 3; or pass the run directories as arguments)."""
    out = []
    for d in RUN_DIRS:
        f = os.path.join(d, name + ".policy.json")
        out.append(json.load(open(f if os.path.exists(f) else os.path.join(d, name + ".json"))))
    return out


# Independent expectations for the persuasion plan: brief A from Cursor's reducer README (choice 8: attempt 1 =
# last business day of this week, full or the floor if already too much; attempt 2 = the floor on the deadline),
# mut-03 from its fixture (early 0 attempts, late 3; the third attempt is quoted in mut-03.md).
PLAN_EXPECTED = {
    "brief-a": {"early": [("last_business_day_this_week", "floor_if_too_much_else_full")],
                "late": [("last_business_day_this_week", "floor_if_too_much_else_full"), ("deadline", "floor")]},
    "mut-03": {"early": [],
               "late": [("last_business_day_this_week", "floor_if_too_much_else_full"), ("deadline", "floor"),
                        ("last_business_day_this_week", "floor")]}}
PLAN_EXPECTED["brief-ab"] = PLAN_EXPECTED["brief-a"]


def plan_of(p):
    return {b: [(s.get("date_rule"), s.get("amount_rule")) for s in steps] for b, steps in ((p.get("attempts") or {}).get("plan") or {}).items()}


def derive(rp, prod, today):
    bands = rp["deadline"]["bands"]
    dl = prod["days_late"]
    band = next((b for b in bands if b.get("min_days_late", 0) <= dl <= b["max_days_late"]), None)
    fr = rp["products"]["floor_by_type"].get(prod["type"]) or {}
    if fr.get("kind") == "percent_of_past_due":
        floor = float(math.ceil(prod["past_due"] * float(fr["percent"]) / 100)) if str(fr.get("round", "")).startswith("up") else round(prod["past_due"] * float(fr["percent"]) / 100, 2)
    else:
        floor = float(prod.get(fr.get("field"), "nan"))
    tpl = rp["products"].get("naming_by_type", {}).get(prod["type"], "")
    try:
        name = tpl.format(**prod)
    except (KeyError, IndexError):
        name = tpl
    return {"band": band and band.get("name"), "deadline": deadline_for(today, dl, rp).isoformat(),
            "attempts_cap": band and band.get("attempts"), "floor": floor, "spoken_name": name}


def cross_check(rp, case, oas):
    out = []
    today = datetime.date.fromisoformat(case["now"][:10])
    for prod, exp in zip(case["account"], case["derived"]):
        got = derive(rp, prod, today)
        for k in ("band", "deadline", "attempts_cap", "floor", "spoken_name"):
            if got[k] != exp[k]:
                out.append(f"{case['id']} {prod['product_id']} {k}: ours {got[k]!r} fixture {exp[k]!r}")
    led = case["ledger"]
    pairs = {(r["outcome"], r.get("reason")) for r in rp["closing"]["table"]}
    if (led["outcome"], led["reason"]) not in pairs:
        out.append(f"{case['id']} ledger outcome {(led['outcome'], led['reason'])} not in our closing table")
    queues = set(((rp.get("writes") or {}).get("transfer") or {}).get("queue_map", {}).values())
    for t in led["transfers"]:
        if t["queue"] not in queues:
            out.append(f"{case['id']} transfer queue {t['queue']!r} not in our queue_map {sorted(queues)}")
    note_enum = oas.get("add_note", {}).get("reason") or []
    for n in led["notes"]:
        if n["reason"] not in note_enum:
            out.append(f"{case['id']} note reason {n['reason']!r} not in add_note enum")
    cb = (rp.get("writes") or {}).get("callback") or {}
    for c in led["callbacks"]:
        if not (cb.get("start", "00:00") <= c["time"] <= cb.get("end", "23:59")):
            out.append(f"{case['id']} callback {c['time']} outside our window {cb.get('start')}-{cb.get('end')}")
    return out


if __name__ == "__main__":
    oas = oas_summary(OAS)
    seq = json.load(open(os.path.join(ROOT, "tests", "fixtures", "reducer", "public_sequences.json")))["cases"]
    print("== 1. cross-check against tests/fixtures/reducer/public_sequences.json (fd1409a)")
    for name, pol in (("A", "brief-a"), ("A+B", "brief-ab")):
        for i, p in enumerate(runs(pol), 1):
            rp, rep = to_reducer(p, OAS)
            cases = [c for c in seq if c["policy"] == name]
            bad = [m for c in cases for m in cross_check(rp, c, oas)]
            n = sum(len(c["derived"]) * 5 + 1 for c in cases)
            print(f"   {pol} run {i}: {len(cases)} cases, {n - len(bad)}/{n} checks match" + ("" if not rep["errors"] else f", bridge errors {rep['errors']}"))
            for m in bad:
                print("      MISMATCH", m)
    print("\n== 2. unmapped rules (two runs, normalised, de-duplicated)")
    stable_all = {}
    for b in BRIEFS:
        stable, unstable = consolidate_unmapped(runs(b))
        stable_all[b] = stable
        print(f"   {b}: stable {len(stable)}, unstable {len(unstable)}")
        for s in stable:
            print(f"      stable: {s['quote'][:110]!r}")
    print("\n== 3. api_mismatch (bridged run 2)")
    for b in BRIEFS:
        rp, rep = to_reducer(runs(b)[0], OAS, stable_all[b])
        print(f"   {b}: {len(rep['api_mismatch'])} mismatch, {len(rp['events'])} topics, {len(rp['who_rules'])} who rules, errors {len(rep['errors'])}")
        for m in rep["api_mismatch"]:
            print(f"      api_mismatch {m['policy_path']} ({m['field']}): {m['value']!r} -> fallback {m['fallback']!r}")
        print(f"      hangup_default {json.dumps({k: v for k, v in rp['hangup_default'].items() if k != 'source'})}, "
              f"pre-verification queues {rp['transfer']['pre_verification_queues']}, notes enabled {rp['writes']['notes']['enabled']}, "
              f"who {[x[1] for x in rep['who']]}")
    print("\n== 4. persuasion plan (attempts.plan) per run")
    for b in BRIEFS:
        for i, p in enumerate(runs(b), 1):
            got = plan_of(p)
            flags = {f: (p.get("attempts") or {}).get(f, {}).get("value") for f in ("flat_refusal_uses_attempt", "proposal_never_refusal", "no_repeat_refused_offer", "stop_when_exhausted")}
            exp = PLAN_EXPECTED.get(b)
            verdict = "" if exp is None else (" MATCH" if got == exp else f" DIFF expected {exp}")
            print(f"   {b} run {i}: {got} flags {flags}{verdict}")
        for n in rep["notes"]:
            print("      note:", n[:200])
