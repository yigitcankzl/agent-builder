"""python3 tests/l3cmp/summary.py: node count, agent_config vs the base agent, L3 model calls per slot."""
import glob, json, os
D = os.path.dirname(os.path.abspath(__file__))
base = json.load(open(os.path.join(D, "..", "..", "examples", "base-agent.json"))).get("agent_config")
for s in ("l3-raw-4", "l3-raw-5", "l3-brief-a"):
    w = json.load(open(os.path.join(D, "out", f"{s}.l3.workflow.json")))
    ev = [json.loads(l) for t in glob.glob(os.path.join(D, "out", f"{s}-*.jsonl")) for l in open(t)]
    calls = [e for e in ev if "model" in json.dumps(e)[:300] and e.get("event") not in ("reproducibility",)]
    print(s, "nodes", len(w["nodes"]), "agent_config==base", w.get("agent_config") == base,
          json.dumps(w.get("agent_config"))[:160], "events", sorted({e.get("event") for e in ev}))
