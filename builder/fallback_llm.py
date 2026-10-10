"""L3 fallback: a direct LLM workflow writer (FINAL-PLAN §1.4 / §2).

One `claude -p` call (no tools, no simulation, no Freya call) reads the brief, the brief's own OpenAPI file, the kit docs
and examples/base-agent.json, and writes a complete Freya workflow. A local static check (shape, targets, OAS tools,
fields and enums, nulls, agent_config, code size, spoken placeholders) runs on it; one repair call on errors.

It runs in a thread from t0 and only writes a local candidate. The hook is in build.py main() only (build() unchanged;
the main path saves itself on exit 0, so there is never more than one save per slot):

    t0 = time.time()
    fb = fallback_llm.Fallback(briefs, openapi).start()                                      # at t0, local only
    r = build(briefs, openapi, a.slot, client, a.out_dir, a.trace_dir, a.runs, min(budget, fallback_llm.MAIN_CAP_S))
    r = fallback_llm.rescue(r, fb, client, r["slot"], a.out_dir, t_end=t0 + budget)          # exit 2 -> L3 saved once
    # exit 0 / 3: rescue() only cancels the thread. L3 saved: exit_code 0, candidate "llm", fallback_used "L3".

    python3 builder/fallback_llm.py <brief files or folders...> <openapi.json> [--out f.json]   # local, prints the check
"""
import json, os, re, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.policy_extract import MODEL, parse_json, read_files

CODE_LIMIT = 131072                      # code_exec: code + data
CAP_S = 600                              # the L3 thread's own cap (plan: 10 min)
# build.py exit-2 signals (Fork 4, 699a736). S2/S5 with next=L2 also go to L3 until an L2 degraded build exists.
L3_SIGNALS = {"main_failed", "EXTRACT", "S2", "S3", "S5", "GUARD", "S7"}
ABORT_SIGNALS = {"S0"}                   # exit 3, engine not loaded: a packaging bug, never covered by L3
MAIN_CAP_S = 15 * 60 + 90                # build() budget while L3 runs: L0+L1 hard cap 15 min (its deadline is budget - 90 s)
SAVE_RESERVE_S = 150                     # save + export after the selection

PROMPT = """You write a Freya workflow (a phone agent) for the bank brief below. Output ONLY the workflow JSON object, nothing else.

Follow the format docs exactly. Use EXAMPLE (a small working agent for a different brief) as the pattern for the JSON shape, not
as the answer: every rule, sentence, field and value must come from THIS brief and THIS tool API.

Required:
- Top-level keys: initial_node, system_prompt, nodes, global_nodes, test_variables, and tools for lifecycle tools. No agent_config.
  No null anywhere: leave an optional field out instead.
- The first node confirms the person and runs the identity check the brief asks for, with the identity tool, before anything
  about the account or the reason for the call is said. Move to the next node on the tool's result (a transition on the
  response variable, as in EXAMPLE), never on what the customer says.
- The next node(s) handle the rest of the call with EVERY other tool of the tool API as an api_call function tool:
  url = the server URL + the path, method as in the API, body properties with exactly the API's field names, `enum` exactly the
  API's allowed values, `required` as in the API, and `"default": "{{customer_id}}"` for customer_id. The tool that records how
  the call ended goes in the workflow-level tools with config.alwaysRunsAt ["end_of_call"], as in EXAMPLE.
- Put the brief's rules in the task_message of the node where they apply: who may be told what and when, the questions and their
  order, how many attempts, deadlines and limits, what to offer and what never to offer, exact sentences the brief requires
  (quote them), what to do for third parties, hardship, disputes, payments already made, requests for a human, and how each
  ending maps to the API's outcome and reason values. Never say something is recorded unless the tool succeeded.
- Spoken text (on_enter tts) may use {{x}} only for keys you put in test_variables, and test_variables holds the brief's call
  variables with sample values.
- Code (if any) has no {{ }} and stays small. No knowledge base, no transfer_call nodes unless the tool API has no transfer tool.
"""

REPAIR = """The workflow you wrote fails these checks. Return the complete corrected workflow JSON object only.

ERRORS:
{errors}

WORKFLOW:
{workflow}
"""


# ---------- the OpenAPI file, read the way the static check needs it ----------

