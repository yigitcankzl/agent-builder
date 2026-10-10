"""The builder: one command, brief files in, a Freya phone agent out.

    python3 builder/build.py <brief files or folders...> <openapi.json> [--slot NAME] [--runs 2] [--budget-min 25]
                             [--mock-freya] [--out-dir submission] [--trace-dir traces]

Pipeline (every step is written to the trace, traces/<slot>-<time>.jsonl plus a .txt summary):
  1. read the sources and the brief's OWN tool API file;
  2. policy extraction with Claude, `--runs` times in parallel (quote-verified, one repair round each); the runs are
     compared on the core fields, and unmapped rules are kept only when stable across runs;
  3. bridge -> generator -> static validator; on validator failure one repair pass (bridge another run's policy);
  4. save_workflow (one slot per brief, updated in place and published) -> export_workflow to <out-dir>/<slot>.workflow.json.
Time guard: the whole build stops at --budget-min (default 25, the rules allow 30). Fallback: if extraction fails, the
workflow stays invalid after the repair pass, or the guard fires before saving, nothing is saved, the trace records
`fallback_required` with the reason, the exit code is 2, and the previously exported workflow for that slot (if any)
stays the submission.

L3 fallback (builder/fallback_llm.py, Fork 5): the direct LLM workflow writer starts in its own thread as soon as the
sources are readable (not on S0, not when nothing is readable; --no-l3 turns it off). The main path is capped at
MAIN_CAP_S (15 min + 90 s) or --budget-min - 90 s, whichever is earlier. If the main path passes, L3 is cancelled
before the save. If it ends on EXTRACT, S2 or S5, build waits for L3 until budget - 150 s and, when L3's static
check passed, saves THAT workflow once and exports it (exit 0, fallback_used=L3, a fallback_selection trace event).
There is exactly one save per slot per build.

Exit codes (also `exit_code` in the JSON result; the trace has a `signal` event with the code):
  0  built, validated and saved (or --no-save)
  2  fallback_required: nothing saved, the previous export for the slot stays; `signal` names why and `next` the
     ladder step a fallback builder should take (S2 core sections missing, S5 validator, extraction failed, time guard)
  3  engine not loaded (S0): builder.engine.reducer / event_field failed to import or raised. A packaging bug: fix the
     clone. Nothing is saved, there is no LLM fallback (a dead stub agent must never be saved).
Signals (FINAL-PLAN section 2): S0 engine not loaded, S1 unreadable source / too little text (warning; abort only
when nothing is readable), S2 core sections missing after the targeted re-extraction,
S5 validator still failing after the repair pass, EXTRACT every extraction run failed, GUARD time guard.
"""
import argparse, concurrent.futures as cf, hashlib, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import generator
from builder.generator import generate, node_counts
from builder.policy_bridge import consolidate_unmapped, to_reducer
from builder.ingest import ingest, s1
from builder.integration import EngineNotLoaded, _load
from builder.engine.date_policy import core_missing
from builder.policy_extract import apply_reextraction, extract, read_files, reextract_core, reextract_fields
from builder.selftest import run_selftest, walk_smoke
from builder.trace import BuildTrace
from builder.validate_workflow import validate

CORE_KEYS = ("business_days", "deadline", "identity", "closing", "products", "attempts", "writes")


def core_signature(p):
    """The core fields a run must agree on (values only, quotes ignored)."""
    bd = p.get("business_days") or {}
    bands = [(b.get("min_days_late"), b.get("max_days_late"), b.get("days"), b.get("attempts")) for b in (p.get("deadline") or {}).get("bands") or []]
    idn = p.get("identity") or {}
    floor = {k: (v.get("kind"), v.get("field") or (v.get("params") or {}).get("field"), v.get("percent"), v.get("amount")) for k, v in ((p.get("products") or {}).get("floor_by_type") or {}).items()}
    cb = (p.get("writes") or {}).get("callback") or {}
    plan = {b: [(s.get("date_rule"), s.get("amount_rule")) for s in st] for b, st in ((p.get("attempts") or {}).get("plan") or {}).items()}
    return json.dumps({"holidays": sorted(bd.get("holidays") or []), "weekdays": sorted(bd.get("weekdays") or []), "bands": bands,
                       "identity": [q.get("field") for q in idn.get("questions") or []], "max_wrong": idn.get("max_wrong"),
                       "closing": sorted({(r.get("outcome"), r.get("reason") or None) for r in (p.get("closing") or {}).get("table") or []}, key=str),
                       "floor": floor, "callback": [cb.get("start"), cb.get("end")], "plan": plan}, sort_keys=True, default=str)


