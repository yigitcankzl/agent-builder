"""Build-time binding assist (FINAL-PLAN decision 3b, signal S3): when the shape rules of oas_bindings leave a CORE
response fact unbound, one Claude call reads the OAS response schemas (resolved) and proposes a dotted path per fact.
A proposal is accepted only when the path exists in the OAS AND its shape fits the fact; nothing is guessed at runtime.

CORE = facts the reducer cannot run without; core_missing(rp) lists the unbound ones.
assist(rp, oas_path, brief_text, sink, deadline) -> (rp', report {proposed, accepted, rejected, still_missing})
"""
import copy, json

from builder.oas import load_oas, response_schema
from builder.oas_bindings import _kind, leaves
from builder.policy_extract import _Forward, Trace, call_claude, parse_json

CORE = {"verify_identity": ("verified_this", "verified_all"),        # one of the two is enough
        "get_account": ("products", "id", "past_due", "days_late")}
FACT_DOC = {"verified_this": "true when THIS identity answer was right (boolean)",
            "verified_all": "true when ALL identity questions are now verified (boolean)",
            "products": "the list (array of objects) of the customer's late products",
            "id": "inside one product: its id (string)",
            "past_due": "inside one product: the past-due amount (number)",
            "days_late": "inside one product: how many days late (integer)"}

PROMPT = """A bank's tool API returns the JSON responses below. For each FACT, give the dotted path where the response
carries it: "data.<a>.<b>" for a field of the response, "item.<a>" for a field of ONE element of the products list.
Use only paths that exist in the schema. If no field carries a fact, answer null. Output JSON only:
{"paths": {"<tool>.<fact>": "<path or null>", ...}, "why": {"<tool>.<fact>": "<short reason>"}}
"""


def core_missing(rp):
    tr = rp.get("tool_results") or {}
    out = []
    vi = tr.get("verify_identity") or {}
    if not (vi.get("verified_this") or vi.get("verified_all")):
        out.append(("verify_identity", "verified_this"))
    ga = tr.get("get_account") or {}
    out += [("get_account", f) for f in CORE["get_account"] if not ga.get(f)]
    return out


def _fits(fact, sch):
    k = _kind(sch)
    return {"verified_this": k == "boolean", "verified_all": k == "boolean",
            "products": k == "array" and _kind((sch or {}).get("items")) == "object",
            "id": k in ("string", "integer", ""), "past_due": k in ("number", "integer"),
            "days_late": k in ("integer", "number")}.get(fact, False)


def _schema_at(oas, tool, path, products_path=None):
    s = response_schema(oas, tool)
    head, _, rest = path.partition(".")
    lv = dict(leaves(s))
    if head == "data":
        return lv.get(rest)
    if head == "item" and products_path and products_path.startswith("data."):
        arr = lv.get(products_path[5:]) or {}
        return dict(leaves((arr or {}).get("items"))).get(rest)
    return None


def assist(rp, oas_path, brief_text="", sink=None, deadline=None, ask=None):
    """ask: optional replacement for the Claude call (tests): ask(prompt) -> model text."""
    miss = core_missing(rp)
    rep = {"proposed": {}, "accepted": {}, "rejected": {}, "still_missing": [], "asked": [f"{t}.{f}" for t, f in miss]}
    if not miss:
        return rp, rep
    oas = load_oas(oas_path)
    schemas = {t: [{"path": p, "type": _kind(v), "description": str(v.get("description") or "")[:120]}
                   for p, v in leaves(response_schema(oas, t))] for t in ("verify_identity", "get_account")}
    for t in ("get_account",):          # the item fields of every array of objects, so 'item.' paths can be named
        for p, v in leaves(response_schema(oas, t)):
            if _kind(v) == "array" and _kind((v or {}).get("items")) == "object":
                schemas[t] += [{"path": f"item.{q}", "in_array": p, "type": _kind(w)} for q, w in leaves(v["items"])]
    facts = {f"{t}.{f}": FACT_DOC[f] for t, f in miss}
    prompt = (PROMPT + "\nFACTS:\n" + json.dumps(facts, indent=1) + "\n\nRESPONSE FIELDS (data.<path>):\n"
              + json.dumps(schemas, indent=1) + ("\n\nBRIEF (context only):\n" + brief_text[:6000] if brief_text else ""))
    if ask is None:
        trace = _Forward(sink, deadline) if sink is not None else Trace(None)
        text = call_claude(prompt, "binding assist (core response facts)", trace)
    else:
        text = ask(prompt)
    out = parse_json(text)
    p = copy.deepcopy(rp)
    tr = p.setdefault("tool_results", {})
    for key, path in (out.get("paths") or {}).items():
        tool, _, fact = key.partition(".")
        if (tool, fact) not in miss or not path:
            continue
        rep["proposed"][key] = path
        path = path if path.startswith(("data.", "item.")) else "data." + path
        prod = (tr.get("get_account") or {}).get("products") or (path if fact == "products" else None)
        sch = _schema_at(oas, tool, path, prod)
        if sch is None:
            rep["rejected"][key] = f"{path}: not in the OAS response schema"
        elif not _fits(fact, sch):
            rep["rejected"][key] = f"{path}: shape {_kind(sch)!r} does not fit {fact}"
        else:
            tr.setdefault(tool, {})[fact] = path
            rep["accepted"][key] = path
    p["api_mismatch"] = [m for m in p.get("api_mismatch") or []
                         if not (str(m.get("policy_path", "")).startswith("tool_results.")
                                 and str(m["policy_path"]).split(".", 1)[1] in rep["accepted"])]
    rep["still_missing"] = [f"{t}.{f}" for t, f in core_missing(p)]
    return p, rep
