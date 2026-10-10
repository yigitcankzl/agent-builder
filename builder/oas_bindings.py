"""Response-side bindings: where each fact the reducer reads lives in the brief's OAS response schema.

tool_results(oas_path, policy) -> ({tool: {fact: path}}, missing: [(tool, fact)])
Paths are "data.<field>" for top-level response fields and "item.<field>" for fields of each element of the
products array. A fact binds only to a field that exists in the schema with the matching shape; ambiguous or absent
-> missing (the bridge reports it as api_mismatch). Field shapes, not names from any brief, decide the binding;
the policy's own field names (products.fields, floor_by_type) win when they exist in the schema.
"""
import json, os, re


def _resp_schema(oas, tool):
    for path, ops in (oas.get("paths") or {}).items():
        if path.strip("/").split("/")[-1] == tool:
            for op in ops.values():
                for code in ("200", "201", "default"):
                    r = (op.get("responses") or {}).get(code)
                    if r:
                        return (((r.get("content") or {}).get("application/json") or {}).get("schema")) or {}
    return {}


def _pick(props, pred, prefer=None):
    """The one property that fits; a preferred name wins when it fits; several fits -> None (ambiguous)."""
    if prefer and prefer in props and pred(prefer, props[prefer]):
        return prefer
    fits = [k for k, v in props.items() if pred(k, v or {})]
    return fits[0] if len(fits) == 1 else None


def tool_results(oas_path, policy):
    oas = json.load(open(oas_path)) if oas_path and os.path.exists(oas_path) else {}
    fields = ((policy.get("products") or {}).get("fields") or {})
    out, missing = {}, []

    def need(tool, fact, val, prefix="data."):
        if val is None:
            missing.append((tool, fact))
        else:
            out.setdefault(tool, {})[fact] = prefix + val
    ok_pred = lambda k, v: v.get("type") == "boolean" and k in ("ok", "success")
    for tool in ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call"):
        s = _resp_schema(oas, tool)
        props = s.get("properties") or {}
        if not s:
            continue
        need(tool, "ok", _pick(props, ok_pred))
        if tool == "verify_identity":
            bools = {k: v for k, v in props.items() if (v or {}).get("type") == "boolean" and "verif" in k}
            need(tool, "verified_all", _pick(bools, lambda k, v: k.startswith("all")) or _pick(bools, lambda k, v: True))
            need(tool, "verified_this", _pick(bools, lambda k, v: not k.startswith("all")))
            need(tool, "wrong_left", _pick(props, lambda k, v: v.get("type") == "integer" and re.search(r"left|remain", k)))
            hint = _pick(props, lambda k, v: "hint" in k)
            if hint:
                out[tool]["hint"] = "data." + hint
        if tool == "get_account":
            arr = _pick(props, lambda k, v: v.get("type") == "array" and ((v.get("items") or {}).get("type") == "object"))
            need(tool, "products", arr)
            item = (((props.get(arr) or {}).get("items") or {}).get("properties") or {}) if arr else {}
            need(tool, "id", _pick(item, lambda k, v: k.endswith("_id") and v.get("type", "string") == "string", fields.get("id")), "item.")
            need(tool, "type", _pick(item, lambda k, v: bool(v.get("enum")), fields.get("type")), "item.")
            need(tool, "past_due", _pick(item, lambda k, v: v.get("type") in ("number", "integer") and re.search(r"due|past|owed|balance", k)
                                        and not re.search(r"days|monthly|minimum|instal", k), fields.get("past_due")), "item.")
            need(tool, "days_late", _pick(item, lambda k, v: v.get("type") in ("integer", "number") and re.search(r"days|late|overdue", k),
                                          fields.get("days_late")), "item.")
            for t, rule in ((policy.get("products") or {}).get("floor_by_type") or {}).items():
                f = (rule or {}).get("field")
                if (rule or {}).get("kind") == "account_field" and f:
                    need(tool, f"floor.{t}", f if f in item else None, "item.")
    return out, missing


def path_exists(oas_path, tool, path):
    oas = json.load(open(oas_path))
    s = _resp_schema(oas, tool)
    props = s.get("properties") or {}
    head, _, name = path.partition(".")
    if head == "data":
        return name in props
    if head == "item":
        return any(name in (((v or {}).get("items") or {}).get("properties") or {}) for v in props.values() if (v or {}).get("type") == "array")
    return False
