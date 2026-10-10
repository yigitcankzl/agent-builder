"""Cursor's 10 OpenAPI mutations (fixtures-briefs eb5e8e7, tests/fixtures/openapi-mutations) through the bridge, the
generator, the validator and the self-test, compared with each expected.json. Offline: the brief A extraction saved
by the integration rebuild (tests/e2e-int) is the policy; for the code-list variants the codes.csv rows are given as
the extractor would quote them (aliases with their csv line) and the csv text is part of the brief text.

    python3 tests/test_oas_mutations.py [variant ...]
Expected notation -> ours: tool_results facts verified -> verified_this, wrong_answers_left -> wrong_left,
product_id -> id, floor.<type>; paths 'a.b' -> 'data.a.b', 'x[].y' (products array) -> 'item.y'; null = missing.
amount_encoding.factor 100 -> amount_scale 0.01; composed_fields -> composed_fields; tools -> tool_status.
"""
import copy, csv, io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.generator import generate
from builder.policy_bridge import to_reducer
from builder.selftest import run_selftest
from builder.validate_workflow import validate

FX = os.path.join(ROOT, "tests", "fixtures", "openapi-mutations")
POLICY = json.load(open(os.path.join(ROOT, "tests", "e2e-int", "submission", "brief-a.extracted.json")))
BRIEF = open(os.path.join(ROOT, "briefs", "brief-a.md")).read()
FACT = {"verified": "verified_this", "wrong_answers_left": "wrong_left", "product_id": "id"}


def our_path(p, products):
    if p is None:
        return None
    if "[]." in p:
        return "item." + p.split("[].", 1)[1]
    return "data." + p


def expected_results(exp):
    out = {}
    for tool, facts in (exp.get("tool_results") or {}).items():
        prod = facts.get("products")
        for fact, path in facts.items():
            if fact == "floor":
                for t, fp in (path or {}).items():
                    out[(tool, f"floor.{t}")] = our_path(fp, prod)
            else:
                out[(tool, FACT.get(fact, fact))] = our_path(path, prod)
    return out


def run(variant):
    d = os.path.join(FX, variant)
    exp = json.load(open(os.path.join(d, "expected.json")))
    oas = os.path.join(d, "openapi.json")
    pol = copy.deepcopy(POLICY)
    text = BRIEF
    for src in exp.get("sources") or []:
        raw = open(os.path.join(d, src)).read()
        text += "\n" + raw
        lines = raw.splitlines()
        for row in csv.DictReader(io.StringIO(raw)):
            if row.get("mapping") == "alias":
                line = next(l for l in lines if l.startswith(row["surface_form"] + ","))
                pol.setdefault("aliases", []).append({"field": row["api_field"], "brief_value": row["surface_form"],
                                                      "api_value": row["api_value"], "source": [{"file": src, "quote": line}]})
    rp, rep = to_reducer(pol, oas, [], text)
    wf = generate(rp, oas)
    errs = validate(wf, rp, oas)
    probs = []
    # tool_args
    for tool, roles in (exp.get("tool_args") or {}).items():
        ours = (rp.get("tool_args") or {}).get(tool) or {}
        for role, field in roles.items():
            if ours.get(role) != field:
                probs.append(f"tool_args.{tool}.{role}: ours {ours.get(role)!r} != expected {field!r}")
    # tool_results
    for (tool, fact), path in expected_results(exp).items():
        ours = ((rp.get("tool_results") or {}).get(tool) or {}).get(fact)
        if ours != path:
            probs.append(f"tool_results.{tool}.{fact}: ours {ours!r} != expected {path!r}")
    # tool status
    for tool, st in (exp.get("tools") or {}).items():
        ours = ((rp.get("tool_status") or {}).get(tool) or {}).get("status")
        if ours != st:
            probs.append(f"tool {tool}: ours {ours} ({((rp.get('tool_status') or {}).get(tool) or {}).get('why')}) != expected {st}")
    # api_mismatch: every expected block is ours too, and no rejected fallback is ever sent
    ours_m = {(m.get("field"), str(m.get("value"))) for m in rep["api_mismatch"]}
    for m in exp.get("api_mismatch") or []:
        if (m["field"], str(m["value"])) not in ours_m:
            probs.append(f"api_mismatch missing: {m['field']} {m['value']!r}")
        fb = m.get("rejected_fallback")
        if fb and fb in json.dumps({k: rp.get(k) for k in ("closing", "transfer", "identity", "events", "who_rules")}):
            sent = [r for r in (rp.get("closing") or {}).get("table") or [] if r.get("outcome") == fb or r.get("reason") == fb]
            if sent or fb in json.dumps((rp.get("transfer") or {}).get("queue_map")):
                probs.append(f"rejected fallback {fb!r} is sendable")
    for a in exp.get("accepted_alias") or []:
        if not any(r.get("outcome") == a["api_value"] for r in (rp.get("closing") or {}).get("table") or []):
            probs.append(f"accepted alias {a['value']}->{a['api_value']} not used")
    # wire shapes
    if exp.get("amount_encoding"):
        want = round(1 / exp["amount_encoding"]["factor"], 6)
        if (rp.get("tool_results") or {}).get("get_account", {}).get("amount_scale") != want:
            probs.append(f"amount_scale != {want}")
    for c in exp.get("composed_fields") or []:
        key = f"{c['tool']}.{c['field']}"
        if ((rp.get("composed_fields") or {}).get(key) or {}).get("roles") != c["roles"]:
            probs.append(f"composed_fields {key} missing")
    vs = exp.get("verified_status")
    if vs and ((rp.get("tool_results") or {}).get("verify_identity") or {}).get("verified_value") != vs["when_true"]:
        probs.append(f"verified_value != {vs['when_true']!r}")
    idn = exp.get("identity") or {}
    if "blocked" in idn and bool((rp.get("identity") or {}).get("blocked")) != idn["blocked"]:
        probs.append(f"identity.blocked ours {bool((rp.get('identity') or {}).get('blocked'))} != {idn['blocked']}")
    st = run_selftest(rp, oas)
    return probs, errs, st


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(n for n in os.listdir(FX) if os.path.isdir(os.path.join(FX, n)))
    bad = 0
    for n in names:
        probs, errs, st = run(n)
        ok = not probs
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {n:20} validator {'PASS' if not errs else 'FAIL'} self-test {st.get('passed')}/{st.get('scenarios')}"
              + (f"  ({len(probs)} diffs)" if probs else ""))
        for p in probs[:12]:
            print("      ", p)
        for e in errs[:4]:
            print("       validator:", e[:160])
    print(f"{len(names) - bad}/{len(names)} variants match expected.json")
    sys.exit(1 if bad else 0)
