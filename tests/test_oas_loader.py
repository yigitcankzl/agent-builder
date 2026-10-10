"""The shared OAS loader (builder/oas.py) and nested response paths, offline.

    python3 tests/test_oas_loader.py
1. A $ref + 201 variant of the kit OAS (every request/response schema moved to components and referenced, product rows
   via a nested $ref, create_promise answering 201) gives a bridged policy and a workflow byte-identical to the plain OAS.
2. A nested-response variant (verify fields under data.result, ok under data.status, products under data.account.items,
   past_due under item.balance) binds to dotted paths, passes the validator, and the self-test (whose fake bank answers
   at the bound paths only) stays green: the reducer reads the nested paths.
3. Unresolvable / remote refs are marked, never guessed; a $ref cycle terminates.
"""
import copy, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.generator import generate
from builder.oas import load_oas, resolve
from builder.policy_bridge import to_reducer
from builder.selftest import run_selftest
from builder.validate_workflow import validate

OAS = os.path.join(ROOT, "tools", "openapi.json")
POLICY = json.load(open(os.path.join(ROOT, "tests", "policy_eval", "v3", "run5", "brief-a.json")))
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def _ops(d):
    for path, ops in d["paths"].items():
        for op in ops.values():
            if isinstance(op, dict):
                yield path.strip("/").split("/")[-1], op


def ref_variant(d):
    d = copy.deepcopy(d)
    comps = d.setdefault("components", {}).setdefault("schemas", {})
    for tool, op in _ops(d):
        body = op["requestBody"]["content"]["application/json"]
        comps[tool + "_req"], body["schema"] = body["schema"], {"$ref": f"#/components/schemas/{tool}_req"}
        rs = op["responses"]
        code = next(c for c in rs if str(c).startswith("2"))
        sch = rs[code]["content"]["application/json"]
        resp = sch["schema"]
        for k, v in list((resp.get("properties") or {}).items()):     # product rows through a second $ref
            if v.get("type") == "array" and (v.get("items") or {}).get("type") == "object":
                comps["product_row"], v["items"] = v["items"], {"$ref": "#/components/schemas/product_row"}
        comps[tool + "_resp"], sch["schema"] = resp, {"$ref": f"#/components/schemas/{tool}_resp"}
        if tool == "create_promise":
            rs["201"] = rs.pop(code)
    return d


def nested_variant(d):
    d = copy.deepcopy(d)
    for tool, op in _ops(d):
        rs = op["responses"]
        code = next(c for c in rs if str(c).startswith("2"))
        s = rs[code]["content"]["application/json"]["schema"]
        props = s.get("properties") or {}
        ok = props.pop("ok", None)
        if tool == "verify_identity":
            s["properties"] = {"result": {"type": "object", "properties": props}}
        if tool == "get_account":
            arr = next(k for k, v in props.items() if v.get("type") == "array")
            items = props.pop(arr)
            ip = items["items"]["properties"]
            ip["balance"] = {"type": "object", "properties": {"past_due": ip.pop("past_due")}}
            s["properties"] = dict(props, account={"type": "object", "properties": {"items": items}})
        if ok:
            s["properties"]["status"] = {"type": "object", "properties": {"ok": ok}}
    return d


def dump(path, d):
    json.dump(d, open(path, "w"), indent=1)
    return path


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    plain = json.load(open(OAS))
    rp0, _ = to_reducer(copy.deepcopy(POLICY), OAS, [])
    wf0 = generate(rp0, OAS)
    # 1 $ref + 201
    refp = dump(os.path.join(tmp, "ref.json"), ref_variant(plain))
    check("$ref" in open(refp).read(), "the variant really uses $ref")
    rp1, _ = to_reducer(copy.deepcopy(POLICY), refp, [])
    wf1 = generate(rp1, refp)
    check(json.dumps(rp1, sort_keys=True) == json.dumps(rp0, sort_keys=True), "bridged policy identical under $ref + 201")
    check(json.dumps(wf1, sort_keys=True) == json.dumps(wf0, sort_keys=True), "workflow byte-identical under $ref + 201")
    check(not validate(wf1, rp1, refp), "validator passes on the $ref variant")
    # 2 nested responses
    nesp = dump(os.path.join(tmp, "nested.json"), nested_variant(plain))
    rp2, rep2 = to_reducer(copy.deepcopy(POLICY), nesp, [])
    tr = rp2["tool_results"]
    check(tr["verify_identity"].get("verified_all") == "data.result.all_verified" and tr["verify_identity"].get("ok") == "data.status.ok",
          f"verify_identity nested paths: {tr['verify_identity']}")
    check(tr["get_account"].get("products") == "data.account.items" and tr["get_account"].get("past_due") == "item.balance.past_due",
          f"get_account nested paths: {tr['get_account']}")
    check(not [m for m in rep2["api_mismatch"] if m["policy_path"].startswith("tool_results")], "no core binding missing")
    wf2 = generate(rp2, nesp)
    errs = validate(wf2, rp2, nesp)
    check(not errs, f"validator passes on the nested variant {errs[:3]}")
    st = run_selftest(rp2, nesp)
    check(st["passed"] == st["scenarios"] and st["scenarios"] > 0, f"self-test with a nested fake bank: {st['passed']}/{st['scenarios']} {json.dumps(st.get('failures'))[:300]}")
    # the self-test really answers nested (no flat keys at the top)
    from builder.selftest import Bank
    b = Bank([{"product_id": "p1", "type": "credit_card", "past_due": 100.0, "days_late": 3}], {"date_of_birth": "x"}, results=tr)
    data = b.call("get_account", {})["data"]
    check("products" not in data and data["account"]["items"][0]["balance"]["past_due"] == 100.0, f"fake bank shape: {data}")
    # 3 refs that cannot be resolved, and cycles
    r = resolve({"a": {"$ref": "#/nope"}, "b": {"$ref": "http://x/y.json#/z"}, "components": {"c": {"properties": {"self": {"$ref": "#/components/c"}}}},
                 "use": {"$ref": "#/components/c"}})
    check(r["a"].get("x-unresolved") and r["b"].get("x-unresolved"), "missing and remote refs are marked, not guessed")
    check(r["use"]["properties"]["self"].get("$ref") == "#/components/c", "a $ref cycle terminates")
    check(load_oas(OAS) is load_oas(OAS), "load_oas caches")
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
