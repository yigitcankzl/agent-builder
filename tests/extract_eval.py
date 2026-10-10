"""Extraction measurement runner for reducer contract v2 (chat API only; refuses to run while a simulation is active).

    python3 tests/extract_eval.py <cases.json> [--only ID,ID] [--out results/extract_eval.json]

Cases file:
{
 "vocab": {"topics": [...], "identity_fields": [...]},            # optional; defaults below
 "cases": [{
   "id": "X01", "now": "2026-10-14T11:00",                         # now is optional
   "context": [{"agent": "...", "customer": "..."}, ...],          # earlier turns, spoken verbatim by the eval agent
   "agent": "the agent line right before the measured message",    # optional
   "customer": ["the customer's last message(s)"],                 # several = a split utterance; ev is read after the last
   "expected": {"kind": "date", "also": "reject", "st": "complete", "prod": "", "d": "", "m": "", "wd": "tue", ...},
   "tags": ["date", "pieces", ...]
 }]
}
Only keys present in `expected` are compared (besides kind/st). Workflow: a minimal chat graph with the generated `ev`
field and a hub that rotates the token and speaks the scripted agent lines; nothing is decided.
"""
import argparse, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
import freya
from builder.engine import event_field as EF

STATE = os.path.join(ROOT, "tests", ".eval-agents.json")
VOCAB = {"topics": ["injection", "hardship", "dispute", "paid", "restructure", "human", "stop", "decline", "purpose", "change_promise", "terms", "scam",
                    "robot", "unknown_info", "other"],
         "identity_fields": ["date_of_birth", "phone_last4"]}
DATE_KEYS = ("rel", "d", "m", "wd", "wk", "vague")
AMOUNT_KEYS = ("amt",)
TOPICS = VOCAB["topics"]
TRIGGER_KINDS = {"identity", "accept", "yes", "callback"}        # kinds that can lead to a tool call in the reducer
NON_CHANGING = {("other", "none")}

HUB = r"""import json, datetime
try:
    runs = int(vars.get('hub_runs') or 0) + 1
    vars['hub_runs'] = str(runs)
    us = datetime.datetime.now().microsecond + runs * 7919
    letters = 'abcdefghjkmnpqrstuvwxyz'
    nt = 'k'
    for _ in range(5):
        nt = nt + letters[us % 23]
        us = us // 23
    vars['ev_tok'] = nt
    try:
        script = json.loads(str(vars.get('script') or '[]'))
    except Exception:
        script = []
    i = int(vars.get('script_i') or 0)
    vars['say_next'] = script[i] if i < len(script) else 'Okay.'
    vars['script_i'] = str(i + 1)
except Exception as e:
    vars['say_next'] = 'Okay.'
    vars['hub_error'] = str(e)[:200]
"""


def workflow(vocab):
    ev = EF.field(vocab)
    conv = lambda name, on_enter: {"name": name, "node_type": "conversation", "on_enter": on_enter, "max_node_turns": 80,
                                   "task_message": "Reply with one short neutral sentence. No tool call is allowed.",
                                   "extraction_schema": [ev], "transitions": [{"target_node": "hub", "description": "always", "condition": {"operator": "always"}}]}
    return {"initial_node": "talk", "test_variables": {"ev_tok": "kstart"},
            "system_prompt": "You are a bank's digital assistant on a phone call. English. One short sentence.",
            "nodes": {"talk": conv("talk", {"type": "llm"}),
                      "say": conv("say", {"type": "tts", "text": "{{say_next}}"}),
                      "hub": {"name": "hub", "node_type": "code", "passthrough": True, "passthrough_default_transition": "say",
                              "on_enter": {"type": "silent"},
                              "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                               "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": HUB},
                                                                                               "timeout_ms": {"type": "number", "default": 10000}}}}}],
                              "transitions": [{"target_node": "say", "description": "always", "condition": {"operator": "always"}}]}}}


