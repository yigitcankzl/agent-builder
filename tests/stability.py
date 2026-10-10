"""Rebuild with build.py (Claude extraction, Freya mocked) and compare the reducer-facing policy across runs:
pre-verification queues, the opening-situation checklist / who rules, fixed sentence keys, slots, tool_args,
validator and self-test.   python3 tests/stability.py [--parallel 4]
Copies the last run's bridged policies to tests/generated/<slot>.reducer_policy.json."""
import concurrent.futures as cf, json, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.policy_bridge import FIXED_SENTENCES

G = "tests/fixtures/general"
F = "tests/fixtures/briefs"
SPEC = {"brief-a": (["briefs/brief-a.md"], "tools/openapi.json", 2),
        "brief-ab": (["briefs/brief-a.md", "briefs/brief-b.md"], "tools/openapi.json", 1),
        "raw-a": ([f"{F}/raw-a"], "tools/openapi.json", 2),
        "raw-b": ([f"{G}/raw-b/{x}" for x in ("email-from-dialler-ops.eml", "policy-extract.md", "memo-2026-10-08.md", "codes.csv")], "tools/openapi.json", 2),
        "ins-clean": ([f"{G}/ins-clean/brief.md"], f"{G}/ins-clean/openapi.json", 1)}
OUT = os.path.join(ROOT, "tests", "e2e5")


def run(job):
    slot, i = job
    briefs, oas, _ = SPEC[slot]
    d = os.path.join(OUT, f"run{i}")
    r = subprocess.run([sys.executable, "builder/build.py", *briefs, oas, "--slot", slot, "--mock-freya",
                        "--out-dir", os.path.join(d, "submission"), "--trace-dir", os.path.join(d, "traces")],
                       cwd=ROOT, capture_output=True, text=True, timeout=1900)
    res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": r.stderr[-400:]}
    path = os.path.join(d, "submission", slot + ".policy.json")
    p = json.load(open(path)) if os.path.exists(path) else {}
    s = p.get("sentences") or {}
    view = {"exit": res.get("exit_code"), "s": res.get("seconds"), "self_test": (res.get("self_test") or {}).get("passed"),
            "of": (res.get("self_test") or {}).get("scenarios"), "pre_queues": (p.get("transfer") or {}).get("pre_verification_queues"),
            "queue_keys": sorted(((p.get("transfer") or {}).get("queue_map") or {}).keys()),
            "who_checklist": p.get("who_checklist"),
            "who": sorted({(w.get("who"), w.get("party"), w.get("effect_kind") or "") for w in p.get("who_rules") or []}),
            "keys_filled": sorted(k for k in FIXED_SENTENCES if (s.get(k) or {}).get("text")),
            "slots": sorted(k for k, v in ((p.get("closing") or {}).get("slots") or {}).items() if v),
            "tool_args_cp": ((p.get("tool_args") or {}).get("create_promise"))}
    return slot, i, view, path


if __name__ == "__main__":
    par = int(sys.argv[sys.argv.index("--parallel") + 1]) if "--parallel" in sys.argv else 4
    jobs = [(slot, i) for slot, (_, _, n) in SPEC.items() for i in range(1, n + 1)]
    res = {}
    with cf.ThreadPoolExecutor(par) as ex:
        for slot, i, view, path in ex.map(run, jobs):
            res.setdefault(slot, []).append(view)
            print(slot, i, json.dumps(view, default=str), flush=True)
            if os.path.exists(path):
                shutil.copy(path, os.path.join(ROOT, "tests", "generated", slot + ".reducer_policy.json"))
    print()
    for slot, views in res.items():
        if len(views) > 1:
            same = {k: all(v[k] == views[0][k] for v in views) for k in ("pre_queues", "queue_keys", "who_checklist", "who", "keys_filled", "slots")}
            print(slot, "stable:", same)
