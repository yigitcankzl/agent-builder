"""Smallest workflow generator: bridged policy + OpenAPI -> Freya workflow (REDUCER-CONTRACT §6 + §11.11, v3.1).

    python3 builder/generator.py <reducer_policy.json> [--openapi tools/openapi.json] [--out workflow.json]

Graph:
  greet (tts opening) / exact_say (tts {{say_next}}) / talk_pre / talk_post   --always--> hub_reset --always--> hub
  hub (code: the reducer from builder.integration.hub_code: Fork 3's module; no stub, a load failure raises), edges in contract order:
    close_say | t_transfer_to_agent (go + (route_ok | xfer_pre)) | t_get_account, t_create_promise, t_add_note
    (go + route_ok) | t_verify_identity, t_schedule_callback (go) | talk_post (route_ok) | exact_say | talk_pre (last)
  t_<tool>  api_request, args baked from w_<tool>_<arg>, response_mapping status -> w_go_<tool>, always -> hub
  close_say (tts {{farewell}}, passthrough) -> t_close_call -> end (end_call, silent)
  lifecycle close_call (alwaysRunsAt end_of_call) with {{close_outcome}} / {{close_reason}} as the hang-up safety net
No null values, no agent_config, no double braces inside code strings. Brief values come only from the policy.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.integration import ev_field, hub_code
from builder.oas import load_oas, request_schema

GENERATED_FROM = {}   # which hub code / event field the last generate() used (stub or Fork 3's module), for the trace

TOOLS_ORDER = ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent")
GATED = ("get_account", "create_promise", "add_note")          # need route_ok == yes (the verified gate)
OPEN = ("verify_identity", "schedule_callback")                 # reachable before verification


def oas_tools(oas_path):
    """tool -> {url, props: {name: schema}, required}"""
    d = load_oas(oas_path)
    base = (d.get("servers") or [{}])[0].get("url", "").rstrip("/")
    out = {}
    for path, ops in d.get("paths", {}).items():
        for op in ops.values():
            if not isinstance(op, dict):
                continue
            s = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
            out[path.strip("/").split("/")[-1]] = {"url": base + path, "props": s.get("properties") or {}, "required": s.get("required") or []}
    return out


def _cond(*conds):
    """AND of variable conditions, inside the mandatory top-level OR group."""
    inner = [{"variable": v, "operator": "equals", "operand": o} for v, o in conds]
    return {"logic": "or", "conditions": [inner[0] if len(inner) == 1 else {"logic": "and", "conditions": inner}]}


def _always(target):
    return {"target_node": target, "description": "always", "condition": {"operator": "always"}}


def _code_action(name, code, target):
    if "{{" in code or "}}" in code:
        raise ValueError(f"{name}: code contains double braces")
    return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": target,
            "on_enter": {"type": "silent"},
            "pre_actions": [{"type": "function", "function": {
                "name": "code_exec", "handler": "__function__:code_exec",
                "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code},
                                                                "timeout_ms": {"type": "number", "default": 10000}}}}}],
            "transitions": [_always(target)]}


# The reducer's canonical argument names per tool (Fork 3's interface). The brief's OAS may rename body fields; each
# OAS field is bound to a canonical name by arg_map(), never by guessing a value.
CANONICAL = {"verify_identity": ["customer_id", "field", "answer"], "get_account": ["customer_id"],
             "create_promise": ["customer_id", "product_id", "amount", "date"], "add_note": ["customer_id", "product_id", "reason"],
             "schedule_callback": ["customer_id", "date", "time"], "transfer_to_agent": ["customer_id", "queue"],
             "close_call": ["customer_id", "outcome", "reason"]}
CALL_VARS = {"customer_id"}     # canonical names filled from call variables, not from the reducer


def _tokens(s):
    return {t for t in re.findall(r"[a-z]+", str(s).lower()) if len(t) > 2}


def arg_map(tool, spec):
    """OAS body field -> canonical name. Exact names first; then a remaining canonical name binds to the one remaining
    OAS field whose name or description mentions it (and whose enum-ness matches). Returns (mapping, unmapped_required,
    unused_canonical)."""
    props, req = spec["props"], set(spec["required"])
    canon = list(CANONICAL.get(tool, []))
    m = {f: f for f in props if f in canon}
    left_c = [c for c in canon if c not in m.values()]
    left_f = [f for f in props if f not in m]
    for c in list(left_c):
        cands = [f for f in left_f if (c in _tokens(f) or c in _tokens((props[f] or {}).get("description", "")))]
        if len(cands) == 1:
            m[cands[0]] = c
            left_c.remove(c)
            left_f.remove(cands[0])
    # structural binding by the field's schema shape, only when exactly one remaining field fits
    for c in list(left_c):
        fit = SHAPES.get(c)
        cands = [f for f in left_f if fit and fit(f, props[f] or {})]
        if len(cands) == 1:
            m[cands[0]] = c
            left_c.remove(c)
            left_f.remove(cands[0])
    # one date-time field for both a date and a time role (e.g. schedule_callback.when): bound to 'date' here;
    # arg_roles() gives it both roles and the reducer composes the value (policy.composed_fields)
    if "date" in left_c and "time" in left_c:
        dt = [f for f in left_f if _is_datetime(f, props[f] or {})]
        if len(dt) == 1:
            m[dt[0]] = "date"
            left_c = [c for c in left_c if c not in ("date", "time")]
            left_f.remove(dt[0])
    return m, [f for f in left_f if f in req], left_c


def _is_datetime(f, s):
    return s.get("format") == "date-time" or bool(re.search(r"date.?time|timestamp", f + " " + str(s.get("description", "")), re.I))


def arg_roles(tool, spec):
    """-> ({canonical role: OAS field} without call variables, composed or None). composed = {field: {format, roles}}
    when one date-time field carries both the date and the time role (contract: the reducer writes ONE
    w_<tool>_<field> = 'YYYY-MM-DDTHH:MM:00')."""
    amap, _, left_c = arg_map(tool, spec)
    roles = {c: f for f, c in amap.items() if c not in CALL_VARS}
    f = roles.get("date")
    if f and "time" in CANONICAL.get(tool, []) and "time" not in roles and _is_datetime(f, spec["props"].get(f) or {}):
        roles["time"] = f
        return roles, {f"{tool}.{f}": {"format": "date-time", "roles": ["date", "time"]}}
    return roles, None


def _is_date(f, s):
    return s.get("format") == "date" or "yyyy" in str(s.get("description", "")).lower() or bool(re.search(r"(date|_on$|day)", f))


SHAPES = {"product_id": lambda f, s: f.endswith("_id") and s.get("type", "string") == "string" and not s.get("enum"),
          "amount": lambda f, s: s.get("type") in ("number", "integer"),
          "date": _is_date,
          "time": lambda f, s: "hh:mm" in str(s.get("description", "")).lower() or "time" in f,
          "field": lambda f, s: bool(s.get("enum")), "queue": lambda f, s: bool(s.get("enum")),
          "reason": lambda f, s: bool(s.get("enum")) or "reason" in f, "outcome": lambda f, s: bool(s.get("enum")),
          "answer": lambda f, s: s.get("type", "string") == "string" and not s.get("enum") and not _is_date(f, s)}


def _api_node(tool, spec, target, args_prefix=None, extra_mapping=()):
    body = {}
    amap, _, _ = arg_map(tool, spec)
    for arg, sch in spec["props"].items():
        c = amap.get(arg)
        if c is None:
            continue            # an optional OAS field with no canonical source is left out (a required one is an error)
        # the reducer writes w_<tool>_<OAS field> from the policy's tool_args table (same table as here); close_call's
        # outcome/reason come from the hub's close_outcome / close_reason
        var = c if c in CALL_VARS else (f"{args_prefix}_{c}" if args_prefix else f"w_{tool}_{arg}")
        body[arg] = {"type": sch.get("type", "string"), "default": "{{" + var + "}}"}
    return {"name": "t_" + tool, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": target,
            "on_enter": {"type": "silent"},
            "pre_actions": [{"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0}, "function": {
                "name": tool, "handler": "__function__:api_call", "description": f"Engine-run {tool} with code-baked arguments.",
                "parameters": {"type": "object", "properties": {
                    "url": {"type": "string", "default": spec["url"]},
                    "method": {"type": "string", "default": "POST"},
                    "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                    "body": {"type": "object", "properties": body, "required": list(spec["required"])}}}}}],
            # one-shot edge: a successful response overwrites w_go_<tool>, so the hub edge cannot fire twice
            "response_mapping": [{"path": "status", "variable": "w_go_" + tool}, {"path": "data", "variable": tool + "_data"}]
                                + list(extra_mapping),
            "transitions": [_always(target)]}


def _text(rp, *ids):
    s = rp.get("sentences") or {}
    for i in ids:
        if isinstance(s.get(i), dict) and s[i].get("text"):
            return s[i]["text"]
    return ""


def _soft_rules(rp, phase):
    """Only run-stable unmapped rules (the bridge already dropped unstable ones), as soft text for free talk."""
    rules = [u["quote"] for u in rp.get("unmapped_rules") or [] if u.get("quote")
             and (not u.get("phase_guess") or phase in str(u.get("phase_guess")).lower() or u.get("phase_guess") in ("any", "unknown"))]
    return ("\nSoft rules from the brief:\n- " + "\n- ".join(rules)) if rules else ""


def _minify(src):
    """Lossless: an AST round trip drops comments and docstrings; anything odd -> the source unchanged."""
    import ast
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and node.body and \
                    isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) \
                    and isinstance(node.body[0].value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
        out = ast.unparse(tree)
        compile(out, "hub", "exec")
        return out if "{{" not in out and "}}" not in out else src
    except Exception:
        return src


def pack_hub(src, safe="Sorry, could you say that again?"):
    """Package the hub as a small loader: zlib + base64 payload, exec'd with the node's `vars` (probe m0-zlib: Python
    3.14, exec/compile allowed, ~65 ms). The code_exec input limit (code + data <= 128 KB) makes this necessary.
    PACK_HUB=0 keeps the plain source (fallback)."""
    if os.environ.get("PACK_HUB", "1") == "0":
        return src
    import base64, zlib
    blob = base64.b64encode(zlib.compress(_minify(src).encode(), 9)).decode()
    loader = ("import zlib, base64\n"
              "try:\n"
              "    exec(compile(zlib.decompress(base64.b64decode(" + json.dumps(blob) + ")).decode(), 'hub', 'exec'), "
              "dict(vars=vars, __name__='hub'))\n"
              "except Exception as e:\n"
              "    vars['hub_error'] = 'loader: ' + str(e)[:150]\n"
              "    vars['route'] = 'say'\n"
              "    vars['say_next'] = " + json.dumps(safe) + "\n")
    return loader if "{{" not in loader and "}}" not in loader else src


def _compose_opening(meta):
    """Self-introduction from the policy meta, without repeating the bank name if the description already has it."""
    desc = (meta.get("agent_self_description") or "digital assistant").strip().rstrip(".")
    bank = (meta.get("bank_name") or "").strip()
    who = desc if (not bank or bank.lower() in desc.lower()) else f"{desc} of {bank}"
    return f"Hello, this is {who if who.lower().startswith(('a ', 'an ', 'the ')) or bank.lower() in who.lower() else 'the ' + who}."


def _call_var_placeholders(text, call_vars):
    """{name}-style placeholders in a brief sentence -> the call-variable placeholders the engine substitutes."""
    return re.sub(r"\{(\w+)\}", lambda m: "{{" + str(call_vars.get(m.group(1), m.group(1))) + "}}", text or "")


# drop an empty or unresolved close reason (a promise/paid outcome sends none); no double braces in this code
DROP_EMPTY_REASON = ("try:\n    b = config.get('body')\n    if isinstance(b, dict):\n"
                     "        r = str(b.get('reason') or '')\n        if r == '' or chr(123) in r:\n"
                     "            b.pop('reason', None)\nexcept Exception:\n    pass\n")


def hub_reset_code(tools):
    lines = ["try:", "    vars['route'] = 'stale'"]
    lines += [f"    if str(vars.get('w_go_{t}') or '') != 'go':\n        vars['w_go_{t}'] = 'done'" for t in tools]
    lines += ["except Exception:", "    vars['route'] = 'stale'"]
    return "\n".join(lines) + "\n"


def generate(rp, oas_path):
    tools = oas_tools(oas_path)
    used = [t for t in TOOLS_ORDER if t in tools and not (t == "add_note" and not (rp.get("writes") or {}).get("notes", {}).get("enabled"))]
    meta = rp.get("meta") or {}
    hd = rp.get("hangup_default") or {}
    who0 = hd.get("before_who") or {}
    safe = _text(rp, "safe_repeat") or "Sorry, could you say that again?"
    farewell = _text(rp, "farewell", "farewell_generic", "goodbye") or "Thank you. Goodbye."
    opening = _text(rp, "opening", "greeting", "intro")
    composed = not opening
    opening = opening or _compose_opening(meta)
    # opening hooks (gap 1) are said in the greet tts, before the name question; the reducer only tracks them.
    # A self-introduction hook replaces the composed one, so the agent never introduces itself twice.
    norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
    intro, extra = opening, []
    for h in rp.get("hooks") or []:
        if h.get("point") != "opening" or h.get("condition") or not h.get("text"):
            continue
        t = _call_var_placeholders(h["text"], meta.get("call_vars") or {})
        if norm(t) in norm(" ".join([intro] + extra)):
            continue
        if composed and re.match(r"(I am|I'm|this is|my name is)\b", t, re.I):
            intro, composed = "Hello. " + t, False
        else:
            extra.append(t)
    opening = " ".join([intro.rstrip()] + extra)
    from builder.policy_bridge import honest_line      # the greet is spoken before any tool result
    opening = honest_line(opening)[0] or re.sub(r"\s*[^.!?]*\b(recorded|scheduled|transferred|saved|booked)\b[^.!?]*[.!?]", "", opening, flags=re.I).strip()
    # the reducer counts the name question as already asked by greet (contract §12 choice 2): greet must say it
    who_q = _call_var_placeholders(_text(rp, "confirm_who"), meta.get("call_vars") or {})
    if who_q and who_q not in opening:
        opening = (opening.rstrip() + " " + who_q).strip()
    id_enum = (tools.get("verify_identity", {}).get("props", {}).get("field") or {}).get("enum") or []
    ev, ev_src = ev_field(rp, id_enum)
    hub_src, hub_from = hub_code(rp)
    plain_kb = len(hub_src) / 1024
    hub_src = pack_hub(hub_src, _text(rp, "safe_repeat") or "Sorry, could you say that again?")
    GENERATED_FROM.update(hub_plain_kb=round(plain_kb, 1), hub_kb=round(len(hub_src) / 1024, 1),
                          hub_packed=hub_src is not None and "zlib.decompress" in hub_src)
    lang = meta.get("language") or "English"
    sysp = (f"You are the {meta.get('agent_self_description') or 'digital assistant'} of {meta.get('bank_name') or 'the bank'}. "
            f"Speak {lang}, one or two short sentences per turn. Never say that anything was recorded, scheduled or "
            f"transferred. Never invent figures, dates or reasons.")
    nodes = {
        "greet": {"name": "greet", "node_type": "conversation", "on_enter": {"type": "tts", "text": opening},
                  "task_message": "No tool call is allowed. Wait for the customer.", "extraction_schema": [ev],
                  "max_node_turns": 80, "transitions": [_always("hub_reset")]},
        "hub_reset": _code_action("hub_reset", hub_reset_code(used), "hub"),
        "exact_say": {"name": "exact_say", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{say_next}}"},
                      "task_message": "No tool call is allowed.", "extraction_schema": [ev], "max_node_turns": 80,
                      "transitions": [_always("hub_reset")]},
        "talk_pre": {"name": "talk_pre", "node_type": "conversation", "on_enter": {"type": "llm"},
                     "task_message": "Identity is NOT verified. Say nothing about why the bank calls, any product, amount "
                                     "or debt. Answer briefly and politely. {{talk_hint}} No tool call is allowed." + _soft_rules(rp, "pre"),
                     "extraction_schema": [ev], "max_node_turns": 80, "transitions": [_always("hub_reset")]},
        "talk_post": {"name": "talk_post", "node_type": "conversation", "on_enter": {"type": "llm"},
                      "task_message": "Identity is verified. Answer briefly. Facts: {{talk_hint}} No tool call is allowed. "
                                      "Never offer terms, dates or amounts yourself." + _soft_rules(rp, "post"),
                      "extraction_schema": [ev], "max_node_turns": 80, "transitions": [_always("hub_reset")]},
        "close_say": {"name": "close_say", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{farewell}}"},
                      "passthrough": True, "passthrough_default_transition": "t_close_call",
                      "task_message": "No tool call is allowed.", "transitions": [_always("t_close_call")]},
        "end": {"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                "transitions": [], "terminal": {"type": "function", "function": {
                    "name": "call_closed", "handler": "__function__:end_call",
                    "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}},
    }
    for t in used:
        nodes["t_" + t] = _api_node(t, tools[t], "hub")
    if "close_call" in tools:
        cc = _api_node("close_call", tools["close_call"], "end", args_prefix="close")
        # the graph's close node too: a promise/paid close sends no reason ('' would break a reason enum)
        cc["pre_actions"][0]["pre_process_code"] = DROP_EMPTY_REASON
        nodes["t_close_call"] = cc
    hub_edges = [{"target_node": "close_say", "description": "close", "condition": _cond(("route", "close"))}]
    if "transfer_to_agent" in used:
        pre_ok = bool((rp.get("transfer") or {}).get("pre_verification_queues"))
        alts = [{"logic": "and", "conditions": [{"variable": "route", "operator": "equals", "operand": "t_transfer_to_agent"},
                                                {"variable": "w_go_transfer_to_agent", "operator": "equals", "operand": "go"},
                                                {"variable": "route_ok", "operator": "equals", "operand": "yes"}]}]
        if pre_ok:
            alts.append({"logic": "and", "conditions": [{"variable": "route", "operator": "equals", "operand": "t_transfer_to_agent"},
                                                        {"variable": "w_go_transfer_to_agent", "operator": "equals", "operand": "go"},
                                                        {"variable": "xfer_pre", "operator": "equals", "operand": "yes"}]})
        hub_edges.append({"target_node": "t_transfer_to_agent", "description": "transfer", "condition": {"logic": "or", "conditions": alts}})
    for t in used:
        if t in GATED:
            hub_edges.append({"target_node": "t_" + t, "description": t, "condition": _cond(("route", "t_" + t), ("w_go_" + t, "go"), ("route_ok", "yes"))})
    for t in used:
        if t in OPEN:
            hub_edges.append({"target_node": "t_" + t, "description": t, "condition": _cond(("route", "t_" + t), ("w_go_" + t, "go"))})
    hub_edges.append({"target_node": "exact_say", "description": "say", "condition": _cond(("route", "say"))})
    # ONE talk_post edge after every specific route (same-target edges merge at the first position): after
    # verification, free talk, a stale turn and any unmatched route (a gated tool whose w_go is not 'go', an unknown
    # route) stay in the verified free talk; talk_pre (the unverified prompt) is reached only before verification
    hub_edges.append({"target_node": "talk_post", "description": "free talk / stale / unmatched route after verification",
                      "condition": _cond(("route_ok", "yes"))})
    hub_edges.append(_always("talk_pre"))
    hub = _code_action("hub", hub_src, "talk_pre")
    hub["transitions"] = hub_edges
    nodes["hub"] = hub
    tv = {"ev_tok": "kstart", "route": "stale", "route_ok": "no", "xfer_pre": "no", "say_next": safe, "farewell": farewell,
          "talk_hint": "", "close_outcome": who0.get("outcome") or "", "close_reason": who0.get("reason") or ""}
    for t in used:
        tv["w_go_" + t] = "done"
        for f in ((rp.get("tool_args") or {}).get(t) or {c: f for f, c in arg_map(t, tools[t])[0].items() if c not in CALL_VARS}).values():
            tv[f"w_{t}_{f}"] = ""
    wf = {"initial_node": "greet", "system_prompt": sysp, "nodes": nodes, "global_nodes": {}, "test_variables": tv}
    GENERATED_FROM.update(hub=hub_from, ev=ev_src)
    if "close_call" in tools:
        lc = _api_node("close_call", tools["close_call"], "end", args_prefix="close")["pre_actions"][0]
        lc["config"] = {"timeoutMs": 12000, "maxRetries": 0, "alwaysRunsAt": ["end_of_call"]}
        # drop an empty or unresolved reason (a promise/paid outcome sends none); no double braces in this code
        lc["pre_process_code"] = DROP_EMPTY_REASON
        wf["tools"] = [lc]
    return wf


def node_counts(wf):
    c = {}
    for n in wf["nodes"].values():
        c[n["node_type"]] = c.get(n["node_type"], 0) + 1
    return c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("policy")
    ap.add_argument("--openapi", default="tools/openapi.json")
    ap.add_argument("--out", default="workflow.json")
    a = ap.parse_args()
    wf = generate(json.load(open(a.policy)), a.openapi)
    json.dump(wf, open(a.out, "w"), indent=1)
    print(json.dumps({"nodes": len(wf["nodes"]), "by_type": node_counts(wf)}))
