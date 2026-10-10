"""Failure injection + wall time of the INTEGRATION build with the L3 hook: build(fallback=factory) exactly as build.py
main() calls it. Local only: MockFreya, no Freya call. Each injection is a monkeypatch of one main-path step.

    python3 tests/fallback_timing.py [inject ...] [--brief briefs/brief-a.md] [--openapi tools/openapi.json] [--budget-min 25]
    injections: none stub_hub extract_fail slow_claude core_missing validator_core binding_core guard
"""
import argparse, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import build as B, fallback_llm as L, oas_bindings

ALL = ["none", "stub_hub", "extract_fail", "slow_claude", "core_missing", "validator_core", "binding_core", "guard"]
CACHED = os.path.join(ROOT, "tests", "fallback", "runs", "none", "brief-a.extracted.json")   # a real run-1 policy of brief A
REP = {"seconds": 0, "quotes_rejected": 0, "quotes_repaired": 0, "quotes_unverified": 0, "errors": [], "oas_warnings": [], "core_missing": []}


def inject(name, t_end):
    """Patch one failure into the main path. Returns an undo function and the extractor to pass to build()."""
    saved = {"load": B._load, "validate": B.validate, "reextract_core": B.reextract_core, "tool_results": oas_bindings.tool_results}
    extractor = B.extract
    if name == "stub_hub":                               # S0: reducer / event field cannot be imported
        B._load = lambda mod, attr: None
    elif name == "extract_fail":                         # EXTRACT at once (e.g. the claude CLI fails)
        def extractor(*a, **k): raise RuntimeError("injected: claude -p failed")
    elif name == "slow_claude":                          # EXTRACT at the main deadline: the model hangs
        def extractor(briefs, openapi, tp, repair, sink, deadline):
            time.sleep(max(0, deadline - time.time())); raise TimeoutError("injected: claude -p hung until the deadline")
    elif name == "guard":                                # extraction returns a real policy only 29 s before the budget ends
        def extractor(*a, **k):
            time.sleep(max(0, t_end - 29 - time.time())); return json.load(open(CACHED)), dict(REP)
    elif name == "core_missing":                         # S2: identity missing in every run, the re-extraction finds nothing
        def extractor(*a, **k):
            p, rep = B.extract(*a, **k); p.pop("identity", None); return p, rep
        B.reextract_core = lambda *a, **k: {}
    elif name == "validator_core":                       # S5 on a core rule
        B.validate = lambda *a, **k: ["2: identity gate: get_account is reachable before verify_identity (injected)"]
    elif name == "binding_core":                         # a core response fact of get_account unbound -> validator check 13 -> S5
        def tr(oas_path, policy):
            t, missing = saved["tool_results"](oas_path, policy)
            acc = t.get("get_account") or {}
            acc.pop(next(iter(acc), None), None)
            return t, missing
        oas_bindings.tool_results = tr

    def undo():
        B._load, B.validate, B.reextract_core, oas_bindings.tool_results = saved["load"], saved["validate"], saved["reextract_core"], saved["tool_results"]
    return undo, extractor


def run(name, brief, openapi, budget_s):
    out = os.path.join(ROOT, "tests", "fallback", "runs", name)
    t0 = time.time()
    undo, extractor = inject(name, t0 + budget_s)
    try:
        r = B.build([brief], openapi, None, B.MockFreya(), out, out, 2, budget_s, extractor,
                    fallback=lambda b, o, log: L.Fallback(b, o, log=log))
    finally:
        undo()
    total = time.time() - t0
    ev = [json.loads(x) for x in open(r["trace"])]
    sel = next((e for e in ev if e["event"] == "fallback_selection"), {})
    sig = next((e for e in ev if e["event"] == "signal" and e.get("signal") != "S1"), {})
    l3 = [e for e in ev if e["event"] == "model_call" and str(e.get("purpose", "")).startswith("L3")]
    save = next((e for e in ev if e["event"] == "save"), {})
    return {"inject": name, "budget_min": budget_s / 60, "signal": r.get("main_signal") or sig.get("signal"), "exit": r["exit_code"],
            "candidate": sel.get("candidate"), "saved": save.get("candidate"), "l3_s": sel.get("l3_seconds"),
            "l3_calls": [(e.get("purpose"), e.get("seconds")) for e in l3], "l3_errors": sel.get("l3_errors"),
            "total_s": round(total), "total_min": round(total / 60, 1), "trace": os.path.relpath(r["trace"], ROOT)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("inject", nargs="*", default=ALL)
    ap.add_argument("--brief", default=os.path.join(ROOT, "briefs", "brief-a.md"))
    ap.add_argument("--openapi", default=os.path.join(ROOT, "tools", "openapi.json"))
    ap.add_argument("--budget-min", type=float, default=25)
    ap.add_argument("--out", default=os.path.join(ROOT, "tests", "fallback", "timing.json"))
    a = ap.parse_args()
    rows = json.load(open(a.out)) if os.path.exists(a.out) else []
    for name in a.inject:
        row = run(name, a.brief, a.openapi, int(a.budget_min * 60))
        print(json.dumps(row), flush=True)
        rows = [x for x in rows if (x["inject"], x.get("budget_min")) != (name, row["budget_min"])] + [row]
        json.dump(rows, open(a.out, "w"), indent=1)
    print("\n| inject | budget min | signal | exit | selected | saved | L3 s | total min |\n|---|---|---|---|---|---|---|---|")
    for x in rows:
        print(f"| {x['inject']} | {x.get('budget_min')} | {x['signal'] or '-'} | {x['exit']} | {x['candidate'] or '-'} | {x['saved'] or '-'} | {x['l3_s']} | {x['total_min']} |")
