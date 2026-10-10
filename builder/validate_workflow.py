"""Local static validator for a generated workflow (no Freya calls).

    python3 builder/validate_workflow.py <workflow.json> <reducer_policy.json> [--openapi tools/openapi.json] [--unstable u.json]

validate(wf, rp, oas_path, unstable_quotes=()) -> list of problems (empty = pass). Checks:
 1 every route target exists (transitions, passthrough defaults, initial node)
 2 identity cannot be bypassed: from greet, account facts (talk_post) and gated tools are unreachable without the
   verified gate (route_ok == yes; transfer: or xfer_pre == yes only if the policy allows pre-verification queues)
 3 required identity fields are never silently skipped: each is an OAS enum value or listed in identity.blocked with a
   close/transfer action
 4 tool names, body arguments and enums match the OAS exactly (also the policy values that will be sent)
 5 confirmation precedes every write: write tools are entered only from the hub, gated, one-shot (w_go), and the
   policy has a confirmation sentence
 6 every terminal path reaches a valid close: end only after t_close_call, close_say -> t_close_call -> end, a
   lifecycle close_call, and every node can reach end
 7 no empty exact-say path: tts texts and their test_variables defaults are non-empty
 8 no double braces in code strings, no null values, no agent_config
 9 no unstable unmapped rule compiled into the workflow
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.generator import CALL_VARS, GATED, arg_map, oas_tools


def _targets(n):
    out = [t["target_node"] for t in n.get("transitions") or []]
    if n.get("passthrough_default_transition"):
        out.append(n["passthrough_default_transition"])
    return out


def _flat_conds(c):
    if not isinstance(c, dict):
        return []
    if "conditions" in c:
        return [x for sub in c["conditions"] for x in _flat_conds(sub)]
    return [c]


def _gate_ok(cond, allow_pre):
    """Every alternative of the OR group requires route_ok == yes (or xfer_pre == yes where allowed)."""
    if not isinstance(cond, dict) or cond.get("operator") == "always":
        return False
    alts = cond.get("conditions") or [cond]
    for a in alts:
        leaves = _flat_conds(a)
        has = any(l.get("variable") == "route_ok" and l.get("operand") == "yes" for l in leaves)
        pre = allow_pre and any(l.get("variable") == "xfer_pre" and l.get("operand") == "yes" for l in leaves)
        if not (has or pre):
            return False
    return True


def _nulls(x, path="$"):
    if x is None:
        return [path]
    if isinstance(x, dict):
        return [p for k, v in x.items() for p in _nulls(v, f"{path}.{k}")]
    if isinstance(x, list):
        return [p for i, v in enumerate(x) for p in _nulls(v, f"{path}[{i}]")]
    return []


def validate(wf, rp, oas_path, unstable_quotes=()):
    errs = []
    nodes = wf.get("nodes") or {}
    tools = oas_tools(oas_path)
    oas = json.load(open(oas_path))
    # 1 targets
    if wf.get("initial_node") not in nodes:
        errs.append(f"1: initial node {wf.get('initial_node')!r} missing")
    for k, n in nodes.items():
        for t in _targets(n):
            if t not in nodes:
                errs.append(f"1: {k} -> {t!r} does not exist")
        if n.get("node_type") != "end_call" and not n.get("transitions"):
            errs.append(f"1: {k} has no outgoing transition")
    # 2 identity gate: drop every gated edge, then nothing gated may be reachable from greet
    allow_pre = bool((rp.get("transfer") or {}).get("pre_verification_queues"))
    protected = {"talk_post"} | {"t_" + t for t in GATED if "t_" + t in nodes} | {"t_transfer_to_agent"} & set(nodes)
    seen, todo = set(), [wf.get("initial_node")]
    while todo:
        k = todo.pop()
        if k in seen or k not in nodes:
            continue
        seen.add(k)
        for t in nodes[k].get("transitions") or []:
            tgt = t["target_node"]
            if tgt in protected:
                if k != "hub":
                    errs.append(f"2: {tgt} is entered from {k}, not from the hub gate")
                elif not _gate_ok(t.get("condition"), allow_pre and tgt == "t_transfer_to_agent"):
                    errs.append(f"2: hub -> {tgt} is not gated on route_ok == yes")
                continue
            todo.append(tgt)
        if nodes[k].get("passthrough_default_transition") in protected:
            errs.append(f"2: {k} passthrough default enters {nodes[k]['passthrough_default_transition']} without the gate")
    leak = protected & seen
    if leak:
        errs.append(f"2: reachable without the verified gate: {sorted(leak)}")
    for k, n in nodes.items():
        if k != "talk_post" and n.get("node_type") == "conversation" and re.search(r"\{\{acct_", json.dumps(n)):
            errs.append(f"2: account facts referenced in {k} (only talk_post may)")
    # 3 identity fields
    idn = rp.get("identity") or {}
    enum = (tools.get("verify_identity", {}).get("props", {}).get("field") or {}).get("enum") or []
    blocked = set((idn.get("blocked") or {}).get("fields") or [])
    for q in idn.get("questions") or []:
        f = q.get("field")
        if f in enum:
            continue
        if f in blocked and (idn.get("blocked") or {}).get("action") in ("close", "transfer"):
            continue
        errs.append(f"3: identity field {f!r} is neither an OAS value nor blocked with a close/transfer action (silently skipped)")
    if not idn.get("questions"):
        errs.append("3: the policy has no identity questions")
    # 4 tools vs OAS
    for k, n in nodes.items():
        for a in n.get("pre_actions") or []:
            fn = a.get("function") or {}
            if fn.get("name") == "code_exec":
                continue
            name = fn.get("name")
            if name not in tools:
                errs.append(f"4: {k} calls {name!r}, not an OAS tool")
                continue
            props = (fn.get("parameters") or {}).get("properties") or {}
            body = (props.get("body") or {}).get("properties") or {}
            extra = set(body) - set(tools[name]["props"])
            if extra:
                errs.append(f"4: {k} body args {sorted(extra)} are not in the OAS")
            amap, unmapped_req, _ = arg_map(name, tools[name])
            for f in unmapped_req:
                errs.append(f"4: api_mismatch: required OAS field {name}.{f} has no canonical source or call variable")
            for f in tools[name]["required"]:
                d = str((body.get(f) or {}).get("default", ""))
                if f not in unmapped_req and not re.fullmatch(r"\{\{(w_\w+|close_\w+|" + "|".join(CALL_VARS) + r")\}\}", d):
                    errs.append(f"4: required OAS field {name}.{f} is not baked from a canonical variable ({d!r})")
            if (props.get("url") or {}).get("default") != tools[name]["url"]:
                errs.append(f"4: {k} url differs from the OAS")
            for arg, sch in body.items():
                d = str(sch.get("default", ""))
                e = (tools[name]["props"].get(arg) or {}).get("enum")
                if e and not re.fullmatch(r"\{\{\w+\}\}", d) and d not in e:
                    errs.append(f"4: {k}.{arg} literal {d!r} not in enum {e}")
    send = [("close_call", "outcome", r["outcome"]) for r in (rp.get("closing") or {}).get("table") or [] if not r.get("blocked")]
    send += [("transfer_to_agent", "queue", q) for q in ((rp.get("transfer") or {}).get("queue_map") or {}).values()]
    send += [("transfer_to_agent", "queue", q) for q in (rp.get("transfer") or {}).get("pre_verification_queues") or []]
    send += [("add_note", "reason", e["note_reason"]) for e in rp.get("events") or [] if e.get("note_reason")]
    for tool, field, val in send:
        e = (tools.get(tool, {}).get("props", {}).get(field) or {}).get("enum")
        if e and val not in e:
            errs.append(f"4: policy value {tool}.{field}={val!r} is not in the OAS enum and not blocked")
    # 5 writes
    for w in ("t_create_promise", "t_add_note"):
        if w in nodes:
            srcs = [k for k, n in nodes.items() if w in _targets(n)]
            if srcs != ["hub"]:
                errs.append(f"5: {w} entered from {srcs}, must be only the hub")
            edge = next((t for t in nodes["hub"]["transitions"] if t["target_node"] == w), {})
            leaves = _flat_conds(edge.get("condition"))
            if not any(l.get("variable") == "w_go_" + w[2:] and l.get("operand") == "go" for l in leaves):
                errs.append(f"5: {w} edge is not one-shot (w_go)")
    sent = {k: v.get("text", "") for k, v in (rp.get("sentences") or {}).items() if isinstance(v, dict)}
    if "t_create_promise" in nodes and not any(re.search(r"confirm", k + " " + t, re.I) for k, t in sent.items()):
        errs.append("5: no confirmation sentence in the policy before writes")
    # 6 closes
    if [k for k, n in nodes.items() if "end" in _targets(n)] != ["t_close_call"]:
        errs.append(f"6: end is entered from {[k for k, n in nodes.items() if 'end' in _targets(n)]}, must be only t_close_call")
    if _targets(nodes.get("close_say", {})) and set(_targets(nodes["close_say"])) != {"t_close_call"}:
        errs.append("6: close_say must lead only to t_close_call")
    if not any((t.get("config") or {}).get("alwaysRunsAt") == ["end_of_call"] and t["function"]["name"] == "close_call" for t in wf.get("tools") or []):
        errs.append("6: no lifecycle close_call safety net")
    rev = {}
    for k, n in nodes.items():
        for t in _targets(n):
            rev.setdefault(t, set()).add(k)
    can, todo = set(), ["end"]
    while todo:
        k = todo.pop()
        if k not in can:
            can.add(k)
            todo += list(rev.get(k, ()))
    stuck = sorted(set(nodes) - can)
    if stuck:
        errs.append(f"6: cannot reach a close from {stuck}")
    tv = wf.get("test_variables") or {}
    if not tv.get("close_outcome") and (rp.get("hangup_default") or {}).get("before_who", {}).get("action") != "end_without_close":
        errs.append("6: close_outcome has no safe default before the first hub run")
    # 7 tts
    for k, n in nodes.items():
        oe = n.get("on_enter") or {}
        if oe.get("type") == "tts":
            txt = oe.get("text", "")
            m = re.fullmatch(r"\{\{(\w+)\}\}", txt.strip())
            if not txt.strip() or (m and not str(tv.get(m.group(1), "")).strip()):
                errs.append(f"7: {k} can speak an empty tts ({txt!r})")
    # 8 code strings, nulls, agent_config
    for k, n in nodes.items():
        for a in n.get("pre_actions") or []:
            code = (((a.get("function") or {}).get("parameters") or {}).get("properties") or {}).get("code", {}).get("default", "")
            if "{{" in code or "}}" in code:
                errs.append(f"8: {k} code has double braces")
    for t in wf.get("tools") or []:
        if "{{" in t.get("pre_process_code", "") or "}}" in t.get("pre_process_code", ""):
            errs.append("8: lifecycle pre_process_code has double braces")
    if "agent_config" in wf:
        errs.append("8: agent_config must be left out")
    errs += [f"8: null at {p}" for p in _nulls(wf)]
    # 9 unstable unmapped
    blob = json.dumps(wf)
    for q in unstable_quotes:
        if q and json.dumps(q)[1:-1] in blob:
            errs.append(f"9: unstable unmapped rule compiled: {q[:60]!r}")
    return errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("policy")
    ap.add_argument("--openapi", default="tools/openapi.json")
    ap.add_argument("--unstable", default="")
    a = ap.parse_args()
    unstable = json.load(open(a.unstable)) if a.unstable else []
    errs = validate(json.load(open(a.workflow)), json.load(open(a.policy)), a.openapi, unstable)
    print("PASS" if not errs else "\n".join(errs))
    sys.exit(1 if errs else 0)