def simulation_active():
    try:
        sims = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id()).get("simulations") or []
    except Exception:
        return False
    return any(str(s.get("status")).lower() in ("running", "pending", "queued", "in_progress") for s in sims)


RETRIES = 0   # measurement rule: no re-send on 503/504; the case counts as unmeasured


def send(wid, call, msg, cv, log):
    """-> (call_id, response, ok). One attempt per message (RETRIES re-sends at most)."""
    body = {"workflowId": wid, "message": msg, "customerVariables": cv}
    if call:
        body["callId"] = call
    for attempt in range(1 + RETRIES):
        try:
            r = freya.api("POST", "/api/v2/chat/message", body)
            return r.get("callId", call), r.get("response"), True
        except RuntimeError as e:
            log.append(str(e)[:80])
            if attempt < RETRIES:
                time.sleep(6)
    return call, None, False


PHASE_ASK = {"opening": "Hello?", "third_party": "When could I reach them?", "identity": "Could you give me the answer, please?",
             "negotiation": "When can you pay?", "readback": "Do you confirm?"}


def from_cursor(c):
    """Adapter for tests/fixtures/reducer/extraction_cases.json (Cursor). Only the turn layout is assumed here: a piece
    said before the measured message gets a neutral phase question before the first piece and 'Go on, please.'
    between pieces. The labels are compared as given; a v2 `rel` key on a who-event is compared against `party`."""
    ctx, exp = c["context"], c["expected"]
    earlier = list(ctx.get("earlier_customer") or [])
    payload = dict(exp.get("payload") or {})
    if exp["kind"] == "who" and "rel" in payload:
        payload["party"] = payload.pop("rel")
    e = dict(kind=exp["kind"], also=exp.get("also", "none"), st=exp.get("st", "complete"), **payload)
    if exp.get("prod"):
        e["prod"] = exp["prod"]
    agents = ([PHASE_ASK.get(ctx.get("phase"), "Yes?")] + ["Go on, please."] * (len(earlier) - 1) if earlier else []) + [ctx["agent"]]
    return {"id": c["id"], "now": ctx.get("now", "2026-10-14T11:00"), "agents": agents, "customer": earlier + [c["customer"]],
            "expected": e, "debatable": bool(c.get("debatable")), "tags": [c.get("covers", "")]}


def run_case(wid, case):
    """Turn plan: an opener (chat does not route turn 1), then a 'ready' turn makes the hub speak the first scripted
    agent line; every customer line is followed by the next scripted agent line."""
    if "agents" in case:   # adapted (Cursor) layout: agents[i] is spoken right before customer[i]
        script, customer_lines = list(case["agents"]), list(case["customer"])
    else:
        agent_lines = [t["agent"] for t in case.get("context", [])] + ([case["agent"]] if case.get("agent") else [])
        customer_lines = [t["customer"] for t in case.get("context", [])] + list(case["customer"])
        script = agent_lines + ["Go on, please."] * max(len(case["customer"]) - 1, 0)
    cv = {"customer_id": "c_eval", "now": case.get("now", "2026-10-14T11:00"), "script": json.dumps(script)}
    errs, call = [], None
    call, _, ok = send(wid, None, "Hello?", cv, errs)
    if ok and script:
        call, _, ok = send(wid, call, "Yes, go ahead.", cv, errs)     # makes the hub speak script[0]
    for line in customer_lines:
        if not ok:
            break
        call, _, ok = send(wid, call, line, cv, errs)
    if call:
        try:
            freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception:
            pass
    if not ok:
        return {"id": case["id"], "call_id": call, "unmeasured": True, "http_errors": errs}
    time.sleep(2)
    got, raw = None, None
    try:
        msgs = freya.get_call(call)["messages"]
    except Exception as e:
        return {"id": case["id"], "unmeasured": True, "error": str(e)[:120], "http_errors": errs}
    last = case["customer"][-1]
    for m in msgs:
        t = str(m.get("message"))
        if m.get("role") == "system" and ('"variable_extracted"' in t or '"extraction_failed"' in t):
            e = json.loads(t)
            if e.get("name") == "ev" and e.get("input_text") == last:
                raw = e.get("value")
                got = EF.parse(raw, TOPICS) if e["event"] == "variable_extracted" else None
    return {"id": case["id"], "call_id": call, "raw": raw, "got": got, "http_errors": errs}


