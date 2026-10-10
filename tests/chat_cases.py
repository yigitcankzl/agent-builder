"""Scripted chat runner: drive a saved agent through /api/v2/chat/message with a fixed customer script per case,
then score the mock bank's ledger with tools/score.py. No simulation, no judge: ledger checks only. One call at a time.

    python3 tests/chat_cases.py <slot or workflow_id> [--brief A] [--only PUB-01,PUB-06] [--scripts tests/chat_scripts.json] [--out f.json]

Scripts are data (tests/chat_scripts.json): {"<key>": {"case": "PUB-xx", "turns": [...]}}. A key may be a variant
("PUB-06:asks_back"); the case id says which practice session and expectation it uses.
The first chat turn is not routed, so "Hello?" is sent before the script. 503/504 -> the case is unmeasured, not re-sent.
"""
import argparse, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import tests._env as _env
MAIN = ROOT.split("/.claude/worktrees/")[0]
_env.load(os.path.join(MAIN, "env.sh"))  # worktrees share the main checkout's env.sh
import freya
from score import http, score_ledger

CASES = {c["id"]: c for c in json.load(open(os.path.join(ROOT, "public-test-set.json")))}
AGENTS = [os.path.join(ROOT, "tests", ".platform-agents.json"), os.path.join(MAIN, ".claude", "worktrees", "policy-extract", "tests", ".platform-agents.json")]


def workflow_id(slot):
    for p in AGENTS:
        if os.path.exists(p) and slot in json.load(open(p)):
            return json.load(open(p))[slot]["workflow_id"]
    return slot


def chat(body):
    t = time.time()
    try:
        return freya.api("POST", "/api/v2/chat/message", body), time.time() - t, None
    except RuntimeError as e:
        return None, time.time() - t, str(e)[:300]


def sim_running():
    """Ids of simulations running in this workspace now (to tell whether chat latency was measured under sim load)."""
    try:
        r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=5)
        return [s["id"] for s in (r.get("simulations") or r.get("items") or r) if s.get("status") not in ("completed", "failed", "paused")]
    except Exception:
        return None


def repeats(lines):
    """Agent sentences said in more than one turn: a cheap flag for the judge's 'offered once' kind of check."""
    seen, rep = {}, []
    for x in lines:
        for s in {s.strip() for s in str(x.get("agent") or "").replace("?", "?.").split(".") if len(s.strip()) > 15}:
            seen[s] = seen.get(s, 0) + 1
    return sorted(s for s, n in seen.items() if n > 1)


def run(wf_id, key, script, cap_extra=3):
    case = CASES[script["case"]]
    sims = sim_running()
    vars_ = http("/v1/practice/sessions", {"case": case["id"]})["variables"]
    call, lines, err, ended = None, [], None, False
    turns = ["Hello?"] + script["turns"]
    for i, msg in enumerate(turns + ["Okay."] * cap_extra):          # cap: a few filler turns if the agent has not closed
        if i >= len(turns) and ended:
            break
        body = {"workflowId": wf_id, "message": msg, "customerVariables": vars_}
        if call:
            body["callId"] = call
        r, dt, err = chat(body)
        if err:
            lines.append({"user": msg, "agent": None, "s": round(dt, 1), "error": err})
            break
        call = r.get("callId", call)
        ended = bool(r.get("ended") or r.get("callEnded") or r.get("isEnded") or r.get("status") in ("ended", "completed"))
        lines.append({"user": msg, "agent": r.get("response"), "s": round(dt, 1)})
        if ended:
            break
    if call and not ended:
        try: freya.api("POST", "/api/v2/chat/end", {"callId": call})
        except Exception: pass
    led = http("/v1/practice/ledger/" + vars_["customer_id"])
    if err and (led.get("calls") or [{}])[-1].get("tool") == "close_call":
        # the chat route answers 504 (no reply text) on the turn where the agent ends the call; the ledger shows the close
        lines[-1]["agent"], lines[-1]["closed_with"] = "(call ended by the agent; farewell not returned by chat)", err
        lines[-1].pop("error", None); err, ended = None, True
    unmeasured = bool(err and any(c in err for c in (" 503", " 504", "-> 503", "-> 504")))
    sc = score_ledger(case, led) if not unmeasured else {"pass": None, "failed": ["unmeasured: " + err]}
    if err and not unmeasured:
        sc["failed"].append("chat error: " + err); sc["pass"] = False
    return {"key": key, "case": case["id"], "pass": sc["pass"], "failed": sc["failed"], "call_id": call, "customer_id": vars_["customer_id"],
            "tools": [c["tool"] for c in led.get("calls", [])], "ledger": {k: led.get(k) for k in ("outcome", "reason", "promises", "notes", "callbacks", "transfers")},
            "expected": case["expected"], "lines": lines, "turn_s": [x["s"] for x in lines], "ended_by_agent": ended,
            "repeated_lines": repeats(lines), "sims_running": [sims, sim_running()]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent"); ap.add_argument("--only"); ap.add_argument("--out")
    ap.add_argument("--brief", help="A, B or AB: only cases of these briefs")
    ap.add_argument("--scripts", default=os.path.join(ROOT, "tests", "chat_scripts.json"))
    ap.add_argument("--during-sim", action="store_true", help="run even while a simulation is running (it slows both; see step-1 notes)")
    a = ap.parse_args()
    wf_id = workflow_id(a.agent)
    scripts = {k: v for k, v in json.load(open(a.scripts)).items() if not k.startswith("_")}
    keys = [k for k in scripts if (not a.only or k in a.only.split(",") or scripts[k]["case"] in a.only.split(","))
            and (not a.brief or CASES[scripts[k]["case"]]["brief"] in a.brief)]
    rows = []
    for k in keys:
        sims = sim_running()
        if sims and not a.during_sim:      # chat under sim load times out (504 at 60 s) and may slow the sim: stop, start nothing
            print(f"STOP before {k}: simulation running {sims}. Re-run when it has finished (or pass --during-sim).", flush=True)
            break
        r = run(wf_id, k, scripts[k]); rows.append(r)
        mark = "UNMEASURED" if r["pass"] is None else ("PASS" if r["pass"] else "FAIL")
        ts = r["turn_s"]
        print(f"{mark} {k} | {' > '.join(r['tools']) or '(no tool calls)'} | turns {len(ts)}, median {sorted(ts)[len(ts) // 2] if ts else 0:.1f} s, worst {max(ts or [0]):.1f} s, closed={r['ended_by_agent']}, sims running at start/end={r['sims_running']}")
        for f in r["failed"]: print("     -", f[:300])
        for s in r["repeated_lines"]: print("     ~ repeated:", s[:120])
        for x in r["lines"]: print(f"       U: {x['user']}\n       A: {x['agent'] if x['agent'] is not None else 'ERROR ' + x.get('error', '')}  ({x['s']} s)", flush=True)
        if a.out:                          # saved after every case, so a stopped run keeps what it measured
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            json.dump({"agent": a.agent, "workflow_id": wf_id, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": rows}, open(a.out, "w"), indent=1)
    m = [r for r in rows if r["pass"] is not None]
    print(f"\n{sum(r['pass'] for r in m)} / {len(m)} passed on the ledger ({len(rows) - len(m)} unmeasured, {len(keys) - len(rows)} not started). Judge checks are not run here.")


if __name__ == "__main__":
    main()
