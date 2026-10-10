"""Live test of the real `ev` extraction on Codex's utterance bank (codex-gen 0b52456, tests/gen/utterances.jsonl).

Harness (extraction-only, chat): a 2-node test workflow carries the SAME ev field as the built agent (taken from the
generator's exact_say node of a brief-A build, so the same prompt, pattern and vocabulary). Per row:
  turn 0 "Hello?" (chat does not route turn 0) -> turn 1 "Okay." routes to node `say`, whose entry tts speaks the row's
  agent_said -> turn 2 the customer line, extracted in `say` with agent_said as the previous assistant turn.
The ev value is read from the call's variable_extracted event and parsed with the reducer's own parse_event.
Context differs from a real call only in the two warm-up turns before agent_said.

    python3 tests/ev_bank.py select                       # offline: write tests/ev_bank/selection.jsonl (~120 rows)
    python3 tests/ev_bank.py workflow                     # offline: write tests/ev_bank/workflow.json
    python3 tests/ev_bank.py selftest                     # offline: compare() on synthetic answers
    python3 tests/ev_bank.py live [--limit N] [--conc 3]  # LIVE (only in the granted window): save + run + report
    python3 tests/ev_bank.py report                       # tables from tests/ev_bank/results.jsonl
"""
import collections, concurrent.futures as cf, hashlib, json, os, random, string, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
D = os.path.join(ROOT, "tests", "ev_bank")
SRC = os.path.join(D, "utterances.jsonl")            # copy of codex-gen 0b52456:tests/gen/utterances.jsonl
RP = os.path.join(ROOT, "tests", "fallback", "runs", "none", "brief-a.policy.json")   # a brief-A reducer policy
OAS = os.path.join(ROOT, "tools", "openapi.json")
TRAPS = ["flat_vs_too_much", "refusal_counteroffer", "correction", "distractor_date", "spoken_number", "hedged_yes",
         "question_back", "year_carry", "priority_combo", "who_voicemail"]
CONTROLS = ["identity_format", "callback_payload", "vague_date"]
PER_TRAP, N_CONTROL = 11, 10
ALIAS = {"who": {"someone_else": "other", "voicemail": "unclear", "customer": "self"}}   # bank labels -> contract (ev prompt: voicemail is who=unclear)


def rows():
    return [json.loads(l) for l in open(SRC)]


def select():
    rnd, out = random.Random(7), []
    allr = rows()
    for t in TRAPS:
        pool = [r for r in allr if r["trap"] == t]
        out += rnd.sample(pool, min(PER_TRAP, len(pool)))
    ctrl = [r for r in allr if r["trap"] in CONTROLS]
    out += rnd.sample(ctrl, N_CONTROL)
    with open(os.path.join(D, "selection.jsonl"), "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    print(len(out), collections.Counter(r["trap"] for r in out))
    return out


def workflow():
    from builder.generator import generate
    rp = json.load(open(RP))
    wf = generate(rp, OAS)
    ev = next(n["extraction_schema"][0] for n in wf["nodes"].values() if (n.get("extraction_schema") or [{}])[0].get("name") == "ev")
    test = {"initial_node": "warm", "system_prompt": wf.get("system_prompt") or "",
            "test_variables": {"ev_tok": "kstart", "agent_said": "Can you make this payment today?", "customer_id": "c_ev",
                               "first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"},
            "nodes": {"warm": {"name": "warm", "node_type": "conversation", "task_message": "Reply only: Okay.",
                               "max_node_turns": 5, "transitions": [{"target_node": "say", "description": "always", "condition": {"operator": "always"}}]},
                      "say": {"name": "say", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{agent_said}}"},
                              "task_message": "No tool call is allowed. Wait for the customer.", "extraction_schema": [ev],
                              "max_node_turns": 10, "transitions": []}}}
    json.dump(test, open(os.path.join(D, "workflow.json"), "w"), indent=1)
    return test


