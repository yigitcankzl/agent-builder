"""Generator + static validator on brief A, A+B and the six Cursor brief fixtures, all local (no Freya).

    python3 tests/test_generator.py
For each brief: bridge the run-5 extraction (unmapped consolidated over runs 4 and 5), generate the workflow,
validate it, print node counts. Then negative tests: mutated workflows/policies must be caught by the validator.
Finally: builder/ must not carry constants from the public briefs or the fixtures.
"""
import copy, glob, json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.generator import generate, node_counts
from builder.policy_bridge import consolidate_unmapped, to_reducer
from builder.validate_workflow import validate

OAS = os.path.join(ROOT, "tools", "openapi.json")
V3 = os.path.join(ROOT, "tests", "policy_eval", "v3")
BRIEFS = ["brief-a", "brief-ab", "mut-01", "mut-02", "mut-03", "mut-04", "mut-05", "raw-a"]


def build(name):
    runs = [json.load(open(os.path.join(V3, r, name + ".json"))) for r in ("run4", "run5")]
    stable, unstable = consolidate_unmapped(runs)
    rp, rep = to_reducer(runs[1], OAS, stable)
    return rp, rep, generate(rp, OAS), [u["quote"] for u in unstable]


def expect_caught(label, wf, rp, unstable, needle):
    errs = validate(wf, rp, OAS, unstable)
    ok = any(needle in e for e in errs)
    print(f"   negative {label}: {'caught' if ok else 'NOT CAUGHT'}" + ("" if ok else f" {errs[:3]}"))
    return ok


def public_constants():
    """Values from the public briefs and the fixtures that a general builder must never carry."""
    texts = [open(p).read() for p in glob.glob(os.path.join(ROOT, "briefs", "*.md"))]
    texts += [open(p).read() for p in glob.glob(os.path.join(ROOT, "tests", "fixtures", "briefs", "**", "*.*"), recursive=True)]
    cases = json.load(open(os.path.join(ROOT, "public-test-set.json")))
    blob = "\n".join(texts)
    consts = set(re.findall(r"\b20\d\d-\d\d-\d\d\b", blob))                                   # dates
    consts |= {f"{p[k]:.2f}".rstrip("0").rstrip(".") for c in cases for p in c["products"] for k in ("past_due",) }  # amounts
    consts |= {c["variables"]["last_name"] for c in cases} | {"Freya Bank"}                   # names
    consts |= set(re.findall(r"`([a-z]+_[a-z_]+)`", blob)) - {"customer_id", "product_id", "days_late", "past_due"}  # outcome/reason/field names
    consts |= {"postcode", "year_of_birth", "no_contact", "phone_last4", "date_of_birth"}
    # the seven tool names are fixed for every brief by the hackathon rules ("The seven tool names stay the same")
    # our own schema vocabulary (also a key in the fixtures), not a brief value
    fixed_schema = {"business_days_after_today"}
    # contract vocabulary (REDUCER-CONTRACT §1.2 party values and the v3.2 effect names), not brief values
    fixed_schema |= {"wrong_number", "no_callback"}
    # identity answer format tokens of the bridge-v2 contract (date|digits(n)|name|alnum|postcode|free)
    fixed_schema |= {"postcode"}
    # the reducer's call-variable roles (contract interface, every brief's call variables are bound to them)
    fixed_schema |= {"first_name", "last_name"}
    # the contract's note keys (writes.notes.reasons: refused, dispute, hardship, paid, service_error)
    fixed_schema |= {"service_error"}
    fixed =fixed_schema | {"verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call"}
    return {c for c in consts if len(c) >= 4} - fixed


