"""Response-side bindings: where each fact the reducer reads lives in the brief's OAS response schema.

tool_results(oas_path, policy) -> ({tool: {fact: path}}, missing: [(tool, fact)])
Paths (Fork 3's get_path contract) are dotted: "data.<a>.<b>" inside the response, "item.<a>.<b>" inside each element
of the products array (which may itself be nested, e.g. "data.account.items"). A flat schema gives exactly today's
paths ("data.verified", "item.past_due"). A fact binds only to a field with the matching shape; when several fit, the
shallowest single one wins, else the fact is missing (the bridge reports it as api_mismatch) - nothing is guessed.
Field shapes, not names from any brief, decide the binding; the policy's own field names (products.fields,
floor_by_type) win when they exist in the schema. $refs are resolved by builder.oas.load_oas.
"""
import re

from builder.oas import load_oas, response_schema

_resp_schema = response_schema      # old name, used by the validator


def _kind(s):
    s = s or {}
    if s.get("type"):
        return s["type"]
    return "object" if s.get("properties") else ("array" if s.get("items") else "")


def leaves(schema, prefix=""):
    """[(dotted path, schema)] for every non-object field under schema; arrays are leaves (their items not entered)."""
    out = []
    for k, v in ((schema or {}).get("properties") or {}).items():
        p = prefix + k
        if _kind(v) == "object":
            out += leaves(v, p + ".")
        else:
            out.append((p, v or {}))
    return out


def _pick(cands, pred, prefer=None):
    """cands: [(path, schema)] -> the path that fits; a preferred name (path or last segment) wins when it fits;
    several fits -> the shallowest single one, else None (ambiguous)."""
    fits = [(p, s) for p, s in cands if pred(p, p.split(".")[-1], s)]
    if prefer:
        pref = [p for p, s in fits if p == prefer or p.split(".")[-1] == prefer]
        if len(pref) == 1:
            return pref[0]
    if len(fits) == 1:
        return fits[0][0]
    if fits:
        depth = min(p.count(".") for p, _ in fits)
        top = [p for p, _ in fits if p.count(".") == depth]
        return top[0] if len(top) == 1 else None
    return None


def tool_results(oas_path, policy):
    oas = load_oas(oas_path)
    fields = ((policy.get("products") or {}).get("fields") or {})
    out, missing = {}, []

    def need(tool, fact, val, prefix="data."):
        if val is None:
            missing.append((tool, fact))
        else:
            out.setdefault(tool, {})[fact] = prefix + val
    ok_pred = lambda p, k, v: _kind(v) == "boolean" and k in ("ok", "success")
    for tool in ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call"):
        s = response_schema(oas, tool)
        if not s:
            continue
        lv = leaves(s)
        need(tool, "ok", _pick(lv, ok_pred))
        if tool == "verify_identity":
            bools = [(p, v) for p, v in lv if _kind(v) == "boolean" and "verif" in p.lower()]
            need(tool, "verified_all", _pick(bools, lambda p, k, v: k.startswith("all") or ".all" in p) or _pick(bools, lambda p, k, v: True))
            need(tool, "verified_this", _pick(bools, lambda p, k, v: not (k.startswith("all") or ".all" in p)))
            need(tool, "wrong_left", _pick(lv, lambda p, k, v: _kind(v) == "integer" and re.search(r"left|remain", k)))
            hint = _pick(lv, lambda p, k, v: "hint" in k)
            if hint:
                out.setdefault(tool, {})["hint"] = "data." + hint
        if tool == "get_account":
            arrs = [(p, v) for p, v in lv if _kind(v) == "array" and _kind((v or {}).get("items")) == "object"]
            arr = _pick(arrs, lambda p, k, v: True)
            need(tool, "products", arr)
            item = leaves(dict(lv)[arr]["items"]) if arr else []
            need(tool, "id", _pick(item, lambda p, k, v: (k.endswith("_id") or k == "id") and _kind(v) in ("string", "") and not v.get("enum"), fields.get("id")), "item.")
            need(tool, "type", _pick(item, lambda p, k, v: bool(v.get("enum")), fields.get("type")), "item.")
            need(tool, "past_due", _pick(item, lambda p, k, v: _kind(v) in ("number", "integer") and re.search(r"due|past|owed|balance", p)
                                        and not re.search(r"days|monthly|minimum|instal", p), fields.get("past_due")), "item.")
            need(tool, "days_late", _pick(item, lambda p, k, v: _kind(v) in ("integer", "number") and re.search(r"days|late|overdue", p),
                                          fields.get("days_late")), "item.")
            for t, rule in ((policy.get("products") or {}).get("floor_by_type") or {}).items():
                f = (rule or {}).get("field")
                if (rule or {}).get("kind") in ("field", "account_field") and f:
                    hit = [p for p, _ in item if p == f or p.split(".")[-1] == f]
                    need(tool, f"floor.{t}", hit[0] if len(hit) == 1 else None, "item.")
    return out, missing


def path_exists(oas_path, tool, path):
    """A 'data.' or 'item.' dotted path names a field of the tool's response schema (item: of a products-like array)."""
    s = response_schema(load_oas(oas_path), tool)
    head, _, rest = path.partition(".")
    lv = leaves(s)
    if head == "data":
        return rest in {p for p, _ in lv} or any(p.startswith(rest + ".") for p, _ in lv)
    if head == "item":
        return any(rest in {q for q, _ in leaves((v or {}).get("items"))} for p, v in lv if _kind(v) == "array")
    return False
