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
10 the reducer interface: every fixed sentence key present, who_rules in the contract vocabulary
11 one tool_args table: policy.tool_args == arg_map(OAS) and the baked placeholders are w_<tool>_<OAS field>
12 every required OAS request field is bound
13 tool_results: every response path exists in the OAS response schema, and the core facts are bound
14 every enum value the agent may send (slots, product types, identity fields, note reasons, outcomes, queues) is exact
15 event and who lines are speakable: no instruction prose
16 the hub code fits the code_exec input limit
17 hooks: known points, closed-set conditions, speakable text with its quote; the greet says every opening hook
18 identity answer formats are in the closed set
19 floor rules, amounts.acceptance and date_rules use the closed shapes (gaps 3-4)
20 honesty: no recorded/scheduled/transferred/saved/booked in the greet or any line spoken before a write succeeds
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.generator import CALL_VARS, GATED, arg_map, arg_roles, oas_tools
from builder.oas import load_oas


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
    oas = load_oas(oas_path)
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
    send += [("close_call", "outcome", e["outcome"]) for coll in ("events", "who_rules") for e in rp.get(coll) or []
             if e.get("outcome") and not e.get("blocked")]
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
    # 10 reducer interface: the fixed sentence keys and the who vocabulary
    from builder.policy_bridge import FIXED_SENTENCES, PARTY_VOCAB, WHO_VOCAB
    sent_all = rp.get("sentences") or {}
    for sid in FIXED_SENTENCES:
        if not isinstance(sent_all.get(sid), dict) or not isinstance(sent_all[sid].get("text"), str):
            errs.append(f"10: fixed sentence key {sid!r} missing")
    for i, w in enumerate(rp.get("who_rules") or []):
        if w.get("who") not in WHO_VOCAB:
            errs.append(f"10: who_rules[{i}].who {w.get('who')!r} not in {WHO_VOCAB}")
        if w.get("party", "") not in PARTY_VOCAB:
            errs.append(f"10: who_rules[{i}].party {w.get('party')!r} not in {PARTY_VOCAB}")
    # 11 one source of truth for tool args: the policy's tool_args == arg_map(OAS), and every baked placeholder of a
    #    tool node is exactly w_<tool>_<OAS field> for the field the table names (what the reducer writes)
    ta = rp.get("tool_args")
    if ta is None:
        errs.append("11: the policy has no tool_args table")
    else:
        for name, spec in tools.items():
            expect = arg_roles(name, spec)[0]
            if name != "close_call" and ta.get(name, {}) != expect:
                errs.append(f"11: tool_args[{name}] {ta.get(name)} != arg_map {expect}")
            node = nodes.get("t_" + name)
            if not node or name == "close_call":
                continue
            body = ((node["pre_actions"][0]["function"]["parameters"]["properties"].get("body") or {}).get("properties") or {})
            for c, f in (ta.get(name) or {}).items():
                want = "{{w_" + name + "_" + f + "}}"
                if (body.get(f) or {}).get("default") != want:
                    errs.append(f"11: t_{name}.{f} bakes {(body.get(f) or {}).get('default')!r}, the reducer writes {want}")
    # 12 every required request field of every generated tool node is bound (canonical role or call variable)
    for name, spec in tools.items():
        if "t_" + name in nodes:
            for f in arg_map(name, spec)[1]:
                errs.append(f"12: required OAS field {name}.{f} is not bound; the tool must be blocked")
    # 13 response paths: every fact the reducer reads exists in the OAS response schema
    from builder.oas_bindings import path_exists
    for tool, facts in (rp.get("tool_results") or {}).items():
        for fact, path in facts.items():
            if fact in ("verified_value", "verified_quote", "amount_scale"):     # values, not paths
                continue
            if not path_exists(oas_path, tool, path):
                errs.append(f"13: tool_results.{tool}.{fact} = {path!r} is not in the OAS response schema")
    vi = (rp.get("tool_results") or {}).get("verify_identity") or {}
    if "t_verify_identity" in nodes and not (vi.get("verified_all") or vi.get("verified_this")):
        errs.append("13: tool_results.verify_identity has neither verified_all nor verified_this")
    for tool, fact in (("get_account", "products"), ("get_account", "id"),
                       ("get_account", "past_due"), ("get_account", "days_late")):
        if "t_" + tool in nodes and fact not in (rp.get("tool_results") or {}).get(tool, {}):
            errs.append(f"13: tool_results.{tool}.{fact} is missing")
    for tool, facts in (rp.get("tool_results") or {}).items():
        if "amount_scale" in facts and facts["amount_scale"] not in (0.01, 0.001):
            errs.append(f"13: tool_results.{tool}.amount_scale {facts['amount_scale']!r} is not 0.01 or 0.001")
        if "verified_value" in facts and not facts.get("verified_quote"):
            errs.append(f"13: tool_results.{tool}.verified_value without its quote")
    # 14 every enum value the agent may send is an exact OAS member: slots, product types, identity fields (unless
    #    blocked), note reasons, outcomes/reasons of tables, events and who rules, queues
    enum = lambda tool, f: (tools.get(tool, {}).get("props", {}).get(f) or {}).get("enum")
    e_out, e_rsn, e_q, e_n = enum("close_call", "outcome"), enum("close_call", "reason"), enum("transfer_to_agent", "queue"), enum("add_note", "reason")
    for k, v in ((rp.get("closing") or {}).get("slots") or {}).items():
        if v and e_out and v.get("outcome") not in e_out:
            errs.append(f"14: closing.slots.{k}.outcome {v.get('outcome')!r} not in the OAS enum")
        if v and e_rsn and v.get("reason") and v.get("reason") not in e_rsn:
            errs.append(f"14: closing.slots.{k}.reason {v.get('reason')!r} not in the OAS enum")
    types = None
    for path, ops in oas.get("paths", {}).items():
        if path.strip("/").endswith("get_account"):
            from builder.oas_bindings import _resp_schema
            arr = [(v.get("items") or {}).get("properties") or {} for v in (_resp_schema(oas, "get_account").get("properties") or {}).values() if (v or {}).get("type") == "array"]
            types = next((p.get("type", {}).get("enum") for p in arr if p.get("type")), None)
    for t in ((rp.get("products") or {}).get("floor_by_type") or {}):
        if types and t not in types and t != "*":     # '*' = the floor for any type (gap 3)
            errs.append(f"14: product type {t!r} not in the OAS get_account enum")
    for q in (rp.get("identity") or {}).get("questions") or []:
        if not q.get("blocked") and enum("verify_identity", "field") and q.get("field") not in enum("verify_identity", "field"):
            errs.append(f"14: identity field {q.get('field')!r} not in the OAS enum and not blocked")
    for coll in ("events", "who_rules"):
        for e in rp.get(coll) or []:
            if e.get("blocked"):
                continue
            if e.get("outcome") and e_out and e["outcome"] not in e_out:
                errs.append(f"14: {coll} outcome {e['outcome']!r} not in the OAS enum")
            if e.get("note_reason") and e_n and e["note_reason"] not in e_n:
                errs.append(f"14: {coll} note_reason {e['note_reason']!r} not in the OAS enum")
    for k, q in ((rp.get("transfer") or {}).get("queue_map") or {}).items():
        if e_q and q not in e_q:
            errs.append(f"14: transfer.queue_map.{k} {q!r} not in the OAS enum")
    # 15 event lines are speakable: no instruction prose in any events[].say / who_rules[].say
    from builder.policy_bridge import INSTRUCTION
    for coll in ("events", "who_rules"):
        for e in rp.get(coll) or []:
            if e.get("say") and INSTRUCTION.search(str(e["say"])):
                errs.append(f"15: {coll} {e.get('topic') or e.get('who')} say is instruction prose: {str(e['say'])[:60]!r}")
    # 16 code_exec input limit (code + data <= 128 KB on the platform): the hub code must leave room for the data
    limit_kb = float(os.environ.get("HUB_LIMIT_KB", "45"))
    hub = nodes.get("hub") or {}
    for a in hub.get("pre_actions") or []:
        code = (((a.get("function") or {}).get("parameters") or {}).get("properties") or {}).get("code", {}).get("default", "")
        if len(code) / 1024 > limit_kb:
            errs.append(f"16: hub code is {len(code)/1024:.1f} KB, over the {limit_kb:g} KB limit (code_exec takes code + data <= 128 KB)")
    # 17 hooks (gap 1): known points, closed-set conditions, speakable text with its quote; the greet says every
    #    unconditional opening hook (the recording clause included)
    from builder.policy_bridge import HOOK_POINTS
    greet = str(((nodes.get("greet") or {}).get("on_enter") or {}).get("text", ""))
    nrm = lambda s: re.sub(r"\W+", " ", str(s).lower()).strip()
    for h in rp.get("hooks") or []:
        if h.get("point") not in HOOK_POINTS:
            errs.append(f"17: hook {h.get('id')} point {h.get('point')!r} is not one of {HOOK_POINTS}")
        c = h.get("condition")
        if c and not all(re.match(r"^(band|product_type|outcome)=[^;=]+$", t) for t in str(c).split(";")):
            errs.append(f"17: hook {h.get('id')} condition {c!r} is outside the closed set")
        if not h.get("text") or INSTRUCTION.search(str(h["text"])) or not h.get("quote"):
            errs.append(f"17: hook {h.get('id')} needs speakable text and its quote: {str(h.get('text'))[:60]!r}")
        if h.get("point") == "opening" and not c and h.get("text"):
            plain = re.sub(r"\{\{\w+\}\}", "", greet)
            if nrm(re.sub(r"\{\w+\}", "", h["text"])) not in nrm(plain):
                errs.append(f"17: the greet does not say opening hook {h.get('id')}: {h['text'][:60]!r}")
    # 18 identity answer formats (gap 2) come from the closed set
    from builder.policy_bridge import FORMATS
    for q in (rp.get("identity") or {}).get("questions") or []:
        if not FORMATS.match(str(q.get("format") or "")):
            errs.append(f"18: identity {q.get('field')} format {q.get('format')!r} is not date|digits(n)|name|alnum|postcode|free")
    # 19 floor / acceptance / date rules (gaps 3-4) in Fork 3's shapes
    from builder.policy_bridge import ACCEPTANCE, DATE_ACTIONS, DATE_SITUATIONS, FLOOR_KINDS
    need = {"field": ("field",), "percent": ("percent",), "fixed": ("amount",), "max_fixed_percent": ("amount", "percent")}
    for t, f in ((rp.get("products") or {}).get("floor_by_type") or {}).items():
        if not isinstance(f, dict) or f.get("kind") not in FLOOR_KINDS or any(f.get(k) in (None, "") for k in need[f.get("kind")]):
            errs.append(f"19: floor_by_type.{t} {f!r} is not a field|percent|fixed|max_fixed_percent rule")
    acc = (rp.get("amounts") or {}).get("acceptance", "floor_to_full")
    if not (acc in ACCEPTANCE or (isinstance(acc, dict) and acc.get("kind") == "min_x" and isinstance(acc.get("min"), (int, float)))):
        errs.append(f"19: amounts.acceptance {acc!r} is not floor_to_full|full_only|above_full_allowed|min_x")
    for sit, r in (rp.get("date_rules") or {}).items():
        if sit not in DATE_SITUATIONS or not isinstance(r, dict) or r.get("action") not in DATE_ACTIONS:
            errs.append(f"19: date_rules.{sit} {r!r} is outside the closed sets")
        elif r.get("say") and (INSTRUCTION.search(r["say"]) or set(re.findall(r"<[A-Z_]+>", r["say"])) - {"<NAMED>", "<DATE>", "<DEADLINE>"}):
            errs.append(f"19: date_rules.{sit}.say is not a speakable line: {r['say'][:60]!r}")
    # 20 honesty: no 'recorded'/'scheduled'/'transferred'/'saved'/'booked' in any line spoken before a write succeeds
    #    (greet, hooks other than on_promise_recorded, sentences other than recorded/text_message, event/who lines)
    from builder.policy_bridge import HONESTY, RESULT_POINTS, RESULT_SENTENCES
    lines = [("greet", greet)]
    lines += [(f"hook {h.get('id')} ({h.get('point')})", h.get("text")) for h in rp.get("hooks") or [] if h.get("point") not in RESULT_POINTS]
    lines += [(f"sentence {k}", (v or {}).get("text")) for k, v in (rp.get("sentences") or {}).items()
              if k not in RESULT_SENTENCES and isinstance(v, dict)]
    lines += [(f"{c} {e.get('topic') or e.get('who')}", e.get("say")) for c in ("events", "who_rules") for e in rp.get(c) or []]
    for where, t in lines:
        m = HONESTY.search(str(t or ""))
        if m:
            errs.append(f"20: {where} says {m.group(1)!r} before any tool result: {str(t)[:70]!r}")
    # 9 unstable unmapped
    # only where unmapped rules are compiled: the policy's unmapped_rules (reducer input) and the free-talk prompts.
    # (A short generic phrase like "Ask once more." can legitimately appear elsewhere, e.g. a fixed sentence.)
    compiled = {u.get("quote") for u in rp.get("unmapped_rules") or []}
    prompts = " ".join(str(n.get("task_message", "")) for k, n in nodes.items() if k.startswith("talk_"))
    for q in unstable_quotes:
        if q and (q in compiled or ("- " + q) in prompts or (len(q) >= 25 and q in prompts)):
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
