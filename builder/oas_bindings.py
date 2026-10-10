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


# verified_value: the one enum member that clearly means "verified" (the OAS description or the brief must name it)
_VERIFIED_WORDS = re.compile(r"^(verified|passed|pass|success|succeeded|matched|match|confirmed|valid|correct|ok)$", re.I)
# amount_scale: an integer amount the OAS explicitly gives in minor units
_MINOR = re.compile(r"\b(cents?|pence|penny|minor units?|minor currency units?|kuru[sş]|kopecks?|paise|centimes?|"
                    r"in hundredths)\b", re.I)
_THOUSANDTHS = re.compile(r"\b(thousandths|mills?|fils)\b", re.I)


def _scale(sch):
    """0.01 / 0.001 when an integer amount's description says minor units, else None (= 1, omitted)."""
    if _kind(sch) != "integer":
        return None
    d = str((sch or {}).get("description") or "")
    return 0.001 if _THOUSANDTHS.search(d) else (0.01 if _MINOR.search(d) else None)


def _verified_enum(lv, brief_text):
    """A string-enum verification field -> (path, member, quote) when exactly one member clearly means verified and the
    OAS description or the brief names it; else None."""
    cands = [(p, v) for p, v in lv if v.get("enum") and _kind(v) in ("string", "") and re.search(r"verif|status|result|check", p, re.I)]
    hits = []
    for p, v in cands:
        members = [m for m in v["enum"] if _VERIFIED_WORDS.match(str(m))]
        if len(members) != 1:
            continue
        m = str(members[0])
        desc = str(v.get("description") or "")
        named = re.search(r"\b" + re.escape(m) + r"\b", desc, re.I) or re.search(r"[`\"']" + re.escape(m) + r"[`\"']", brief_text or "")
        if named:
            quote = desc if re.search(re.escape(m), desc, re.I) else next(
                (ln.strip() for ln in (brief_text or "").splitlines() if re.search(re.escape(m), ln)), "")
            hits.append((p, m, quote))
    return hits[0] if len(hits) == 1 else None


def tool_results(oas_path, policy, brief_text=None):
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
            # the verification booleans: named for verifying / passing / matching (never the generic ok/success flag)
            bools = [(p, v) for p, v in lv if _kind(v) == "boolean" and re.search(r"verif|pass|match|correct", p, re.I)
                     and p.split(".")[-1] not in ("ok", "success")]
            is_all = lambda p, k, v: k.startswith("all") or ".all" in p
            this_b = _pick(bools, lambda p, k, v: not is_all(p, k, v))
            ve = None if this_b else _verified_enum(lv, brief_text)
            all_b = _pick(bools, is_all)
            # verified_all binds only to its OWN field ('all...'): a single per-answer flag is never also read as 'all
            # verified' (that would end identity after the first right answer); with no all-field it is omitted
            if ve:      # a string status (contract decision): the reducer compares that path with verified_value
                out.setdefault(tool, {}).update(verified_this="data." + ve[0], verified_value=ve[1], verified_quote=ve[2][:200])
                if all_b:
                    out[tool]["verified_all"] = "data." + all_b
            elif this_b and not all_b:
                out.setdefault(tool, {})["verified_this"] = "data." + this_b
            else:
                need(tool, "verified_all", all_b)
                need(tool, "verified_this", this_b)
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
            pd_path = (out.get(tool) or {}).get("past_due")
            sc = _scale(dict(item).get(pd_path[5:])) if pd_path else None
            if sc:
                out[tool]["amount_scale"] = sc
            for t, rule in ((policy.get("products") or {}).get("floor_by_type") or {}).items():
                f = (rule or {}).get("field")
                if (rule or {}).get("kind") in ("field", "account_field") and f:
                    hit = [p for p, _ in item if p == f or p.split(".")[-1] == f]
                    need(tool, f"floor.{t}", hit[0] if len(hit) == 1 else None, "item.")
    # the promise amount the agent SENDS: scaled the same way when the request field is in minor units
    for path, ops in (oas.get("paths") or {}).items():
        if path.strip("/").split("/")[-1] == "create_promise":
            for op in ops.values():
                body = ((((op or {}).get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
                amt = [v for k, v in (body.get("properties") or {}).items() if _kind(v) in ("number", "integer")]
                sc = _scale(amt[0]) if len(amt) == 1 else None
                if sc:
                    out.setdefault("create_promise", {})["amount_scale"] = sc
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