def norm(k, v):
    if v is None:
        return None
    v = ALIAS.get(k, {}).get(v, v)
    if k in ("amt",):
        try: return round(float(v), 2)
        except (TypeError, ValueError): return v
    if k in ("d", "m", "y"):
        try: return int(v)
        except (TypeError, ValueError): return v
    return str(v)


def compare(expect, got):
    """Fields the row specifies (non-null) that differ. got: the parsed ev dict (or None)."""
    if got is None:
        return ["unparsed"]
    bad = []
    for k, v in expect.items():
        if v is None:
            continue                                   # the row does not specify it
        g = got.get(k)
        if k == "also" and got.get("also") == "topic" and got.get("also_t"):
            g = got["also_t"] if v not in ("topic",) else g
        if norm(k, g) != norm(k, v) and not (norm(k, g) in (None, "") and norm(k, v) in (None, "")):
            bad.append(f"{k}: {g!r} != {v!r}")
    return bad


def token(row_id):
    h = hashlib.sha1(row_id.encode()).digest()
    return "k" + "".join(string.ascii_lowercase[b % 26] for b in h[:5])


def selftest():
    from builder.engine.reducer import parse_event, TOPIC_RANK
    st = {"tok": "kabcde", "last_tok": "kstart"}
    e = parse_event("n=kabcde;src=user;kind=topic;also=amount;st=complete;prod=;t=dispute;amt=50.00", st, TOPIC_RANK)
    assert compare({"kind": "topic", "also": "amount", "t": "dispute", "amt": 50}, e) == []
    assert compare({"kind": "reject", "why": "too_much"}, dict(e, kind="reject", why="flat")) == ["why: 'flat' != 'too_much'"]
    e2 = parse_event("n=kabcde;src=user;kind=who;also=none;st=complete;prod=;who=other;party=relative", st, TOPIC_RANK)
    assert compare({"kind": "who", "also": None, "who": "someone_else"}, e2) == []
    assert compare({"kind": "date"}, None) == ["unparsed"]
    print("selftest PASS")


# ---------------------------------------------------------------- live
def _env():
    import tests._env as E
    E.load(os.path.join(ROOT.split("/.claude/worktrees/")[0], "env.sh"))
    import freya
    return freya


def sims(freya):
    r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=5)
    return [s["id"] for s in (r.get("simulations") or r.get("items") or r) if s.get("status") not in ("completed", "failed", "paused")]


def one(freya, wf_id, row):
    from builder.engine.reducer import parse_event, TOPIC_RANK
    tok = token(row["id"])
    cv = {"ev_tok": tok, "agent_said": row["agent_said"], "customer_id": "c_ev", "first_name": "Daniel", "last_name": "Reyes",
          "title": "Mr", "now": "2026-10-14T11:00"}
    call, lines, t0 = None, [], time.time()
    for msg in ["Hello?", "Okay.", row["customer_said"]]:
        body = {"workflowId": wf_id, "message": msg, "customerVariables": cv}
        if call: body["callId"] = call
        try:
            r = freya.api("POST", "/api/v2/chat/message", body)
        except Exception as e:                         # no re-send: the row is unmeasured
            return {"id": row["id"], "trap": row["trap"], "error": str(e)[:200], "lines": lines}
        call = r.get("callId", call); lines.append([msg, r.get("response")])
    try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
    except Exception: pass
    raw, said = None, None
    for m in freya.get_call(call).get("messages") or []:
        if m.get("role") == "assistant" and m.get("nodeId") == "say" and said is None:
            said = m.get("message")
        if m.get("role") == "system":
            try: e = json.loads(m.get("message") or "{}")
            except ValueError: continue
            if e.get("event") == "variable_extracted" and e.get("name") == "ev":
                raw = e.get("value")                     # the last one: the customer line
    got = parse_event(raw, {"tok": tok, "last_tok": "kstart"}, TOPIC_RANK) if raw else None
    return {"id": row["id"], "trap": row["trap"], "agent_said": row["agent_said"], "spoken_before": said, "customer": row["customer_said"],
            "expect": row["expect"], "raw": raw, "got": got, "diff": compare(row["expect"], got), "call_id": call,
            "s": round(time.time() - t0, 1), "lines": lines}


