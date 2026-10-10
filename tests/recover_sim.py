"""Read back a simulation whose status poll died (e.g. a 503) without starting a new one: read-only GETs, the same
scoring as tools/run_cases.py, the same --out format. The customer_id comes from the call's variables.
    python3 tests/recover_sim.py <sim_id> <cases.json> <out.json>"""
import hashlib, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
import tests._env  # noqa: F401
import freya
from run_cases import persona_for
from score import http, score_ledger

sim_id, cases_path, out = sys.argv[1:4]
cases = json.load(open(cases_path))
store = json.load(open(os.path.join(ROOT, ".personas.json")))
pid = {}
for c in cases:
    spec = persona_for(c, {"identity": c["identity"]}, None)
    pid[c["id"]] = store[c["id"] + ":" + hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]]
s = freya.api("GET", f"/api/v2/simulations/{sim_id}"); s = s.get("simulation") or s
its = freya.api("GET", f"/api/v2/simulations/{sim_id}/iterations"); its = its.get("iterations") or its.get("items") or its
judge = {r["personaId"]: r for r in freya.get_iteration(sim_id, its[0]["id"])["runs"]}
print("status", s.get("status"))
rows = []
for c in cases:
    j = judge.get(pid[c["id"]], {})
    if not j.get("callId"):
        print("NORUN", c["id"]); continue
    call = freya.get_call(j["callId"])
    cust = None
    for m in call.get("messages") or []:
        vt = (m.get("workflowSnapshot") or {}).get("variableTable") or {}
        if (vt.get("customer_id") or {}).get("value"):
            cust = vt["customer_id"]["value"]; break
    led = http("/v1/practice/ledger/" + cust)
    r = score_ledger(c, led)
    if j.get("outcome") != "pass":
        r["failed"].append("conversation: " + " ".join(str(j.get("reason") or "no verdict").split())[:400])
    r["pass"] = not r["failed"]
    rows.append({"id": c["id"], "level": c["level"], "family": c["family"], "pass": r["pass"], "failed": r["failed"], "call_id": j["callId"],
                 "tools": [x["tool"] for x in led["calls"]], "customer_id": cust})
    print("PASS" if r["pass"] else "FAIL", c["id"], c["family"], "|", " > ".join(x["tool"] for x in led["calls"]))
    for f in r["failed"]:
        print("       -", f[:300])
n = sum(r["pass"] for r in rows)
print(f"{n} / {len(cases)} passed (recovered from simulation {sim_id})")
json.dump({"simulation_id": sim_id, "passed": n, "total": len(cases), "runs": 1, "rows": rows, "all_rows": [rows], "recovered": True}, open(out, "w"), indent=1)
