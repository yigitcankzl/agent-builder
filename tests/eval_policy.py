"""Evaluate builder/policy_extract.py against Cursor's independent brief fixtures (tests/fixtures/briefs).

    python3 tests/eval_policy.py            # extract all (4 in parallel), then diff
    python3 tests/eval_policy.py --reuse    # diff the outputs already in runs/policy/
Runs brief A, A+B, mut-01..05 and raw-a. Brief A and A+B have no expected file: they report extraction only.
Core fields diffed: holidays, business days, deadline bands, attempts, floor rule, identity questions and limit,
outcome table, required sentences, callback window; raw-a also checks every memo override was detected.
"""
import concurrent.futures as cf, json, os, re, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.policy_extract import extract

FX = os.path.join(ROOT, "tests", "fixtures", "briefs")
OUT = os.path.join(ROOT, "runs", "policy")
RUNS = {"brief-a": [os.path.join(ROOT, "briefs", "brief-a.md")],
        "brief-ab": [os.path.join(ROOT, "briefs", "brief-a.md"), os.path.join(ROOT, "briefs", "brief-b.md")],
        **{f"mut-0{i}": [os.path.join(FX, f"mut-0{i}.md")] for i in range(1, 6)},
        "raw-a": [os.path.join(FX, "raw-a")]}
# Naming the fixtures use that differs from the tool API enum (reported, not silently matched)
FIXTURE_ALIASES = {"phone_last_four": "phone_last4"}


def norm_text(s):
    s = re.sub(r"\{+\s*(\w+)\s*\}+", r"{\1}", str(s))
    return re.sub(r"\s+", " ", s.strip().strip('"').strip("“”")).lower()


def ptype(t):
    return re.sub(r"[\s-]+", "_", str(t).strip().lower())


def ours_view(p):
    """Our policy -> the fixtures' shape (core fields only)."""
    bands = (p.get("deadline") or {}).get("bands") or []
    floor = {}
    for t, r in ((p.get("products") or {}).get("floor_by_type") or {}).items():
        if r.get("kind") == "percent_of_past_due":
            floor[ptype(t)] = ("percent_of_past_due", float(r.get("percent")), str(r.get("round", "")).split("_")[0])
        else:
            floor[ptype(t)] = ("account_field", r.get("field"))
    cb = (p.get("writes") or {}).get("callback") or {}
    return {
        "holidays": sorted((p.get("business_days") or {}).get("holidays") or []),
        "business_weekdays": sorted((p.get("business_days") or {}).get("weekdays") or []),
        "deadline_bands": [(b.get("min_days_late"), b.get("max_days_late"), b.get("days")) for b in bands],
        "persuasion_attempts": [b.get("attempts") for b in bands],
        "floor_rule": floor,
        "identity_questions": [q.get("field") for q in (p.get("identity") or {}).get("questions") or []],
        "identity_wrong_answer_limit": (p.get("identity") or {}).get("max_wrong"),
        "outcome_table": sorted({(r.get("outcome"), r.get("reason") or None) for r in (p.get("closing") or {}).get("table") or []}, key=str),
        "required_exact_sentences": sorted({norm_text(s.get("text")) for s in (p.get("sentences") or {}).values() if isinstance(s, dict)}),
        "callback_window": (cb.get("days"), cb.get("start"), cb.get("end"), cb.get("inclusive"), cb.get("after_now")),
    }


def expected_view(e):
    v = lambda k: (e.get(k) or {}).get("value")
    floor = {}
    for t, r in (v("floor_rule") or {}).items():
        if r.get("type") == "percent_of_past_due":
            floor[ptype(t)] = ("percent_of_past_due", float(r.get("percent")), str(r.get("round", "")).split("_")[0])
        else:
            floor[ptype(t)] = ("account_field", r.get("field"))
    cb = v("callback_window") or {}
    idn = v("identity") or {}
    return {
        "holidays": sorted(v("holidays") or []),
        "business_weekdays": sorted(v("business_weekdays") or []),
        "deadline_bands": [(b["min_days_late"], b["max_days_late"], b["business_days_after_today"]) for b in v("deadline_bands") or []],
        "persuasion_attempts": [(v("persuasion_attempts") or {}).get(b["band"]) for b in v("deadline_bands") or []],
        "floor_rule": floor,
        "identity_questions": list(idn.get("questions") or []),
        "identity_wrong_answer_limit": v("identity_wrong_answer_limit"),
        "outcome_table": sorted({(r["outcome"], r.get("reason") or None) for r in v("outcome_table") or []}, key=str),
        "required_exact_sentences": sorted({norm_text(s["text"]) for s in v("required_exact_sentences") or []}),
        "callback_window": (cb.get("eligible_days"), cb.get("time_start"), cb.get("time_end"), cb.get("times_inclusive"), cb.get("must_be_later_than_now")),
    }


