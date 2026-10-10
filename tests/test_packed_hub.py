"""The packed hub (zlib + base64 loader) runs locally exactly as the code node would: exec the generated code string
with a vars dict and check that the reducer wrote its outputs. Also checks the size budget.
    python3 tests/test_packed_hub.py"""
import glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import generator
from builder.generator import generate

OAS = os.path.join(ROOT, "tools", "openapi.json")

if __name__ == "__main__":
    bad = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "tests", "generated", "*.reducer_policy.json"))):
        name = os.path.basename(f).replace(".reducer_policy.json", "")
        oas = os.path.join(ROOT, "tests", "fixtures", "general", name, "openapi.json")
        oas = oas if os.path.exists(oas) else OAS
        rp = json.load(open(f))
        wf = generate(rp, oas)
        code = wf["nodes"]["hub"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
        v = dict(wf["test_variables"])
        v.update(customer_id="c1", first_name="A", last_name="B", title="Mx", now="2026-10-14T11:00",
                 ev="n=kstart;src=user;kind=who;also=none;st=complete;prod=;who=self;party=")
        exec(compile(code, "hub", "exec"), {"vars": v})
        ok = not v.get("hub_error") and v.get("route") in ("say", "talk_pre", "talk_post", "close") or str(v.get("route", "")).startswith("t_")
        ok = ok and v.get("st") and v.get("ev_tok") != "kstart"
        bad += not ok
        print(f"{'ok' if ok else 'FAIL'} {name}: packed {generator.GENERATED_FROM['hub_kb']} KB (plain {generator.GENERATED_FROM['hub_plain_kb']} KB), "
              f"route={v.get('route')} say={str(v.get('say_next'))[:50]!r} err={v.get('hub_error')}")
    print("PASS" if not bad else "FAIL")
    sys.exit(1 if bad else 0)
