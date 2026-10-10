"""build.py tests with Freya mocked and the extractor replaced by saved extractions (no model calls).

    python3 tests/test_build.py
Checks the pipeline wiring, the trace contents and key stripping, the time guard, the extraction-failure fallback and
the repair pass. The real end-to-end runs (with Claude) are in tests/build_e2e.py.
"""
import json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.build import MockFreya, build

OAS = os.path.join(ROOT, "tools", "openapi.json")
V3 = os.path.join(ROOT, "tests", "policy_eval", "v3")
REQUIRED_EVENTS = {"start", "sources", "model_call", "extraction_run", "core_agreement", "rules_extracted", "superseded",
                   "unmapped", "bridge", "validator", "workflow", "save", "self_test", "end"}


def saved_extractor(name):
    runs = iter(("run4", "run5"))

    def ex(briefs, openapi, trace_path, repair, sink, deadline):
        r = next(runs)
        sink.model_call(model="saved-" + r, purpose="extract policy from brief (replayed)", seconds=0.0)
        rep = json.load(open(os.path.join(V3, r, name + ".report.json")))
        return json.load(open(os.path.join(V3, r, name + ".json"))), rep
    return ex


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    try:
        os.environ["FREYA_API_KEY"] = "fak_test_secret_value_123"
        r = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "brief-a", MockFreya(), os.path.join(tmp, "sub"),
                  os.path.join(tmp, "tr"), 2, 1500, saved_extractor("brief-a"))
        check(r["exit_code"] == 0 and not r["fallback_required"], r)
        check(os.path.exists(r["export"]) and json.load(open(r["export"]))["workflow"]["initial_node"] == "greet", "export written")
        ev = [json.loads(l) for l in open(r["trace"])]
        missing = REQUIRED_EVENTS - {e["event"] for e in ev}
        check(not missing, f"trace lacks {missing}")
        txt = open(r["trace"]).read() + open(r["trace"].replace(".jsonl", ".txt")).read()
        check("fak_test_secret_value_123" not in txt, "a key leaked into the trace")
        check(any(e["event"] == "rules_extracted" and e["rules"] for e in ev), "rules with quotes")
        print("ok pipeline + trace + export + key stripping:", r["nodes"], "nodes", r["node_types"])
        # time guard
        r2 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "guard", MockFreya(), os.path.join(tmp, "sub"),
                   os.path.join(tmp, "tr"), 2, 1, saved_extractor("brief-a"))
        check(r2["fallback_required"] and r2["exit_code"] == 2 and "time guard" in r2["fallback_reason"], r2)
        print("ok time guard -> fallback, nothing saved")
        # extraction failure
        def boom(*a):
            raise RuntimeError("claude unavailable")
        r3 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "fail", MockFreya(), os.path.join(tmp, "sub"),
                   os.path.join(tmp, "tr"), 2, 1500, boom)
        check(r3["fallback_required"] and "extraction failed" in r3["fallback_reason"], r3)
        print("ok extraction failure -> fallback")
        # repair pass: first run broken (identity question outside the enum and not blocked is impossible via the
        # bridge, so break the core instead: no closing table), second run good
        import threading, time as _t
        lock, n = threading.Lock(), [0]

        def half(briefs, openapi, tp, rep_, sink, deadline):
            with lock:  # the first submitted run starts first and gets the broken policy
                n[0] += 1
                mine = n[0]
            p = json.load(open(os.path.join(V3, "run4", "brief-a.json")))
            if mine == 1:
                p["identity"]["questions"] = []
            else:
                _t.sleep(0.3)
            return p, json.load(open(os.path.join(V3, "run4", "brief-a.report.json")))
        r4 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "repair", MockFreya(), os.path.join(tmp, "sub"),
                   os.path.join(tmp, "tr"), 2, 1500, half)
        ev4 = [json.loads(l) for l in open(r4["trace"])]
        vals = [e for e in ev4 if e["event"] == "validator"]
        check(r4["exit_code"] == 0 and len(vals) == 2 and not vals[0]["passed"] and vals[1]["passed"], [v["passed"] for v in vals])
        print("ok repair pass: run 1 invalid, run 2 valid and saved")
        # S0: a clean clone without builder/engine/reducer.py -> exit 3 before any model call, nothing saved
        import subprocess
        clone = os.path.join(tmp, "clone")
        shutil.copytree(os.path.join(ROOT, "builder"), os.path.join(clone, "builder"), ignore=shutil.ignore_patterns("__pycache__"))
        os.remove(os.path.join(clone, "builder", "engine", "reducer.py"))
        out = subprocess.run([sys.executable, os.path.join(clone, "builder", "build.py"), os.path.join(ROOT, "briefs", "brief-a.md"),
                              OAS, "--slot", "s0", "--mock-freya", "--out-dir", os.path.join(clone, "sub"), "--trace-dir",
                              os.path.join(clone, "tr")], capture_output=True, text=True, timeout=120)
        res = json.loads(out.stdout.strip().splitlines()[-1])
        ev5 = [json.loads(l) for l in open(res["trace"])]
        check(out.returncode == 3 and res["signal"] == "S0" and not os.path.exists(os.path.join(clone, "sub")), res)
        check(any(e["event"] == "hub_import_failed" for e in ev5) and not any(e["event"] == "model_call" for e in ev5),
              "S0 is traced as hub_import_failed, before any model call")
        print("ok S0: clone without reducer.py -> exit 3, hub_import_failed, nothing saved, no model call")
        # S0 at generate time (the engine imports but hub_source raises) -> exit 3
        import builder.integration as I
        real = I._load
        I._load = lambda m, n: (lambda *a: (_ for _ in ()).throw(ValueError("broken engine"))) if n == "hub_source" else real(m, n)
        try:
            r6 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "s0b", MockFreya(), os.path.join(tmp, "sub6"),
                       os.path.join(tmp, "tr"), 2, 1500, saved_extractor("brief-a"))
        finally:
            I._load = real
        check(r6["exit_code"] == 3 and r6["signal"] == "S0" and "export" not in r6, r6)
        print("ok S0: hub_source raising -> exit 3, nothing saved")
        # S2: identity missing in every run; the targeted re-extraction fails to fill it -> exit 2, next L3
        import builder.build as BB

        def no_identity(briefs, openapi, tp, rep_, sink, deadline):
            p = json.load(open(os.path.join(V3, "run4", "brief-a.json")))
            p.pop("identity", None)
            return p, json.load(open(os.path.join(V3, "run4", "brief-a.report.json")))
        real_rc = BB.reextract_core
        BB.reextract_core = lambda *a, **k: {}
        try:
            r7 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "s2", MockFreya(), os.path.join(tmp, "sub7"),
                       os.path.join(tmp, "tr"), 2, 1500, no_identity)
            ev7 = [json.loads(l) for l in open(r7["trace"])]
            check(r7["exit_code"] == 2 and r7["signal"] == "S2" and r7["next"] == "L3" and "identity" in r7["core_missing"], r7)
            check(any(e["event"] == "core_missing" for e in ev7) and any(e["event"] == "signal" and e["signal"] == "S2" for e in ev7),
                  "S2 in the trace")
            print("ok S2: identity missing in every run, re-extraction empty -> exit 2, signal S2, next L3")
            # the re-extraction fills it -> the build goes on and saves
            full = json.load(open(os.path.join(V3, "run4", "brief-a.json")))
            BB.reextract_core = lambda *a, **k: {"identity": full["identity"]}
            r8 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "s2ok", MockFreya(), os.path.join(tmp, "sub8"),
                       os.path.join(tmp, "tr"), 2, 1500, no_identity)
            check(r8["exit_code"] == 0 and not r8["fallback_required"], r8)
            print("ok S2: re-extraction fills identity -> build continues, exit 0")
        finally:
            BB.reextract_core = real_rc
        print("PASS")
    finally:
        shutil.rmtree(tmp)
