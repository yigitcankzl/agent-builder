"""Generalisation fixtures (Cursor, fixtures-briefs 287034c): build ins-clean (its OWN openapi.json) and raw-b (kit
OAS) with build.py (Freya mocked), then diff the bridged policy against <fixture>.expected.json.

    python3 tests/eval_general.py            # build both (parallel), then diff
    python3 tests/eval_general.py --reuse    # diff the saved policies only
Outputs the bridged reducer policies at tests/generated/<fixture>.reducer_policy.json for Fork 3.
"""
import concurrent.futures as cf, glob, json, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.eval_policy import diff, expected_view, norm_text, ours_view

G = os.path.join(ROOT, "tests", "fixtures", "general")
OUT = os.path.join(ROOT, "tests", "e2e3")
RUNS = {"ins-clean": ([os.path.join(G, "ins-clean", "brief.md")], os.path.join(G, "ins-clean", "openapi.json"),
                      os.path.join(G, "ins-clean", "brief.expected.json")),
        "raw-b": ([os.path.join(G, "raw-b", f) for f in ("email-from-dialler-ops.eml", "policy-extract.md", "memo-2026-10-08.md", "codes.csv")],
                  os.path.join(ROOT, "tools", "openapi.json"), os.path.join(G, "raw-b", "raw-b.expected.json"))}


def build(slot):
    briefs, oas, _ = RUNS[slot]
    r = subprocess.run([sys.executable, os.path.join(ROOT, "builder", "build.py"), *briefs, oas, "--slot", slot, "--mock-freya",
                        "--out-dir", os.path.join(OUT, "submission"), "--trace-dir", os.path.join(OUT, "traces")],
                       capture_output=True, text=True, timeout=1900)
    try:
        return slot, json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return slot, {"error": (r.stderr or r.stdout)[-800:]}


def plan_expected(e):
    out = {}
    for band, steps in ((e.get("attempts_plan") or {}).get("value") or {}).items():
        row = []
        for s in steps:
            amt = "floor_if_too_much_else_full" if s.get("amount_rule") == "full" and s.get("if_full_already_too_much") == "floor" else s.get("amount_rule")
            row.append((s.get("date_rule"), amt))
        out[band] = row
    return out


def plan_ours(p):
    return {b: [(s.get("date_rule"), s.get("amount_rule")) for s in st] for b, st in ((p.get("attempts") or {}).get("plan") or {}).items()}


def latest_trace(slot):
    fs = sorted(glob.glob(os.path.join(OUT, "traces", slot + "-*.jsonl")))
    return [json.loads(l) for l in open(fs[-1])] if fs else []


if __name__ == "__main__":
    if "--reuse" not in sys.argv:
        with cf.ThreadPoolExecutor(2) as ex:
            for slot, res in ex.map(build, RUNS):
                print(slot, json.dumps({k: res.get(k) for k in ("exit_code", "seconds", "fallback_required", "fallback_reason", "nodes",
                                                                "api_mismatch", "self_test", "error")})[:700], flush=True)
    for slot, (_, oas, exp_path) in RUNS.items():
        pol_path = os.path.join(OUT, "submission", slot + ".policy.json")
        if not os.path.exists(pol_path):
            print(f"\n== {slot}: no policy (build failed)")
            continue
        p, e = json.load(open(pol_path)), json.load(open(exp_path))
        shutil.copy(pol_path, os.path.join(ROOT, "tests", "generated", slot + ".reducer_policy.json"))
        d, notes = diff(ours_view(p), expected_view(e))
        n = len(expected_view(e))
        print(f"\n== {slot}: core fields exact {n - len(d)}/{n}")
        for k, v in d.items():
            print(f"   DIFF {k}: {json.dumps(v)[:400]}")
        for x in notes:
            print("   note:", x)
        pe, po = plan_expected(e), plan_ours(p)
        print("   attempts plan:", "MATCH" if pe == po else f"DIFF ours {po} expected {pe}")
        if "notes_enabled" in e:
            ne = e["notes_enabled"]["value"]
            print("   notes enabled:", "MATCH" if bool((p.get("writes") or {}).get("notes", {}).get("enabled")) == ne else f"DIFF expected {ne}")
        if "tool_args" in e:
            from builder.generator import arg_map, oas_tools
            t = oas_tools(oas)
            amap, unm, _ = arg_map("create_promise", t["create_promise"])
            print("   create_promise args bound:", amap, "unmapped required:", unm)
        if "superseded_rules" in e:
            exp = e["superseded_rules"]["value"]
            for x in exp:
                nv = x["new_value"]
                hit = any((sorted(s.get("new_value")) == sorted(nv)) if isinstance(nv, list) and isinstance(s.get("new_value"), list)
                          else norm_text(s.get("new_value")) == norm_text(nv) for s in p.get("superseded") or [])
                print(f"   supersession {x['rule']}: {'detected' if hit else 'NOT DETECTED'}")
        if "aliases" in e:
            ours = {(a.get("brief_value"), a.get("api_value")) for a in p.get("aliases") or []}
            for a in e["aliases"]["value"]:
                print(f"   alias {a['surface_form']} -> {a['api_value']}: {'recorded' if (a['surface_form'], a['api_value']) in ours else 'NOT recorded'}")
        tr = latest_trace(slot)
        g = lambda name: [x for x in tr if x["event"] == name]
        if g("bridge"):
            print("   api_mismatch:", [(m["field"], m["value"], m["action"]) for m in g("bridge")[-1].get("api_mismatch") or []])
        if g("validator"):
            print("   validator:", [(v["passed"], v["errors"][:3]) for v in g("validator")])
        if g("self_test"):
            s = g("self_test")[-1]
            print("   self-test:", s.get("passed"), "/", s.get("scenarios"), json.dumps(s.get("failures") or {})[:500])
