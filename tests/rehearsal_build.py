"""Build Cursor's rehearsal briefs (fixtures-briefs: nightmare-1, raw-2, biz-1) with NO save: the brief files and the
brief's own OAS only (never README, cases or expected files). Outputs in tests/generated/rehearsal/<brief>/.

    python3 tests/rehearsal_build.py [brief ...]
"""
import concurrent.futures as cf, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "tests", "fixtures", "rehearsal")
INPUTS = {"nightmare-1": ["brief.md"], "biz-1": ["brief.md"], "clean-1": ["brief.md"],
          "raw-2": ["email-thread.eml", "meeting-2026-10-01.txt", "slack-export.json", "codes.csv"],
          "raw-1": ["policy-extract.md", "memo-2026-10-08.md", "email-from-dialler-ops.eml", "codes.csv"]}
OUT = os.path.join(ROOT, "tests", "generated", "rehearsal")


def run(name):
    d = os.path.join(FX, name)
    out = os.path.join(OUT, name)
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "builder", "build.py"), *[os.path.join(d, f) for f in INPUTS[name]],
                        os.path.join(d, "openapi.json"), "--slot", name, "--no-save", "--no-l3", "--out-dir", out,
                        "--trace-dir", os.path.join(out, "traces")], capture_output=True, text=True, timeout=1900)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        res = {"error": (r.stderr or r.stdout)[-800:]}
    res.update(wall_s=round(time.time() - t0, 1), exit=r.returncode)
    return name, res


if __name__ == "__main__":
    names = sys.argv[1:] or ["nightmare-1", "raw-2", "biz-1", "clean-1", "raw-1"]
    with cf.ThreadPoolExecutor(len(names)) as ex:
        for name, res in ex.map(run, names):
            print(name, json.dumps({k: res.get(k) for k in ("exit", "wall_s", "signal", "fallback_reason", "api_mismatch", "self_test",
                                                             "examiner", "graph_walk", "degraded", "error")}, default=str)[:900], flush=True)
