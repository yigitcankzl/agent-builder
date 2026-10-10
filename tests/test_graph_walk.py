"""The compiled workflow walked like the engine (builder/graph_walk.py) on the kit sequences, plus failure injection.
Workflows: read-only copies of integration's tests/e2e-int/submission in tests/generated/walk (WALK_DIR overrides).

    python3 tests/test_graph_walk.py [PUB-01 ...]
Per case: graph errors (unresolved placeholders, OAS-invalid bodies, deadlocks, code errors, no close_call, a turn
without speech), then the hub's decisions compared one to one with the sequence's expected actions.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.graph_walk import walk, hub_actions

WD = os.path.join(ROOT, os.environ.get("WALK_DIR", "tests/generated/walk"))
OAS = json.load(open(os.path.join(ROOT, "tests/generated/walk/openapi.json")))
FIX = json.load(open(os.path.join(ROOT, "tests/fixtures/reducer/public_sequences.json")))
WF = {"A": "brief-a.workflow.json", "A+B": "brief-ab.workflow.json"}
CASES = ["PUB-01", "PUB-02", "PUB-05", "PUB-06", "PUB-10", "PUB-11"]


def bank_for(case, fail=None):
    """Answers in the order the sequence's tool steps give; close_call is always ok. fail = {tool: n}: the first n
    calls of that tool answer 500 before the scripted answers."""
    q = dict()
    for s in case["steps"]:
        if s["source"] == "tool":
            te = s["tool_event"]
            q.setdefault(te["node"][2:], []).append((te.get("status_code") or 200, te.get("data") or dict()))
    for tool, k in (fail or dict()).items():
        q[tool] = [(500, dict(error="injected"))] * k + [x for x in q.get(tool, []) if x[0] < 400]

    def bank(tool, body):
        if tool == "close_call":
            return 200, dict(ok=True)
        lst = q.get(tool) or []
        if not lst:
            return 200, dict(ok=True)
        sc, data = lst.pop(0)
        return sc, dict(data, ok=True) if sc < 400 and isinstance(data, dict) and "ok" not in data else data
    return bank


def compare(exp, got):
    probs = []
    for i, e in enumerate(exp):
        if i >= len(got):
            probs.append("missing action %d: %s" % (i + 1, json.dumps(e)[:120]))
            continue
        g = got[i]
        if g["type"] != e["type"]:
            probs.append("action %d: %s != %s (%s)" % (i + 1, g["type"], e["type"], json.dumps(g)[:140]))
            continue
        if e["type"] == "say_exact":
            if e.get("text") is not None and g["text"] != e["text"]:
                probs.append("action %d text %r != %r" % (i + 1, g["text"], e["text"]))
            for c in e.get("contains", []):
                if c not in (g["text"] or ""):
                    probs.append("action %d: missing %r in %r" % (i + 1, c, g["text"]))
            for c in e.get("must_not_contain", []):
                if c in (g["text"] or ""):
                    probs.append("action %d: forbidden %r in %r" % (i + 1, c, g["text"]))
        elif e["type"] == "call_tool":
            if g["tool"] != e["tool"]:
                probs.append("action %d tool %s != %s" % (i + 1, g["tool"], e["tool"]))
            else:
                ea = dict((k, round(v, 2) if isinstance(v, float) else v) for k, v in e["args"].items())
                ga = dict((k, round(v, 2) if isinstance(v, float) else v) for k, v in (g["args"] or dict()).items())
                if ea != ga:
                    probs.append("action %d args %s != %s" % (i + 1, ga, ea))
        elif e["type"] == "close":
            if (g["outcome"], g["reason"]) != (e["outcome"], e.get("reason")):
                probs.append("action %d close %s/%s != %s/%s" % (i + 1, g["outcome"], g["reason"], e["outcome"], e.get("reason")))
    if len(got) > len(exp):
        probs.append("extra actions: %s" % json.dumps(got[len(exp):])[:200])
    return probs


def run(case, fail=None, expect=None):
    wf = json.load(open(os.path.join(WD, WF[case["policy"]])))
    evs = [s["event"] for s in case["steps"] if s["source"] == "user"]
    rep = walk(wf, OAS, dict(case["call_variables"]), evs, bank_for(case, fail))
    got = hub_actions(rep)
    probs = list(rep["errors"])
    if expect is None:
        probs += compare([s["action"] for s in case["steps"]], got)
    else:
        probs += expect(rep, got)
    if not rep["ended"]:
        probs.append("the call did not reach an end_call node")
    return rep, probs


def fail_once(rep, got):
    """PUB-01 with create_promise failing once: retry, one promise, recorded only after the success."""
    cp = [c for c in rep["calls"] if c["tool"] == "create_promise"]
    closes = [a for a in got if a["type"] == "close"]
    out = []
    if [c["status_code"] for c in cp] != [500, 200]:
        out.append("create_promise calls %s, expected a retry after one 500" % [c["status_code"] for c in cp])
    if not closes or closes[-1]["outcome"] != "promise":
        out.append("close %s, expected promise" % closes[-1:])
    said = [t for _, t in rep["speech"]]
    first_ok = next((i for i, (n, t) in enumerate(rep["speech"]) if "recorded" in t and "call is recorded" not in t), None)
    if first_ok is None:
        out.append("'recorded' never said after the success")
    return out


def fail_twice(rep, got):
    """PUB-01 with create_promise failing twice: no third call, close on the write-failed slot, never 'recorded'."""
    cp = [c for c in rep["calls"] if c["tool"] == "create_promise"]
    closes = [a for a in got if a["type"] == "close"]
    out = []
    if [c["status_code"] for c in cp] != [500, 500]:
        out.append("create_promise calls %s, expected two 500s and no third" % [c["status_code"] for c in cp])
    if not closes or (closes[-1]["outcome"], closes[-1]["reason"]) != ("no_promise", "service_error"):
        out.append("close %s, expected no_promise/service_error" % closes[-1:])
    if any("recorded" in t and "call is recorded" not in t for _, t in rep["speech"]):
        out.append("'recorded' said without a success")
    body = [c for c in rep["calls"] if c["tool"] == "close_call"]
    if not body or body[0]["body"].get("outcome") != "no_promise":
        out.append("close_call body %s" % (body[:1],))
    return out


def close_retry_cases():
    """The end of the call with a close_call the bank rejects, on a freshly generated workflow (the generator's
    close-retry edges): accepted -> end; rejected once -> one retry with an allowed reason and no second farewell;
    rejected twice -> end, no loop; HTTP 500 once -> one retry; a stale close_ok never triggers a retry."""
    from builder.generator import generate
    oas_path = os.path.join(ROOT, "tests/generated/walk/openapi.json")
    out = []
    for cid in ("PUB-05", "PUB-01"):
        c = dict((x["id"], x) for x in FIX["cases"])[cid]
        rp = json.load(open(os.path.join(ROOT, "tests/e2e-hon/submission", ("brief-a" if c["policy"] == "A" else "brief-ab") + ".policy.json")))
        wf = generate(rp, oas_path)
        evs = [s["event"] for s in c["steps"] if s["source"] == "user"]
        allowed = ["refused", "dispute", "service_error"]      # a mock never rejects a reason it lists
        for name, plan, cv in (("accepted", [(200, dict(ok=True))], {}),
                               ("rejected once", [(200, dict(ok=False, error="this outcome needs one of these reasons: " + ", ".join(allowed)))], {}),
                               ("rejected twice", [(200, dict(ok=False, error="rejected"))] * 2, {}),
                               ("HTTP 500 once", [(500, dict(error="injected"))], {}),
                               ("stale close_ok=false", [(200, dict(ok=True))], dict(close_ok="false"))):
            q = list(plan)
            base = bank_for(c)

            def bank(tool, body, q=q, base=base):
                if tool == "close_call" and q:
                    return q.pop(0)
                return base(tool, body)
            rep = walk(wf, OAS, dict(c["call_variables"], **cv), evs, bank)
            probs = list(rep["errors"])
            graph = [x for x in rep["calls"] if x["tool"] == "close_call" and x["node"] == "t_close_call"]
            want = {"accepted": 1, "rejected once": 2, "rejected twice": 2, "HTTP 500 once": 2, "stale close_ok=false": 1}[name]
            if len(graph) != want:
                probs.append("graph close_call sent %d times, expected %d" % (len(graph), want))
            if not rep["ended"]:
                probs.append("the call did not reach end")
            if rep["entered"].count("close_say") != 1:
                probs.append("close_say (the farewell) entered %d times" % rep["entered"].count("close_say"))
            if name == "rejected once" and len(graph) == 2 and graph[0]["body"].get("reason") and graph[1]["body"].get("reason") not in allowed:
                probs.append("retried reason %r is not one the error allows" % graph[1]["body"].get("reason"))
            if len(graph) == 2 and graph[1]["body"].get("outcome") != graph[0]["body"].get("outcome"):
                probs.append("the retry changed the outcome")
            life = [x for x in rep["calls"] if x["tool"] == "close_call" and x["node"] != "t_close_call"]
            if life and graph and life[-1]["body"] != graph[-1]["body"]:
                probs.append("the lifecycle close_call sends %s, the graph's last close %s" % (life[-1]["body"], graph[-1]["body"]))
            out.append(("%s close %s" % (cid, name), probs, [(x["node"], x["status_code"], x["body"].get("outcome"), x["body"].get("reason")) for x in rep["calls"] if x["tool"] == "close_call"]))
    return out


def mutations():
    """The walker must catch planted wiring bugs (each on a copy of the A workflow, PUB-01)."""
    import copy
    c = dict((x["id"], x) for x in FIX["cases"])["PUB-01"]
    base = json.load(open(os.path.join(WD, WF["A"])))
    nodes = lambda w: w["workflow"]["nodes"]
    body = lambda w, n: nodes(w)[n]["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]

    def m_placeholder(w):
        nodes(w)["greet"]["on_enter"]["text"] = nodes(w)["greet"]["on_enter"]["text"].replace("{{last_name}}", "{{lastname}}")

    def m_body_var(w):
        body(w, "t_create_promise")["amount"]["default"] = "{{w_create_promise_amt}}"

    def m_mixed(w):
        body(w, "t_create_promise")["date"]["default"] = "on {{w_create_promise_day}}"

    def m_drop_edge(w):
        nodes(w)["hub"]["transitions"] = [t for t in nodes(w)["hub"]["transitions"] if t["target_node"] != "t_create_promise"]

    def m_bad_target(w):
        nodes(w)["exact_say"]["transitions"][0]["target_node"] = "hub_rset"

    def m_mapping(w):
        nodes(w)["t_get_account"]["response_mapping"] = []
        for k in ("get_account_data",):
            w["workflow"]["test_variables"].pop(k, None)

    def m_pattern(w):
        for n in nodes(w).values():
            for x in n.get("extraction_schema") or []:
                x["validation_pattern"] = "^n=[a-z]{6};src=user;kind=(who|identity)(;.*)?$"

    def m_no_close(w):
        nodes(w)["close_say"]["passthrough_default_transition"] = "end"
        nodes(w)["close_say"]["transitions"] = [dict(target_node="end", condition=dict(operator="always"))]
        w["workflow"]["tools"] = []

    oas_enum = copy.deepcopy(OAS)          # the bank's close_call enum without 'promise'
    for path, ops in oas_enum["paths"].items():
        if path.endswith("close_call"):
            sch = ops["post"]["requestBody"]["content"]["application/json"]["schema"]
            while "$ref" in sch:
                ref = sch["$ref"].lstrip("#/").split("/")
                sch = oas_enum
                for r in ref:
                    sch = sch[r]
            sch["properties"]["outcome"]["enum"] = [x for x in sch["properties"]["outcome"].get("enum", []) if x != "promise"] or ["x"]

    out = []
    for name, mut in (("unresolved placeholder in the greet", m_placeholder), ("body var renamed (required field dropped)", m_body_var),
                      ("mixed literal placeholder in a body", m_mixed), ("hub edge to t_create_promise removed", m_drop_edge),
                      ("transition to a missing node", m_bad_target), ("get_account response_mapping removed", m_mapping),
                      ("validation_pattern rejects most events", m_pattern), ("close path without close_call", m_no_close),
                      ("OAS close_call enum without the outcome", None)):
        w = copy.deepcopy(base)
        if mut:
            mut(w)
        evs = [s["event"] for s in c["steps"] if s["source"] == "user"]
        rep = walk(w, OAS if mut else oas_enum, dict(c["call_variables"]), evs, bank_for(c))
        probs = rep["errors"] + compare([s["action"] for s in c["steps"]], hub_actions(rep)) + ([] if rep["ended"] else ["no end"])
        out.append((name, probs, name.startswith("get_account response_mapping")))   # the hub also reads the flat keys
    return out


if __name__ == "__main__":
    ids = sys.argv[1:] or CASES
    bad = 0
    byid = dict((c["id"], c) for c in FIX["cases"])
    for cid in ids:
        rep, probs = run(byid[cid])
        bad += bool(probs)
        print(("PASS" if not probs else "FAIL") + " %s  nodes=%d calls=%s  warnings=%d" % (
            cid, len(set(rep["entered"])), [c["tool"] for c in rep["calls"]], len(rep["warnings"])))
        for p in probs[:10]:
            print("      ", p[:260])
    for name, fail, check in (("PUB-01 + create_promise 500 once", dict(create_promise=1), fail_once),
                              ("PUB-01 + create_promise 500 twice", dict(create_promise=2), fail_twice)):
        c = byid["PUB-01"]
        steps = [s for s in c["steps"]]
        rep, probs = run(c, fail, check)
        bad += bool(probs)
        print(("PASS" if not probs else "FAIL") + " %s  calls=%s" % (name, [(x["tool"], x["status_code"]) for x in rep["calls"]]))
        for p in probs[:10]:
            print("      ", p[:260])
    for name, probs, closes in close_retry_cases():
        bad += bool(probs)
        print(("PASS" if not probs else "FAIL") + " %s  closes=%s" % (name, closes))
        for p in probs[:6]:
            print("      ", p[:260])
    print("graph walk:", "all clean" if not bad else "%d case(s) with problems" % bad)
    for name, probs, robust in mutations():
        if robust:   # a planted change the build is meant to survive
            bad += bool(probs)
            print(("SURVIVED " if not probs else "BROKE   ") + name + (": " + probs[0][:200] if probs else " (expected: the hub falls back to the flattened response keys)"))
            continue
        bad += not probs
        print(("CAUGHT   " if probs else "MISSED   ") + name + ": " + (probs[0][:200] if probs else ""))
    sys.exit(1 if bad else 0)