def _deref(doc, s, seen=0):
    while isinstance(s, dict) and "$ref" in s and seen < 20:
        ref = s["$ref"]
        if not ref.startswith("#/"):
            return {}
        s = doc
        for part in ref[2:].split("/"):
            s = s.get(part.replace("~1", "/").replace("~0", "~"), {})
        seen += 1
    if isinstance(s, dict) and s.get("allOf"):
        out = {"properties": {}, "required": []}
        for sub in s["allOf"]:
            sub = _deref(doc, sub, seen + 1)
            out["properties"].update(sub.get("properties") or {})
            out["required"] += sub.get("required") or []
        return out
    return s if isinstance(s, dict) else {}


def oas_ops(path):
    """{tool name: {url, method, fields: {name: enum list or None}, required}} from an OpenAPI file."""
    doc = json.load(open(path))
    server = ((doc.get("servers") or [{}])[0].get("url") or "").rstrip("/")
    ops = {}
    for p, items in (doc.get("paths") or {}).items():
        for method, op in items.items():
            if not isinstance(op, dict) or method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            content = (op.get("requestBody") or {}).get("content") or {}
            media = content.get("application/json") or next((v for k, v in content.items() if "json" in k), {})
            s = _deref(doc, media.get("schema") or {})
            fields = {k: _deref(doc, v).get("enum") for k, v in (s.get("properties") or {}).items()}
            name = p.strip("/").split("/")[-1]
            ops[name] = {"url": server + p, "path": p, "method": method.upper(), "fields": fields,
                         "required": list(s.get("required") or []), "operationId": op.get("operationId")}
    return ops


# ---------- the static check ----------

def _walk(x, path="$"):
    yield path, x
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def _default(prop):
    return (prop or {}).get("default") if isinstance(prop, dict) else None


def check(wf, ops):
    """Errors that make the candidate unusable. An empty list means statically valid."""
    errs = []
    if not isinstance(wf, dict):
        return ["the output is not a JSON object"]
    nodes = wf.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return ["nodes is missing or empty"]
    if wf.get("initial_node") not in nodes:
        errs.append(f"initial_node {wf.get('initial_node')!r} is not a node")
    for path, v in _walk(wf):
        if v is None:
            errs.append(f"null at {path}")
        if path.endswith(".agent_config"):
            errs.append(f"agent_config at {path}")
    types = {"conversation", "api_request", "code", "end_call"}
    for key, n in nodes.items():
        if not isinstance(n, dict):
            errs.append(f"node {key} is not an object"); continue
        if n.get("node_type") not in types:
            errs.append(f"node {key}: node_type {n.get('node_type')!r}")
        for t in n.get("transitions") or []:
            if t.get("target_node") not in nodes:
                errs.append(f"node {key}: transition target {t.get('target_node')!r} does not exist")
        for f in ("passthrough_default_transition", "max_turn_transition"):
            if n.get(f) and n[f] not in nodes:
                errs.append(f"node {key}: {f} {n[f]!r} does not exist")
    # tools: every api_call must be an OAS operation with exact fields and enums
    used = set()
    tools = [("workflow", t) for t in wf.get("tools") or []]
    for key, n in nodes.items():
        tools += [(key, t) for t in (n.get("tools") or []) + (n.get("pre_actions") or []) if isinstance(n, dict)]
    for where, t in tools:
        fn = (t or {}).get("function") or {}
        if fn.get("handler") != "__function__:api_call":
            continue
        props = (fn.get("parameters") or {}).get("properties") or {}
        url = str(_default(props.get("url")) or "")
        op_name = next((k for k, o in ops.items() if url == o["url"] or (url.endswith(o["path"]) and o["path"])), None)
        if not op_name:
            errs.append(f"{where}: tool {fn.get('name')!r} url {url!r} is not an operation of the API"); continue
        op = ops[op_name]; used.add(op_name)
        if str(_default(props.get("method")) or "POST").upper() != op["method"]:
            errs.append(f"{where}: tool {op_name} method {_default(props.get('method'))!r}, the API says {op['method']}")
        body = (props.get("body") or {}).get("properties") or {}
        for f, spec in body.items():
            if f not in op["fields"]:
                errs.append(f"{where}: tool {op_name} body field {f!r} is not in the API ({sorted(op['fields'])})"); continue
            en = (spec or {}).get("enum") if isinstance(spec, dict) else None
            if en and op["fields"][f] and not set(en) <= set(op["fields"][f]):
                errs.append(f"{where}: tool {op_name} field {f} enum {sorted(set(en) - set(op['fields'][f]))} not in the API enum {op['fields'][f]}")
            if en and not op["fields"][f]:
                errs.append(f"{where}: tool {op_name} field {f} has an enum the API does not define")
        for f in op["required"]:
            if f not in body:
                errs.append(f"{where}: tool {op_name} misses the required field {f!r}")
    for name in ops:
        if name not in used:
            errs.append(f"the API operation {name} is not used by any tool")
    # code size and placeholders in code
    for path, v in _walk(wf):
        if isinstance(v, str) and (path.endswith(".code.default") or path.endswith("_process_code")):
            if len(v.encode()) > CODE_LIMIT:
                errs.append(f"{path}: code is {len(v.encode())} bytes, the limit is {CODE_LIMIT}")
            if "{{" in v:
                errs.append(f"{path}: code contains {{{{ }}}}")
    # spoken placeholders must be test variables
    tv = set((wf.get("test_variables") or {}).keys())
    for key, n in nodes.items():
        text = ((n.get("on_enter") or {}).get("text") or "") if isinstance(n, dict) else ""
        for var in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", text):
            if var not in tv:
                errs.append(f"node {key}: spoken placeholder {{{{{var}}}}} is not a test_variables key")
    return errs