def default_slot(briefs):
    stems = [os.path.splitext(os.path.basename(b.rstrip("/")))[0] for b in briefs]
    return "+".join(stems)


class MockFreya:
    """Local stand-in for freya.py: save returns fake ids, export writes the workflow it was given."""
    def __init__(self):
        self.saved = {}

    def save_workflow(self, slot, wf):
        ids = {"workflow_id": "mock-wf-" + hashlib.sha1(slot.encode()).hexdigest()[:8], "agent_id": "mock-ag-" + hashlib.sha1(slot[::-1].encode()).hexdigest()[:8]}
        self.saved[ids["workflow_id"]] = wf
        return ids

    def export_workflow(self, workflow_id, path):
        json.dump({"workflow_id": workflow_id, "agent_id": "mock", "workflow": self.saved[workflow_id]}, open(path, "w"), indent=1)
        return path


def _sources(trace, briefs, openapi):
    files, manifest = ingest(briefs)
    trace.log("sources", files=[{"name": n, "chars": len(t), "sha1": hashlib.sha1(t.encode()).hexdigest()[:12]} for n, t in files.items()],
              manifest=manifest, openapi=os.path.basename(openapi), openapi_sha1=hashlib.sha1(open(openapi, "rb").read()).hexdigest()[:12])
    return files, manifest


def _rules_summary(policy):
    """Every extracted section with its quotes (the trace's 'rules extracted, with quotes')."""
    out = {}
    for k, v in policy.items():
        if isinstance(v, dict) and v.get("source"):
            out[k] = [s.get("quote") if isinstance(s, dict) else s for s in v["source"]][:6]
    for i, b in enumerate((policy.get("deadline") or {}).get("bands") or []):
        out[f"deadline.bands[{i}]"] = {kk: b.get(kk) for kk in ("name", "min_days_late", "max_days_late", "days", "attempts")}
    for band, steps in ((policy.get("attempts") or {}).get("plan") or {}).items():
        out[f"attempts.plan.{band}"] = [(s.get("date_rule"), s.get("amount_rule"), ((s.get("source") or [{}])[0] or {}).get("quote")) for s in steps]
    return out


MAIN_CAP_S = 15 * 60 + 90       # the main path's own cap; the rest of --budget-min is for the L3 candidate + one save
L3_SIGNALS = {"EXTRACT", "S2", "S5"}     # main-path failures the L3 writer may cover (never S0, S1 abort or GUARD: a late main build is never replaced)


def _save(freya_client, slot, wf, out_dir, trace, result, candidate):
    """The ONE save of a build (main or L3 candidate): save_workflow + export, traced."""
    if freya_client is None:
        trace.log("save", skipped=True, candidate=candidate, note="no Freya client (--no-save)")
        return
    ids = freya_client.save_workflow(slot, wf)
    path = freya_client.export_workflow(ids["workflow_id"], os.path.join(out_dir, f"{slot}.workflow.json"))
    result.update(workflow_id=ids["workflow_id"], agent_id=ids["agent_id"], export=path)
    trace.log("save", candidate=candidate, workflow_id=ids["workflow_id"], agent_id=ids["agent_id"],
              export=os.path.relpath(path, ROOT) if path.startswith(ROOT) else path)


