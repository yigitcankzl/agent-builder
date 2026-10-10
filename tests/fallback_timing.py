"""Failure injection + wall time of the build with the L3 fallback hook (the same flow as the proposed build.py main()):
L3 thread at t0, build() capped at fallback_llm.MAIN_CAP_S, rescue() on exit 2. Local only: MockFreya, no Freya call.

    python3 tests/fallback_timing.py [inject ...] [--brief briefs/brief-a.md] [--openapi tools/openapi.json] [--out f.json]
    injections: none stub_hub extract_fail slow_claude core_missing validator_core binding_core
"""
import argparse, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import build as B, fallback_llm as L, oas_bindings

ALL = ["none", "stub_hub", "extract_fail", "slow_claude", "core_missing", "validator_core", "binding_core"]


def inject(name):
    """Patch one failure into the main path. Returns an undo function and the extractor to pass to build()."""
    saved = {"load": B._load, "validate": B.validate, "reextract_core": B.reextract_core, "tool_results": oas_bindings.tool_results}
    extractor = B.extract
    if name == "stub_hub":                               # S0: reducer / event field cannot be imported
        B._load = lambda mod, attr: None
    elif name == "extract_fail":                         # EXTRACT at once (e.g. claude CLI missing)
        def extractor(*a, **k): raise RuntimeError("injected: claude -p failed")
    elif name == "slow_claude":                          # EXTRACT at the main deadline: the model hangs
        def extractor(briefs, openapi, tp, repair, sink, deadline):
            time.sleep(max(0, deadline - time.time())); raise TimeoutError("injected: claude -p hung until the deadline")
    elif name == "core_missing":                         # S2: identity section missing in every run, re-extraction finds nothing
        def extractor(*a, **k):
            p, rep = B.extract(*a, **k); p.pop("identity", None); return p, rep
        B.reextract_core = lambda *a, **k: {}
    elif name == "validator_core":                       # S5 on a core rule
        B.validate = lambda *a, **k: ["2: identity gate: get_account is reachable before verify_identity (injected)"]
    elif name == "binding_core":                         # a core response fact unbound -> validator check 13 -> S5
        def tr(oas_path, policy):
            t, missing = saved["tool_results"](oas_path, policy)
            acc = t.get("get_account") or {}
            acc.pop(next(iter(acc), None), None)
            return t, missing
        oas_bindings.tool_results = tr

    def undo():
        B._load, B.validate, B.reextract_core, oas_bindings.tool_results = saved["load"], saved["validate"], saved["reextract_core"], saved["tool_results"]
    return undo, extractor


def run(name, brief, openapi, budget_s=25 * 60):
    undo, extractor = inject(name)
    out = os.path.join(ROOT, "tests", "fallback", "runs", name)
    try:
        t0 = time.time()
        fb = L.Fallback([brief], openapi).start()
        r = B.build([brief], openapi, None, B.MockFreya(), out, out, 2, min(budget_s, L.MAIN_CAP_S), extractor)
        main_s = time.time() - t0
        r = L.rescue(r, fb, B.MockFreya(), r["slot"], out, t_end=t0 + budget_s)
        total = time.time() - t0
    finally:
        undo()
    return {"inject": name, "signal": r.get("signal"), "exit": r["exit_code"], "candidate": r.get("candidate", "main" if r["exit_code"] == 0 else None),
            "main_s": round(main_s), "l3_s": fb.result.get("seconds"), "l3_errors": (fb.result.get("errors") or [])[:3],
            "total_s": round(total), "total_min": round(total / 60, 1), "trace": r.get("trace")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inject", nargs="*", default=ALL)
    ap.add_argument("--brief", default=os.path.join(ROOT, "briefs", "brief-a.md"))
    ap.add_argument("--openapi", default=os.path.join(ROOT, "tools", "openapi.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "tests", "fallback", "timing.json"))
    a = ap.parse_args()
    rows = json.load(open(a.out)) if os.path.exists(a.out) else []
    for name in a.inject:
        row = run(name, a.brief, a.openapi)
        print(json.dumps(row), flush=True)
        rows = [x for x in rows if x["inject"] != name] + [row]
        json.dump(rows, open(a.out, "w"), indent=1)
    print("\n| inject | signal | exit | candidate | main s | L3 s | total min |\n|---|---|---|---|---|---|---|")
    for x in rows:
        print(f"| {x['inject']} | {x['signal'] or '-'} | {x['exit']} | {x['candidate']} | {x['main_s']} | {x['l3_s']} | {x['total_min']} |")
