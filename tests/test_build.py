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
        # L3 hook (Fork 5's fallback_llm): a fake writer object with start/cancel/wait
        l3_wf = json.load(open(os.path.join(ROOT, "tests", "fallback", "brief-a.l3.workflow.json")))

        class FakeL3:
            made = []

            def __init__(self, briefs, openapi, log, wf=l3_wf, errors=()):
                self.wf, self.errors, self.cancelled, self.started = wf, list(errors), False, False
                FakeL3.made.append(self)

            def start(self):
                self.started = True
                return self

            def cancel(self):
                self.cancelled = True

            def wait(self, timeout):
                return {"workflow": self.wf, "errors": self.errors, "seconds": 1.0}
        fr = MockFreya()
        r9 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "l3", fr, os.path.join(tmp, "sub9"), os.path.join(tmp, "tr"),
                   2, 1500, boom, fallback=FakeL3)
        ev9 = [json.loads(l) for l in open(r9["trace"])]
        sel = [e for e in ev9 if e["event"] == "fallback_selection"]
        check(r9["exit_code"] == 0 and r9.get("fallback_used") == "L3" and r9["main_signal"] == "EXTRACT" and len(fr.saved) == 1, r9)
        check(sel and sel[0]["candidate"] == "llm" and [e["candidate"] for e in ev9 if e["event"] == "save"] == ["llm"], "one save, of the L3 candidate")
        print("ok L3: main path failed (EXTRACT) -> L3 saved once, exit 0, fallback_used=L3")
        fr2 = MockFreya()
        FakeL3.made.clear()
        r10 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "l3main", fr2, os.path.join(tmp, "sub10"), os.path.join(tmp, "tr"),
                    2, 1500, saved_extractor("brief-a"), fallback=FakeL3)
        ev10 = [json.loads(l) for l in open(r10["trace"])]
        check(r10["exit_code"] == 0 and not r10.get("fallback_used") and len(fr2.saved) == 1 and FakeL3.made[0].cancelled, r10)
        check([e["candidate"] for e in ev10 if e["event"] == "save"] == ["main"], "one save, of the main candidate; L3 cancelled first")
        print("ok L3: main path passed -> L3 cancelled, the main workflow saved once")
        fr3 = MockFreya()
        bad = lambda b, o, log: FakeL3(b, o, log, errors=["shape: no greet"])
        r11 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "l3bad", fr3, os.path.join(tmp, "sub11"), os.path.join(tmp, "tr"),
                    2, 1500, boom, fallback=bad)
        check(r11["exit_code"] == 2 and not fr3.saved and r11["signal"] == "EXTRACT", r11)
        print("ok L3: main failed and L3 invalid -> exit 2, nothing saved")
        FakeL3.made.clear()
        r12 = build([os.path.join(clone, "missing.md")], OAS, "l3s1", MockFreya(), os.path.join(tmp, "sub12"), os.path.join(tmp, "tr"),
                    2, 1500, boom, fallback=FakeL3)
        check(r12["exit_code"] == 2 and r12["signal"] == "S1" and not FakeL3.made, "S1 (nothing readable): L3 never starts")
        print("ok L3: nothing readable -> L3 not started")
        # S7 smoke hook (BUILDER_SMOKE=1, a client with api/get_call): pass -> L3 cancelled after the smoke; fail -> L3 replaces
        import builder.smoke as SM

        class SmokeFreya(MockFreya):
            def api(self, *a):
                return {}

            def get_call(self, cid):
                return {}
        real_run, real_sims = SM.run, SM.running_sims
        os.environ["BUILDER_SMOKE"] = "1"
        try:
            SM.running_sims = lambda f: []
            SM.run = lambda *a, **k: {"ok": True, "skipped": False, "signal": None, "reason": ""}
            FakeL3.made.clear()
            fr4 = SmokeFreya()
            r13 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "smoke-ok", fr4, os.path.join(tmp, "s13"), os.path.join(tmp, "tr"),
                        2, 1500, saved_extractor("brief-a"), fallback=FakeL3)
            check(r13["exit_code"] == 0 and len(fr4.saved) == 1 and FakeL3.made[0].cancelled and r13["smoke"][0]["ok"], r13)
            print("ok S7: smoke passed -> one save, L3 cancelled after the smoke")
            SM.run = lambda *a, **k: {"ok": False, "skipped": False, "signal": "S7", "reason": "no reply"}
            fr5 = SmokeFreya()
            r14 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "smoke-bad", fr5, os.path.join(tmp, "s14"), os.path.join(tmp, "tr"),
                        2, 1500, saved_extractor("brief-a"), fallback=FakeL3)
            saves = lambda r: [json.loads(l)["candidate"] for l in open(r["trace"]) if json.loads(l)["event"] == "save"]
            check(r14["exit_code"] == 2 and r14["signal"] == "S7" and r14.get("fallback_used") == "L3" and saves(r14) == ["main", "llm"], r14)
            print("ok S7: main smoke failed -> L3 saved to the slot and smoked; both failed -> exit 2 S7")
            calls = iter([{"ok": False, "skipped": False, "signal": "S7", "reason": "no reply"}, {"ok": True, "skipped": False, "signal": None, "reason": ""}])
            SM.run = lambda *a, **k: next(calls)
            fr6 = SmokeFreya()
            r15 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "smoke-l3", fr6, os.path.join(tmp, "s15"), os.path.join(tmp, "tr"),
                        2, 1500, saved_extractor("brief-a"), fallback=FakeL3)
            check(r15["exit_code"] == 0 and r15.get("fallback_used") == "L3" and r15["main_signal"] == "S7" and saves(r15) == ["main", "llm"], r15)
            print("ok S7: main smoke failed, L3 smoke passed -> exit 0 with fallback_used=L3")
            fr7 = SmokeFreya()
            r16 = build([os.path.join(ROOT, "briefs", "brief-a.md")], OAS, "smoke-nol3", fr7, os.path.join(tmp, "s16"), os.path.join(tmp, "tr"),
                        2, 1500, saved_extractor("brief-a"))
            check(r16["exit_code"] == 0 or r16["signal"] == "S7", r16)
        finally:
            SM.run, SM.running_sims = real_run, real_sims
            os.environ.pop("BUILDER_SMOKE", None)
        print("PASS")
    finally:
        shutil.rmtree(tmp)