# ---------- the writer ----------

def _clean(x):
    """The example as exported has nulls and editor positions; the writer should not copy them."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if v is not None and k != "position"}
    return [_clean(v) for v in x] if isinstance(x, list) else x


def _docs():
    read = lambda p: open(os.path.join(ROOT, p), errors="replace").read()
    example = json.dumps(_clean(json.load(open(os.path.join(ROOT, "examples", "base-agent.json")))), indent=1)
    return (f"=== docs/workflow-format.md ===\n{read('docs/workflow-format.md')}\n\n=== docs/tools-and-code.md ===\n{read('docs/tools-and-code.md')}"
            f"\n\n=== EXAMPLE: examples/base-agent.json ===\n{example}")


class Fallback:
    """The L3 writer in a background thread. cancel() kills a running claude call."""

    def __init__(self, briefs, openapi, log=None, cap_s=CAP_S):
        self.briefs, self.openapi, self.log, self.cap_s = briefs, openapi, log or (lambda **kw: None), cap_s
        self.proc, self.cancelled, self.done = None, False, threading.Event()
        self.result = {"workflow": None, "errors": ["not run"], "seconds": None, "calls": []}

    def start(self):
        self.t0 = time.time()
        threading.Thread(target=self._run, daemon=True, name="l3-fallback").start()
        return self

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def wait(self, timeout):
        self.done.wait(max(0, timeout))
        return self.result

    def _claude(self, prompt, purpose):
        left = self.cap_s - (time.time() - self.t0)
        if self.cancelled or left < 20:
            raise RuntimeError("cancelled" if self.cancelled else "L3 cap reached")
        cmd = ["claude", "-p", "--output-format", "json", "--tools", "", "--no-session-persistence"] + (["--model", MODEL] if MODEL else [])
        t = time.time()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if self.cancelled:                                   # cancel() ran between the check above and Popen
            self.proc.kill()
        try:
            out, err = self.proc.communicate(prompt, timeout=left)
        except subprocess.TimeoutExpired:
            self.proc.kill(); self.proc.communicate()
            raise RuntimeError("L3 cap reached during the claude call")
        dt = round(time.time() - t, 1)
        if self.cancelled:
            raise RuntimeError("cancelled")
        try:
            o = json.loads(out)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude -p failed: {(err or out)[:300]}")
        rec = {"purpose": purpose, "seconds": dt, "ok": not o.get("is_error"), "cost_usd": o.get("total_cost_usd"),
               "model": ",".join((o.get("modelUsage") or {}).keys()) or MODEL or "default"}
        self.result["calls"].append(rec); self.log(**rec)
        return o.get("result", "")

    def _run(self):
        try:
            # ponytail: same brief sources as the main path (read_files); switch to Fork 4's manifest when it lands
            files = read_files(self.briefs)
            ops = oas_ops(self.openapi)
            material = "\n\n".join(f"=== BRIEF FILE: {k} ===\n{v}" for k, v in files.items())
            prompt = (PROMPT + "\n\n" + _docs() + "\n\n=== TOOL API (the brief's own OpenAPI file) ===\n" + open(self.openapi).read()
                      + "\n\n" + material)
            wf, errs = None, []
            try:
                wf = parse_json(self._claude(prompt, "L3 fallback: write workflow"))
                errs = check(wf, ops)
            except (ValueError, json.JSONDecodeError) as e:
                errs = [f"the output is not valid JSON: {e}"]
            if errs:
                fixed = self._claude(PROMPT + "\n\n" + REPAIR.format(errors="\n".join(errs[:40]), workflow=json.dumps(wf, indent=1) if wf else "(none)")
                                     + "\n\n=== TOOL API ===\n" + open(self.openapi).read(), "L3 fallback: repair")
                try:
                    wf = parse_json(fixed); errs = check(wf, ops)
                except (ValueError, json.JSONDecodeError) as e:
                    errs = [f"the repaired output is not valid JSON: {e}"]
            self.result.update(workflow=wf, errors=errs)
        except Exception as e:
            self.result.update(errors=[f"L3 failed: {str(e)[:300]}"])
        finally:
            self.result["seconds"] = round(time.time() - self.t0, 1)
            self.done.set()


def select_candidate(main_wf, signals, fb, wait_s):
    """-> (workflow or None, candidate 'main'|'llm'|'none'|'abort', reason).
    main_wf is the main path's validator-passing workflow, or None when it failed. signals: codes raised on the way."""
    signals = set(signals or [])
    if signals & ABORT_SIGNALS:
        fb and fb.cancel()
        return None, "abort", ",".join(sorted(signals & ABORT_SIGNALS))
    if main_wf is not None and not signals & L3_SIGNALS:
        fb and fb.cancel()                                   # build time is tie-break 2
        return main_wf, "main", None
    why = ",".join(sorted(signals & L3_SIGNALS)) or "main_failed"
    if fb is None:
        return None, "none", why + "; no L3 thread"
    r = fb.wait(wait_s)
    if r["workflow"] is not None and not r["errors"]:
        return r["workflow"], "llm", why
    return None, "none", why + "; L3 " + ("not ready in time" if not fb.done.is_set() else "invalid: " + "; ".join(r["errors"][:3]))