def score(case, res):
    exp, got = case["expected"], res.get("got")
    f = dict(kind_ok=False, st_ok=False, fields_ok=True, date_amount_case=False, date_amount_ok=True, partial_none_case=False,
             state_change_violation=False, identity_case=False, identity_skip=False, wrong_trigger=False,
             unsure_case=False, unsure_ok=True, extracted=got is not None)
    gk, gs = (got or {}).get("kind"), (got or {}).get("st")
    f["kind_ok"] = gk == exp["kind"]
    f["st_ok"] = gs == exp.get("st", "complete")
    for k, v in exp.items():
        if k in ("kind", "st"):
            continue
        if (got or {}).get(k, "") != v:
            f["fields_ok"] = False
    if any(k in exp for k in DATE_KEYS + AMOUNT_KEYS) and exp.get("st", "complete") == "complete":
        f["date_amount_case"] = True
        f["date_amount_ok"] = all((got or {}).get(k, "") == exp[k] for k in DATE_KEYS + AMOUNT_KEYS if k in exp)
    if exp.get("st") in ("partial", "none"):
        f["partial_none_case"] = True
        f["state_change_violation"] = not (gs in ("partial", "none") or (gk, gs) in NON_CHANGING)
    if exp["kind"] == "identity":
        f["identity_case"] = True
        f["identity_skip"] = gk != "identity" or (got or {}).get("ans", "") != exp.get("ans", (got or {}).get("ans", ""))
    if gk in TRIGGER_KINDS and gk != exp["kind"]:
        f["wrong_trigger"] = True
    if exp.get("st") == "ambiguous":
        f["unsure_case"] = True
        f["unsure_ok"] = gs in ("ambiguous", "partial", "none") or gk == "other"
    return f


