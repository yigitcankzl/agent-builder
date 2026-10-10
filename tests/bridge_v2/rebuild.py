"""Rebuild with real extraction (Freya mocked): A, A+B, ins-clean, raw-b, mut-03 through builder/build.py, in parallel.

    python3 tests/bridge_v2/rebuild.py [out_dir]
Writes <out_dir>/submission/<slot>.policy.json (the bridged policy) and .workflow.json, and <out_dir>/results.json.
"""
import concurrent.futures as cf, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
G = os.path.join(ROOT, "tests", "fixtures", "general")
OAS = os.path.join(ROOT, "tools", "openapi.json")
RUNS = {"brief-a": ([os.path.join(ROOT, "briefs", "brief-a.md")], OAS),
        "brief-ab": ([os.path.join(ROOT, "briefs", "brief-a.md"), os.path.join(ROOT, "briefs", "brief-b.md")], OAS),
        "ins-clean": ([os.path.join(G, "ins-clean", "brief.md")], os.path.join(G, "ins-clean", "openapi.json")),
        "raw-b": ([os.path.join(G, "raw-b", f) for f in ("email-from-dialler-ops.eml", "policy-extract.md", "memo-2026-10-08.md", "codes.csv")], OAS),
        "mut-03": ([os.path.join(ROOT, "tests", "fixtures", "briefs", "mut-03.md")], OAS)}
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "e2e8")


def run(slot):
    briefs, oas = RUNS[slot]
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "builder", "build.py"), *briefs, oas, "--slot", slot, "--mock-freya",
                        "--out-dir", os.path.join(OUT, "submission"), "--trace-dir", os.path.join(OUT, "traces")],
                       capture_output=True, text=True, timeout=1900)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        res = {"error": (r.stderr or r.stdout)[-600:]}
    res.update(wall_s=round(time.time() - t0, 1), exit=r.returncode)
    return slot, res


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    results = {}
    with cf.ThreadPoolExecutor(len(RUNS)) as ex:
        for slot, res in ex.map(run, RUNS):
            results[slot] = res
            print(slot, json.dumps({k: res.get(k) for k in ("exit", "wall_s", "fallback_required", "fallback_reason", "api_mismatch",
                                                            "self_test", "error")}), flush=True)
    json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)
