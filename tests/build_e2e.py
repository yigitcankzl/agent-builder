"""End-to-end build.py runs with real Claude extraction and Freya mocked, on brief A, A+B and the six Cursor fixtures.

    python3 tests/build_e2e.py [--parallel 4]
Each brief runs the exact CLI (`builder/build.py <briefs...> <openapi> --mock-freya`) as a subprocess and is timed.
"""
import concurrent.futures as cf, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "tests", "fixtures", "briefs")
OAS = os.path.join(ROOT, "tools", "openapi.json")
RUNS = {"brief-a": [os.path.join(ROOT, "briefs", "brief-a.md")],
        "brief-ab": [os.path.join(ROOT, "briefs", "brief-a.md"), os.path.join(ROOT, "briefs", "brief-b.md")],
        **{f"mut-0{i}": [os.path.join(FX, f"mut-0{i}.md")] for i in range(1, 6)},
        "raw-a": [os.path.join(FX, "raw-a")]}
OUT = os.path.join(ROOT, "tests", "e2e")


def run(slot):
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "builder", "build.py"), *RUNS[slot], OAS, "--slot", slot,
                        "--mock-freya", "--out-dir", os.path.join(OUT, "submission"), "--trace-dir", os.path.join(OUT, "traces")],
                       capture_output=True, text=True, timeout=1900)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        res = {"error": (r.stderr or r.stdout)[-600:]}
    res["wall_s"] = round(time.time() - t0, 1)
    res["exit"] = r.returncode
    return slot, res


if __name__ == "__main__":
    par = int(sys.argv[sys.argv.index("--parallel") + 1]) if "--parallel" in sys.argv else 4
    os.makedirs(OUT, exist_ok=True)
    results = {}
    with cf.ThreadPoolExecutor(par) as ex:
        for slot, res in ex.map(run, RUNS):
            results[slot] = res
            print(slot, json.dumps({k: res.get(k) for k in ("exit", "wall_s", "seconds", "fallback_required", "fallback_reason",
                                                            "nodes", "tools", "api_mismatch", "hub_code", "workflow_id", "error")}), flush=True)
    json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)
