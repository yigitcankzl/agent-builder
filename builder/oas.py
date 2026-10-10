"""One OpenAPI loader for every reader (bridge, oas_bindings, generator, validator, self-test, extraction summary).

load_oas(path) -> the OAS dict with every LOCAL $ref ("#/components/...") resolved in place and allOf merged, cached by
path and mtime. A remote or broken $ref is left as {"$ref": ...} plus "x-unresolved": true (never guessed). A cycle is
cut at the second visit (the inner node keeps its $ref). response_schema(oas, tool) picks the first 2xx JSON response.
"""
import copy, json, os

_CACHE = {}


def _resolve_ptr(doc, ref):
    node = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _merge_all_of(parts):
    out = {}
    for p in parts:
        if not isinstance(p, dict):
            continue
        for k, v in p.items():
            if k == "properties":
                out.setdefault("properties", {}).update(v or {})
            elif k == "required":
                out["required"] = sorted(set(out.get("required") or []) | set(v or []))
            else:
                out.setdefault(k, v)
    if "properties" in out:
        out.setdefault("type", "object")
    return out


def resolve(doc):
    def walk(node, seen):
        if isinstance(node, list):
            return [walk(x, seen) for x in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith("#/"):
                return dict(node, **{"x-unresolved": True})
            if ref in seen:
                return dict(node)                       # cycle: keep the reference
            target = _resolve_ptr(doc, ref)
            if target is None:
                return dict(node, **{"x-unresolved": True})
            merged = dict(walk(copy.deepcopy(target), seen | {ref}))
            merged.update({k: walk(v, seen) for k, v in node.items() if k != "$ref"})   # siblings of $ref win
            return merged
        out = {k: walk(v, seen) for k, v in node.items()}
        if isinstance(out.get("allOf"), list):
            rest = {k: v for k, v in out.items() if k != "allOf"}
            out = _merge_all_of(out["allOf"] + [rest])
        return out
    return walk(doc, frozenset())


def load_oas(path):
    if not path or not os.path.exists(path):
        return {}
    key = (os.path.abspath(path), os.path.getmtime(path))
    if key not in _CACHE:
        _CACHE[key] = resolve(json.load(open(path)))
    return _CACHE[key]


def response_schema(oas, tool):
    """The JSON schema of the tool's first 2xx response (200, 201, 2XX, then default)."""
    for path, ops in (oas.get("paths") or {}).items():
        if path.strip("/").split("/")[-1] != tool:
            continue
        for op in ops.values():
            if not isinstance(op, dict):
                continue
            rs = op.get("responses") or {}
            codes = sorted(c for c in rs if str(c).startswith("2")) + (["default"] if "default" in rs else [])
            for c in codes:
                s = (((rs[c] or {}).get("content") or {}).get("application/json") or {}).get("schema")
                if s:
                    return s
    return {}


def request_schema(op):
    return (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