def build(briefs, openapi, slot=None, freya_client=None, out_dir="submission", trace_dir="traces", runs=2,
          budget_s=25 * 60, extractor=extract, fallback=None, examiner=None):
    """fallback: None, or a factory (briefs, openapi, log) -> an object with start/cancel/wait (fallback_llm.Fallback).
    It starts as soon as the sources are readable and is used only when the main path ends on an L3 signal."""
    t0 = time.time()
    slot = slot or default_slot(briefs)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trace = BuildTrace(os.path.join(trace_dir, f"{slot}-{stamp}.jsonl"))
    t_end = t0 + budget_s
    deadline = min(t_end - 90, t0 + MAIN_CAP_S)     # the main path: keep 90 s for save and export, and the cap
    result = {"slot": slot, "trace": trace.path, "fallback_required": False}
    fb = [None]

    def finish(reason=None, code=0, signal=None, **extra):
        if not reason and fb[0]:
            fb[0].cancel()
            trace.log("fallback_selection", candidate="main", l3="cancelled")
        if reason and fb[0] and signal in L3_SIGNALS:
            wait = max(0, t_end - 150 - time.time())
            r = fb[0].wait(wait)
            ok = r.get("workflow") is not None and not r.get("errors")
            trace.log("fallback_selection", candidate="llm" if ok else "none", main_signal=signal, main_reason=reason,
                      waited_s=round(wait, 1), l3_seconds=r.get("seconds"), l3_errors=(r.get("errors") or [])[:5])
            if ok and time.time() < t_end - 30:
                os.makedirs(out_dir, exist_ok=True)
                json.dump(r["workflow"], open(os.path.join(out_dir, f"{slot}.l3.workflow.json"), "w"), indent=1)
                _save(freya_client, slot, r["workflow"], out_dir, trace, result, "llm")
                result.update(fallback_used="L3", main_signal=signal, main_reason=reason)
                reason, code = None, 0
            else:
                fb[0].cancel()
        elif reason and fb[0]:
            fb[0].cancel()
        if reason:
            code = code or 2
            result.update(fallback_required=True, fallback_reason=reason, signal=signal, **extra)
            trace.log("signal", signal=signal, exit_code=code, reason=reason, **extra)
            trace.log("fallback_required", reason=reason, action="nothing saved; the previous export for this slot stays the submission")
        result["seconds"] = round(time.time() - t0, 1)
        result["exit_code"] = code
        trace.log("end", seconds=result["seconds"], result={k: v for k, v in result.items() if k != "trace"})
        trace.summary(trace.path.replace(".jsonl", ".txt"))
        return result

    def engine_failed(e):
        trace.log("hub_import_failed", error=str(e)[:400])
        return finish(f"engine not loaded: {e}", 3, "S0", next="fix the clone (no fallback)")

    trace.log("start", slot=slot, briefs=[os.path.basename(b.rstrip("/")) for b in briefs], runs=runs, budget_s=budget_s)
    try:     # S0 before any model call: a clone without a loadable engine stops in seconds, not after extraction
        for mod, name in (("builder.engine.reducer", "hub_source"), ("builder.engine.event_field", "ev_field")):
            if not _load(mod, name):
                raise EngineNotLoaded(f"{mod} has no {name}")
    except EngineNotLoaded as e:
        return engine_failed(e)
    files, manifest = _sources(trace, briefs, openapi)
    brief_text = "\n".join(files.values())
    probs = s1(manifest, files)       # S1: unreadable sources / too little text
    if probs:
        trace.log("signal", signal="S1", level="warning" if any(t.strip() for t in files.values()) else "abort", problems=probs)
        result["s1"] = probs
    if not any(t.strip() for t in files.values()):
        return finish("no readable brief source: " + "; ".join(probs), 2, "S1", next="a human converts the source")
    if fallback is not None:          # the L3 writer runs from here, in its own thread, local only
        fb[0] = fallback(briefs, openapi, trace.model_call).start()
        trace.log("fallback_started", candidate="llm")
    # 1. extraction runs, in parallel
    policies = []
    with cf.ThreadPoolExecutor(runs + 1) as ex:
        # the independent examiner (sees only the sources and the OAS) runs in parallel with the extractions
        exam_f = ex.submit(examiner, briefs, openapi, trace, deadline) if examiner else None
        futs = [ex.submit(extractor, briefs, openapi, None, True, trace, deadline) for _ in range(runs)]
        for i, f in enumerate(futs, 1):
            try:
                p, rep = f.result()
                policies.append(p)
                trace.log("extraction_run", run=i, seconds=rep["seconds"], quotes_rejected=rep["quotes_rejected"],
                          quotes_repaired=rep["quotes_repaired"], quotes_unverified=rep["quotes_unverified"],
                          schema_errors=rep["errors"], oas_warnings=rep["oas_warnings"], core_missing=rep["core_missing"])
            except Exception as e:
                trace.log("extraction_run", run=i, error=str(e)[:400])
    if not policies:
        return finish("policy extraction failed in every run", 2, "EXTRACT", next="L3")
    # S2: core sections missing in EVERY run -> one targeted re-extraction; still missing -> fallback
    missing = [core_missing(p) for p in policies]
    if all(missing):
        want = sorted({m for ms in missing for m in ms})
        trace.log("core_missing", runs=missing, action="targeted re-extraction of " + ", ".join(want))
        try:
            got = reextract_core(briefs, want, openapi, trace, deadline) if time.time() < deadline - 60 else {}
        except Exception as e:
            got = {}
            trace.log("re_extract_core", error=str(e)[:300])
        for sec, val in got.items():
            policies[0][sec] = val
        still = core_missing(policies[0])
        trace.log("re_extract_core", filled=sorted(got), still_missing=still)
        if still:
            lvl = "L3" if any(m.split(".")[0] in ("identity", "closing") for m in still) else "L2"
            return finish(f"core sections missing after re-extraction: {still}", 2, "S2", core_missing=still, next=lvl)
    if exam_f is not None:     # Q1: compare with the examiner; each disagreement re-checked once (quotes, memo order)
        try:
            answers = exam_f.result()
            trace.log("examiner", answered=sorted(answers))
            if time.time() < deadline - 120:
                from builder.examiner import reconcile
                policies[0], erep = reconcile(policies[0], briefs, openapi, answers, trace, deadline, log=trace.log)
            else:
                from builder.examiner import disagreements
                erep = {"disagreements": len(disagreements(policies[0], answers)), "skipped": "no time for the re-check"}
            trace.log("examiner_result", **erep)
            result["examiner"] = erep
        except Exception as e:
            trace.log("examiner", error=str(e)[:300])
    sigs = [core_signature(p) for p in policies]
    agree = len(set(sigs)) == 1
    trace.log("core_agreement", runs=len(policies), agree=agree,
              note=None if agree else "runs disagree on core fields: the first run is used, the other is the repair candidate")
    primary = policies[0]
    trace.log("rules_extracted", rules=_rules_summary(primary))
    trace.log("superseded", entries=primary.get("superseded") or [])
    stable, unstable = consolidate_unmapped(policies)
    trace.log("unmapped", stable=[u["quote"] for u in stable], dropped_unstable=[u["quote"] for u in unstable],
              note="only stable rules become soft rules; with one run nothing is stable" if len(policies) == 1 else None)
    # 2. bridge -> generate -> validate, one repair pass
    attempt_order = [primary] + [p for p in policies[1:]]
    wf = rp = None
    for k, pol in enumerate(attempt_order[:2]):
        rp, brep = to_reducer(pol, openapi, stable, brief_text)
        trace.log("bridge", attempt=k + 1, api_mismatch=brep["api_mismatch"], notes=brep["notes"], schema_errors=brep["errors"],
                  topics=brep["events"], identity_blocked=(rp.get("identity") or {}).get("blocked"), hangup_default=rp.get("hangup_default"))
        mism = brep["api_mismatch"]
        if mism and k == 0 and time.time() < deadline - 60:
            # targeted re-extraction (contract §13.2): only the mismatching fields, once
            try:
                res = reextract_fields(briefs, mism, openapi, trace, deadline)
            except Exception as e:
                res = {}
                trace.log("re_extract", error=str(e)[:300])
            for m in mism:
                r = res.get(m["policy_path"]) or {}
                trace.log("re_extract", field=m["field"], policy_path=m["policy_path"], old=m["value"], new=r.get("value"),
                          quote=(r.get("source") or {}).get("quote"), why=r.get("why"),
                          result="mapped (sourced, in the OAS enum)" if r.get("accepted") else "kept block")
            if any(r.get("accepted") for r in res.values()):
                pol = apply_reextraction(pol, mism, res)
                rp, brep = to_reducer(pol, openapi, stable, brief_text)
                trace.log("bridge", attempt="1-reextracted", api_mismatch=brep["api_mismatch"], notes=brep["notes"],
                          identity_blocked=(rp.get("identity") or {}).get("blocked"))
        try:
            wf = generate(rp, openapi)
        except EngineNotLoaded as e:
            return engine_failed(e)
        if "stub" in (generator.GENERATED_FROM.get("hub"), generator.GENERATED_FROM.get("ev")):
            return engine_failed("the generator used a stub hub or event field")
        errs = validate(wf, rp, openapi, [u["quote"] for u in unstable])
        trace.log("validator", attempt=k + 1, passed=not errs, errors=errs, hub_code=generator.GENERATED_FROM.get("hub"),
                  ev_field=generator.GENERATED_FROM.get("ev"))
        if not errs:
            break
        if k == 0 and len(attempt_order) == 1:
            trace.log("repair", note="no second extraction run to repair from")
    else:
        return finish("workflow still invalid after the repair pass", 2, "S5", next="L2", validator_errors=errs[:10])
    if errs:
        return finish("workflow invalid", 2, "S5", next="L2", validator_errors=errs[:10])
    tool_nodes = [k for k, n in wf["nodes"].items() if n["node_type"] == "api_request"]
    result.update(nodes=len(wf["nodes"]), node_types=node_counts(wf), tools=[k[2:] for k in tool_nodes],
                  api_mismatch=len(brep["api_mismatch"]), hub_code=generator.GENERATED_FROM.get("hub"))
    trace.log("workflow", nodes=len(wf["nodes"]), node_types=node_counts(wf), tool_nodes=tool_nodes, kb=len(json.dumps(wf)) // 1024)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(rp, open(os.path.join(out_dir, f"{slot}.policy.json"), "w"), indent=1)
    # the raw extraction (before the bridge), so a bridge change can be re-checked without a new model call
    json.dump(pol, open(os.path.join(out_dir, f"{slot}.extracted.json"), "w"), indent=1)
    # 3. save and export
    if time.time() > t0 + budget_s - 30:
        return finish("time guard fired before saving", 2, "GUARD")
    if fb[0]:
        fb[0].cancel()      # before the save: one save per slot, the main candidate
    _save(freya_client, slot, wf, out_dir, trace, result, "main")
    # a generic call through the compiled graph (Fork 3's walker): wiring bugs only; a warning signal, never blocking
    try:
        wk = walk_smoke(rp, wf, openapi)
    except Exception as e:
        wk = {"run": False, "errors": [f"walk_smoke raised {type(e).__name__}: {str(e)[:200]}"]}
    trace.log("graph_walk", **wk)
    result["graph_walk"] = {"run": wk.get("run"), "errors": (wk.get("errors") or [])[:5], "calls": wk.get("calls")}
    if wk.get("errors"):
        trace.log("signal", signal="WALK", level="warning", problems=wk["errors"][:10])
    st_res = run_selftest(rp, openapi)
    trace.log("self_test", **st_res)
    result["self_test"] = {k: st_res.get(k) for k in ("run", "scenarios", "passed", "failed", "note")}
    return finish()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", help="brief files or folders, then the tool API file (openapi.json)")
    ap.add_argument("--slot")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--budget-min", type=float, default=25)
    ap.add_argument("--mock-freya", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "submission"))
    ap.add_argument("--trace-dir", default=os.path.join(ROOT, "traces"))
    ap.add_argument("--no-l3", action="store_true", help="do not start the L3 fallback writer (local tests)")
    ap.add_argument("--no-examiner", action="store_true", help="do not run the independent examiner")
    a = ap.parse_args()
    *briefs, openapi = a.inputs
    if not briefs or not openapi.endswith(".json") or "paths" not in json.load(open(openapi)):
        ap.error("the last argument must be the brief's OpenAPI file (a .json with 'paths')")
    client = None
    if a.mock_freya:
        client = MockFreya()
    elif not a.no_save:
        import freya as client  # noqa: the real client; needs FREYA_API_KEY in the environment
    fallback = None
    if not a.no_l3:
        from builder import fallback_llm
        fallback = lambda b, o, log: fallback_llm.Fallback(b, o, log=log)
    exam = None
    if not a.no_examiner:
        from builder.examiner import examine
        exam = lambda b, o, sink, dl: examine(b, o, sink, dl)
    r = build(briefs, openapi, a.slot, client, a.out_dir, a.trace_dir, a.runs, int(a.budget_min * 60), fallback=fallback,
              examiner=exam)
    print(json.dumps({k: v for k, v in r.items()}, default=str))
    sys.exit(r["exit_code"])


if __name__ == "__main__":
    main()