def live(limit=None, conc=3):
    freya = _env()
    running = sims(freya)
    if running:
        print("STOP: simulation running", running); return
    wf = json.load(open(os.path.join(D, "workflow.json")))
    print("dry run:", freya.validate_workflow("ev-bank", wf))
    ids = freya.save_workflow("ev-bank", wf, os.path.join(ROOT, "tests", ".platform-agents.json"))
    freya.save_workflow("ev-bank", wf, os.path.join(ROOT, "tests", ".platform-agents.json"))    # 2nd save sets the event model for chat
    sel = [json.loads(l) for l in open(os.path.join(D, "selection.jsonl"))][:limit]
    out = os.path.join(D, "results.jsonl")
    done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
    todo = [r for r in sel if r["id"] not in done]
    with cf.ThreadPoolExecutor(conc) as ex, open(out, "a") as f:
        futs = {}
        for i, r in enumerate(todo):
            if i and i % 15 == 0 and sims(freya):
                print("STOP: a simulation started; the rest is not sent"); break
            futs[ex.submit(one, freya, ids["workflow_id"], r)] = r
            if len(futs) >= conc:
                for fu in cf.as_completed(list(futs)):
                    res = fu.result(); f.write(json.dumps(res) + "\n"); f.flush(); futs.pop(fu)
                    print(("ok " if not res.get("diff") and not res.get("error") else "BAD"), res["id"], res["trap"], res.get("raw") or res.get("error"), flush=True)
                    break
        for fu in cf.as_completed(list(futs)):
            res = fu.result(); f.write(json.dumps(res) + "\n"); f.flush()
            print(("ok " if not res.get("diff") and not res.get("error") else "BAD"), res["id"], res["trap"], res.get("raw") or res.get("error"), flush=True)
    report()


def report():
    path = os.path.join(D, "results.jsonl")
    res = [json.loads(l) for l in open(path)]
    by = collections.defaultdict(lambda: [0, 0, 0])
    lines = ["| id | trap | agent said | customer | expected | got | diff |", "|---|---|---|---|---|---|---|"]
    for r in res:
        b = by[r["trap"]]
        if r.get("error"):
            b[2] += 1; continue
        b[1] += 1; b[0] += not r["diff"]
        if r["diff"]:
            exp = ";".join(f"{k}={v}" for k, v in r["expect"].items() if v is not None)
            lines.append(f"| {r['id']} | {r['trap']} | {r['agent_said']} | {r['customer']} | {exp} | {r['raw']} | {'; '.join(r['diff'])} |")
    acc = ["| trap | correct | measured | unmeasured |", "|---|---|---|---|"] + \
          [f"| {t} | {c} | {n} | {u} |" for t, (c, n, u) in sorted(by.items())]
    tot = [sum(x[i] for x in by.values()) for i in range(3)]
    acc.append(f"| **all** | {tot[0]} | {tot[1]} | {tot[2]} |")
    md = "\n".join(acc) + "\n\n" + "\n".join(lines) + "\n"
    open(os.path.join(D, "report.md"), "w").write(md)
    print(md)
    print("results sha1:", hashlib.sha1(open(path, "rb").read()).hexdigest()[:12])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "select": select()
    elif cmd == "workflow": workflow()
    elif cmd == "selftest": selftest()
    elif cmd == "report": report()
    elif cmd == "live":
        a = sys.argv[2:]
        live(int(a[a.index("--limit") + 1]) if "--limit" in a else None, int(a[a.index("--conc") + 1]) if "--conc" in a else 3)