def rescue(result, fb, client, slot, out_dir, t_end):
    """The build.py hook for exit 2: pick the L3 candidate and save it ONCE to the same slot. Returns the updated result.
    Exit 3 (S0) and exit 0 only cancel the thread. t_end: the wall-clock time the whole build must end by."""
    code = result.get("exit_code")
    if code != 2:
        fb.cancel()
        return result
    t = time.time()
    wf, cand, why = select_candidate(None, {result.get("signal") or "main_failed"}, fb, wait_s=t_end - t - SAVE_RESERVE_S)
    ev = {"event": "fallback_selection", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "candidate": cand, "reason": why,
          "waited_s": round(time.time() - t, 1), "l3_seconds": fb.result.get("seconds"), "l3_errors": fb.result.get("errors")[:5],
          "l3_calls": fb.result.get("calls")}
    result.update(candidate=cand, candidate_reason=why)
    if wf is not None and time.time() < t_end - 30:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{slot}.workflow.json")
        if client is None:
            json.dump({"workflow": wf}, open(path, "w"), indent=1)
            ev["save"] = "skipped (no Freya client); written to " + path
        else:
            ids = client.save_workflow(slot, wf)                  # the one save of this build
            path = client.export_workflow(ids["workflow_id"], path)
            result.update(workflow_id=ids["workflow_id"], agent_id=ids["agent_id"], export=path)
            ev["save"] = {"workflow_id": ids["workflow_id"], "agent_id": ids["agent_id"], "export": path}
        result.update(exit_code=0, fallback_used="L3")
    else:
        fb.cancel()
    ev["exit_code"] = result["exit_code"]
    if result.get("trace"):
        from builder.trace import redact
        line = redact(json.dumps(ev, ensure_ascii=False, default=str))
        open(result["trace"], "a").write(line + "\n")
        txt = result["trace"].replace(".jsonl", ".txt")
        if os.path.exists(txt):
            open(txt, "a").write(f"[{ev['at']}] fallback_selection: {line[:4000]}\n")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+"); ap.add_argument("--out")
    a = ap.parse_args()
    fb = Fallback(a.inputs[:-1], a.inputs[-1], log=lambda **kw: print("  model call:", kw, flush=True)).start()
    r = fb.wait(CAP_S + 30)
    print(json.dumps({"seconds": r["seconds"], "errors": r["errors"], "calls": r["calls"],
                      "nodes": sorted((r["workflow"] or {}).get("nodes", {}))}, indent=1))
    if a.out and r["workflow"]:
        json.dump(r["workflow"], open(a.out, "w"), indent=1)
    sys.exit(0 if r["workflow"] and not r["errors"] else 1)
