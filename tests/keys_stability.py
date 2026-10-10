"""Build A and A+B twice each (Claude extraction, Freya mocked) and compare the bridge's reducer-facing keys across runs:
the fixed sentence keys (and whether each is filled), the who_rules vocabulary, and the self-test.
    python3 tests/keys_stability.py"""
import concurrent.futures as cf, json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.policy_bridge import FIXED_SENTENCES

OUT = os.path.join(ROOT, "tests", "e2e4")
JOBS = [(slot, i, briefs) for slot, briefs in (("brief-a", ["briefs/brief-a.md"]), ("brief-ab", ["briefs/brief-a.md", "briefs/brief-b.md"])) for i in (1, 2)]


def run(job):
    slot, i, briefs = job
    d = os.path.join(OUT, f"run{i}")
    r = subprocess.run([sys.executable, "builder/build.py", *briefs, "tools/openapi.json", "--slot", slot, "--mock-freya",
                        "--out-dir", os.path.join(d, "submission"), "--trace-dir", os.path.join(d, "traces")],
                       cwd=ROOT, capture_output=True, text=True, timeout=1900)
    res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": r.stderr[-500:]}
    return slot, i, res, os.path.join(d, "submission", slot + ".policy.json")


if __name__ == "__main__":
    out = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for slot, i, res, path in ex.map(run, JOBS):
            p = json.load(open(path)) if os.path.exists(path) else {}
            s = p.get("sentences") or {}
            out[(slot, i)] = {"keys": {k: bool((s.get(k) or {}).get("text")) for k in FIXED_SENTENCES},
                              "who": sorted({(w.get("who"), w.get("party"), w.get("effect_kind")) for w in p.get("who_rules") or []}, key=str),
                              "self_test": res.get("self_test"), "seconds": res.get("seconds"), "exit": res.get("exit_code")}
            print(slot, i, json.dumps(out[(slot, i)], default=str)[:600], flush=True)
    for slot in ("brief-a", "brief-ab"):
        a, b = out[(slot, 1)], out[(slot, 2)]
        print(f"{slot}: key set identical {set(a['keys']) == set(b['keys']) == set(FIXED_SENTENCES)}, "
              f"filled identical {a['keys'] == b['keys']}, who identical {a['who'] == b['who']}")