if __name__ == "__main__":
    bad = 0
    print("== generate + validate")
    for b in BRIEFS:
        rp, rep, wf, unstable = build(b)
        errs = validate(wf, rp, OAS, unstable)
        bad += bool(errs)
        blocked = (rp.get("identity") or {}).get("blocked")
        print(f"   {b}: {len(wf['nodes'])} nodes {node_counts(wf)}, {len(json.dumps(wf)) // 1024} KB, "
              f"validator {'PASS' if not errs else 'FAIL'}, api_mismatch {len(rep['api_mismatch'])}"
              + (f", identity BLOCKED {blocked['fields']} -> close {blocked['close']}" if blocked else ""))
        for e in errs:
            print("      ", e)
    print("\n== negative tests (each must be caught)")
    rp, _, wf, unstable = build("brief-a")
    caught = []
    w = copy.deepcopy(wf)
    for t in w["nodes"]["hub"]["transitions"]:
        if t["target_node"] == "t_get_account":
            t["condition"] = {"logic": "or", "conditions": [{"variable": "route", "operator": "equals", "operand": "t_get_account"}]}
    caught.append(expect_caught("ungated get_account", w, rp, unstable, "2:"))
    w = copy.deepcopy(wf); w["nodes"]["exact_say"]["transitions"] = [{"target_node": "t_create_promise", "description": "x", "condition": {"operator": "always"}}]
    caught.append(expect_caught("write tool reachable from a speaking node", w, rp, unstable, "2:"))
    w = copy.deepcopy(wf); w["nodes"]["greet"]["transitions"] = [{"target_node": "nowhere", "description": "x", "condition": {"operator": "always"}}]
    caught.append(expect_caught("missing route target", w, rp, unstable, "1:"))
    p = copy.deepcopy(rp); p["identity"]["questions"].append({"field": "mother_maiden_name"})
    caught.append(expect_caught("identity field silently skipped", wf, p, unstable, "3:"))
    w = copy.deepcopy(wf); w["nodes"]["t_verify_identity"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]["field"]["default"] = "shoe_size"
    caught.append(expect_caught("literal outside the OAS enum", w, rp, unstable, "4:"))
    p = copy.deepcopy(rp); p["transfer"]["queue_map"]["x"] = "vip"
    caught.append(expect_caught("policy queue outside the enum", wf, p, unstable, "4:"))
    w = copy.deepcopy(wf); w["nodes"]["talk_post"]["transitions"] = [{"target_node": "end", "description": "x", "condition": {"operator": "always"}}]
    caught.append(expect_caught("end without close_call", w, rp, unstable, "6:"))
    w = copy.deepcopy(wf); w["test_variables"]["say_next"] = ""
    caught.append(expect_caught("empty exact_say default", w, rp, unstable, "7:"))
    w = copy.deepcopy(wf); w["nodes"]["hub"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"] += "x = {'a': {'b': 1}}\n"
    caught.append(expect_caught("double braces in code", w, rp, unstable, "8:"))
    w = copy.deepcopy(wf); w["nodes"]["t_create_promise"]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]["date"]["default"] = "{{w_create_promise_when}}"
    caught.append(expect_caught("baked name differs from the tool_args table", w, rp, unstable, "11:"))
    p = copy.deepcopy(rp); p["tool_results"]["get_account"]["past_due"] = "item.balance_xyz"
    caught.append(expect_caught("response path not in the OAS", wf, p, unstable, "13:"))
    p = copy.deepcopy(rp); p["closing"]["slots"]["promise"] = {"outcome": "arranged", "reason": None}
    caught.append(expect_caught("slot outcome outside the enum", wf, p, unstable, "14:"))
    if unstable:
        w = copy.deepcopy(wf); w["nodes"]["talk_post"]["task_message"] += " " + unstable[0]
        caught.append(expect_caught("unstable unmapped compiled", w, rp, unstable, "9:"))
    print("\n== public constants in builder/")
    consts = public_constants()
    hits = []
    for f in glob.glob(os.path.join(ROOT, "builder", "**", "*.py"), recursive=True):
        text = open(f).read()
        hits += [(os.path.relpath(f, ROOT), c) for c in sorted(consts) if re.search(r"(?<![\w-])" + re.escape(c) + r"(?![\w-])", text)]
    fork3 = ("builder/engine/reducer.py", "builder/engine/event_field.py")    # owned by Fork 3, read-only here
    own = [h for h in hits if h[0] not in fork3]
    theirs = [h for h in hits if h[0] in fork3]
    print(f"   {len(consts)} constants checked; own files: {own or 'none'}")
    if theirs:
        print(f"   WARNING (Fork 3 files, reported, not edited): {theirs}")
    ok = bad == 0 and all(caught) and not own
    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