def report(cases, results):
    unmeasured = [r["id"] for r in results if r.get("unmeasured")]
    all_rows = [(c, r, score(c, r)) for c, r in zip(cases, results) if not r.get("unmeasured")]
    exact = lambda s: s["extracted"] and s["kind_ok"] and s["st_ok"] and s["fields_ok"]
    fam = {}
    for c, r, s in all_rows:
        f = (c.get("tags") or [""])[0] or "-"
        fam.setdefault(f, [0, 0])
        fam[f][0] += exact(s); fam[f][1] += 1
    print(f"\nmeasured {len(all_rows)} / {len(results)}; unmeasured (HTTP error, not re-sent): {len(unmeasured)} {unmeasured}")
    print("PER FAMILY (exact match: kind, st and every expected field)")
    for f in sorted(fam):
        print(f"   {f:28} {fam[f][0]}/{fam[f][1]}")
    deb_rows = [(c, r, s) for c, r, s in all_rows if c.get("debatable")]
    print(f"DEBATABLE (reported separately, not in the gates): {sum(exact(s) for _, _, s in deb_rows)}/{len(deb_rows)} exact")
    for c, r, s in deb_rows:
        if not exact(s):
            print(f"   {c['id']}: raw={r.get('raw')!r} expected={c['expected']} call={r.get('call_id')}")
    rows = [(c, r, s) for c, r, s in all_rows if not c.get("debatable")]
    n = len(rows)
    pct = lambda a, b: f"{a}/{b}" + (f" ({100 * a / b:.0f}%)" if b else "")
    da = [s for _, _, s in rows if s["date_amount_case"]]
    pn = [s for _, _, s in rows if s["partial_none_case"]]
    idc = [s for _, _, s in rows if s["identity_case"]]
    un = [s for _, _, s in rows if s["unsure_case"]]
    m = dict(
        extracted=pct(sum(s["extracted"] for _, _, s in rows), n),
        kind=pct(sum(s["kind_ok"] for _, _, s in rows), n),
        status=pct(sum(s["st_ok"] for _, _, s in rows), n),
        all_expected_fields=pct(sum(s["fields_ok"] and s["kind_ok"] for _, _, s in rows), n),
        date_amount_fields=pct(sum(s["date_amount_ok"] for s in da), len(da)),
        state_change_on_partial_none=f"{sum(s['state_change_violation'] for s in pn)} violations / {len(pn)}",
        identity_skip=f"{sum(s['identity_skip'] for s in idc)} / {len(idc)}",
        wrong_trigger_kind=f"{sum(s['wrong_trigger'] for _, _, s in rows)} / {n}",
        unsure_to_clarify_or_talk=pct(sum(s["unsure_ok"] for s in un), len(un)))
    gates = dict(identity_and_trigger_zero=sum(s["identity_skip"] for s in idc) + sum(s["wrong_trigger"] for _, _, s in rows) == 0,
                 date_amount_100=all(s["date_amount_ok"] for s in da),
                 partial_none_zero=not any(s["state_change_violation"] for s in pn),
                 kind_95=n > 0 and sum(s["kind_ok"] for _, _, s in rows) / n >= 0.95,
                 unsure_all=all(s["unsure_ok"] for s in un))
    print("\nMETRICS", json.dumps(m, indent=1))
    print("GATES", json.dumps(gates), "PASS" if all(gates.values()) else "FAIL")
    for c, r, s in rows:
        bad = [k for k in ("kind_ok", "st_ok", "fields_ok", "date_amount_ok", "unsure_ok") if not s[k]] + \
              [k for k in ("state_change_violation", "identity_skip", "wrong_trigger") if s[k]]
        if bad or not s["extracted"]:
            print(f"  {c['id']}: {bad or ['not_extracted']} raw={r.get('raw')!r} expected={c['expected']} call={r.get('call_id')} http={r.get('http_errors')}")
    return m, gates, all_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cases"); ap.add_argument("--only"); ap.add_argument("--out")
    a = ap.parse_args()
    spec = json.load(open(a.cases))
    cases = [c for c in spec["cases"] if not a.only or c["id"] in a.only.split(",")]
    if cases and isinstance(cases[0].get("context"), dict):   # Cursor's extraction_cases.json layout
        cases = [from_cursor(c) for c in cases]
    if simulation_active():
        sys.exit("a simulation is running in this workspace; extraction eval is chat-only and waits for it to finish")
    TOPICS = (spec.get("vocab") or VOCAB)["topics"]
    wf = workflow(spec.get("vocab") or VOCAB)
    print("dry run:", freya.validate_workflow("eval-ev", wf))
    ids = freya.save_workflow("eval-ev", wf, state_file=STATE)
    results = []
    for c in cases:
        r = run_case(ids["workflow_id"], c)
        print(c["id"], "->", r.get("raw"), "| http errors:", len(r.get("http_errors") or []))
        results.append(r)
    m, gates, rows = report(cases, results)
    out = a.out or os.path.join(ROOT, "results", "extract_eval_" + time.strftime("%H%M%S") + ".json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"cases_file": a.cases, "metrics": m, "gates": gates,
               "unmeasured": [dict(id=r["id"], call_id=r.get("call_id"), http=r.get("http_errors")) for r in results if r.get("unmeasured")],
               "rows": [dict(id=c["id"], expected=c["expected"], debatable=c.get("debatable", False), raw=r.get("raw"),
                             call_id=r.get("call_id"), score=s) for c, r, s in rows]},
              open(out, "w"), indent=1)
    print("report:", out)