def diff(ours, exp):
    out, notes = {}, []
    for k, ev in exp.items():
        ov = ours.get(k)
        if k == "identity_questions":
            mapped = [FIXTURE_ALIASES.get(x, x) for x in ev]
            if mapped != ev and ov == mapped:
                notes.append(f"identity: fixture says {ev}, the tool API enum says {mapped}; ours follows the tool API")
                continue
        if k == "required_exact_sentences":
            missing = [s for s in ev if s not in ov]
            if missing:
                out[k] = {"missing": missing, "extra": [s for s in ov if s not in ev]}
            continue
        if ov != ev:
            out[k] = {"ours": ov, "expected": ev}
    return out, notes


def superseded_check(policy, exp):
    """Every expected override must appear in ours: same rule area and the new value present."""
    ours = policy.get("superseded") or []
    blob = [json.dumps(s).lower() for s in ours]
    res = []
    sr = exp.get("superseded_rules") or []
    for e in (sr.get("value", []) if isinstance(sr, dict) else sr):
        # detected = one of our supersession entries carries the expected new value in its new_value field
        nv = e.get("new_value")
        want = sorted(nv) if isinstance(nv, list) else norm_text(nv)
        hit = False
        for s in ours:
            got = s.get("new_value")
            if isinstance(nv, list) and isinstance(got, list):
                hit |= sorted(got) == want
            elif not isinstance(nv, list):
                hit |= norm_text(got) == want or (isinstance(got, (int, float)) and str(got) == str(nv))
        res.append((e["rule"], "detected" if hit else "NOT DETECTED (no entry with the new value)"))
    return res


def run_one(name):
    policy, report = extract(RUNS[name], os.path.join(ROOT, "tools", "openapi.json"), os.path.join(OUT, "trace.jsonl"))
    json.dump(policy, open(os.path.join(OUT, name + ".json"), "w"), indent=1)
    json.dump(report, open(os.path.join(OUT, name + ".report.json"), "w"), indent=1)
    return name


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if "--reuse" not in sys.argv:
        t0 = time.time()
        with cf.ThreadPoolExecutor(4) as ex:
            for f in cf.as_completed([ex.submit(run_one, n) for n in RUNS]):
                print("extracted", f.result(), f"{time.time() - t0:.0f}s", flush=True)
    total_core, total_ok = 0, 0
    for name in RUNS:
        p = json.load(open(os.path.join(OUT, name + ".json")))
        r = json.load(open(os.path.join(OUT, name + ".report.json")))
        line = (f"\n== {name}: {r['seconds']}s, quotes rejected {r['quotes_rejected']} repaired {r['quotes_repaired']} "
                f"unverified {r['quotes_unverified']}, unmapped {len(r['unmapped'])}, superseded {len(r['superseded'])}, "
                f"fallback {r['fallback_required']}, errors {len(r['errors'])}, oas warnings {len(r['oas_warnings'])}")
        print(line)
        for w in r["oas_warnings"]:
            print("   oas:", w)
        exp_path = os.path.join(FX, name + ".expected.json")
        if not os.path.exists(exp_path):
            print("   (no expected file) core:", json.dumps(ours_view(p))[:600])
            continue
        e = json.load(open(exp_path))
        d, notes = diff(ours_view(p), expected_view(e))
        n = len(expected_view(e))
        total_core += n; total_ok += n - len(d)
        print(f"   core fields exact: {n - len(d)}/{n}")
        for k, v in d.items():
            print(f"   DIFF {k}: {json.dumps(v)[:500]}")
        for x in notes:
            print("   note:", x)
        if e.get("superseded_rules"):
            for rule, verdict in superseded_check(p, e):
                print(f"   supersession {rule}: {verdict}")
    print(f"\nTOTAL core fields exact: {total_ok}/{total_core}")
