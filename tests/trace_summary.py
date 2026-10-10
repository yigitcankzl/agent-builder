"""One line per build trace: core agreement, model calls, unmapped stable/dropped, validator, key check.
    python3 tests/trace_summary.py tests/e2e/traces"""
import glob, json, os, re, sys

d = sys.argv[1] if len(sys.argv) > 1 else "traces"
for f in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
    ev = [json.loads(l) for l in open(f)]
    g = lambda n: [e for e in ev if e["event"] == n]
    ca, un, mc = g("core_agreement"), g("unmapped"), g("model_call")
    raw = open(f).read() + open(f.replace(".jsonl", ".txt")).read()
    print(os.path.basename(f)[:20], "agree", ca[0]["agree"] if ca else None, "| model calls", len(mc),
          [m.get("seconds") for m in mc], "| unmapped stable", len(un[0]["stable"]) if un else None,
          "dropped", len(un[0]["dropped_unstable"]) if un else None, "| validator", [v["passed"] for v in g("validator")],
          "| key-shaped strings", len(re.findall(r"fak_[A-Za-z0-9]{8,}", raw)))
