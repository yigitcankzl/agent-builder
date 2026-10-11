"""Final-case runner: cases -> Turkish personas -> Freya simulations -> per-case results.

    python3 tests/final_runner/run_final.py <agent_id> --cases <cases.json> [--reps N] [--style S] [--styles f.json]
        [--out results.json] [--mock-state URL] [--concurrency 5] [--dry-run]

--dry-run prints the persona and simulation payloads and makes no Freya call. Nothing here touches builder/.
Every call gets two variables: customerNumber (8 digits) and now (Istanbul time, ISO with +03:00).
A failed request is recorded and not re-sent (no retry on 503/504).
"""
import argparse, hashlib, json, os, re, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]

import freya  # noqa: E402  (imports offline; calls happen only in the real run)

NOW_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00$")
CUST_RE = re.compile(r"^\d{8}$")
STORE = os.path.join(HERE, ".personas.json")

# Persona wrapper in Turkish. It carries no case facts: the facts come only from the case's script.
LANGUAGE_RULE = "Türkçe konuş. Bütün cümlelerini Türkçe söyle."
PERSONA_TR = """ÇIKTI KURALI: Sadece telefonda söyleyeceğin kelimeleri yaz. Sahne yönergesi, parantez ya da açıklama yazma.
{language}
Bir ya da iki kısa cümle söyle, sonra karşı tarafın cevabını bekle.

NE BİLİYORSUN VE NE İSTİYORSUN:
{script}

KURALLAR:
- Sana sorulanı cevapla. Sorulmayan bilgiyi kendiliğinden verme.
- Bir sayı ya da tarih verdiğinde hepsini tek turda söyle; yarıda kesme.
- Metinde yazmayan tutar, tarih ya da bilgi uydurma. Yazılmayan bir konu sorulursa kısa ve nötr cevap ver.
- Karşı taraf bir şeyi geri okur ve senin kabul ettiğinle uyuşursa, "Evet, onaylıyorum." de.
- Karşı taraf veda ederse "Teşekkürler, iyi günler." de ve başka bir şey söyleme."""

CASE_KEYS = {"id", "customerNumber", "now", "script", "checks", "style", "expect", "unchecked", "title"}


def load_cases(path, allow_unchecked=False):
    """Read and validate a cases file: a JSON list of case objects."""
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: the cases file must be a JSON list")
    seen, out = set(), []
    for i, c in enumerate(data):
        where = f"{path}[{i}] {c.get('id', '?')}"
        extra = set(c) - CASE_KEYS
        if extra:
            raise ValueError(f"{where}: unknown keys {sorted(extra)}")
        for k in ("id", "customerNumber", "now", "script"):
            if not c.get(k):
                raise ValueError(f"{where}: missing {k}")
        if c["id"] in seen:
            raise ValueError(f"{where}: duplicate id")
        seen.add(c["id"])
        if not CUST_RE.match(str(c["customerNumber"])):
            raise ValueError(f"{where}: customerNumber must be 8 digits")
        if not NOW_RE.match(c["now"]):
            raise ValueError(f"{where}: now must look like 2026-10-12T10:30:00+03:00")
        if not c.get("checks") and not (c.get("unchecked") and allow_unchecked):
            raise ValueError(f"{where}: no checks (judge criteria); add checks or pass --allow-unchecked")
        out.append(c)
    return out


def style_table(extra_file=None):
    """The kit's official styles, plus any extra styles from a JSON file (name -> paragraph)."""
    import run_cases  # tools/run_cases.py: its STYLES dict, read only
    table = dict(run_cases.STYLES)
    if extra_file:
        table.update(json.load(open(extra_file, encoding="utf-8")))
    return table


def persona_text(case, style, styles):
    if style and style not in styles:
        raise ValueError(f"unknown style {style!r}")
    text = PERSONA_TR.format(language=LANGUAGE_RULE, script=case["script"])
    if style:
        text += "\n\n" + styles[style]
    return text


def persona_for(case, style, styles):
    """One persona in the shape freya.create_personas takes."""
    st = style or case.get("style")
    name = case["id"] + (" " + case["title"] if case.get("title") else "") + (f" [{st}]" if st else "")
    crit = "Hepsi doğru olmalı:\n- " + "\n- ".join(case.get("checks") or ["(no checks: unchecked case)"])
    return {"name": name, "prompt": persona_text(case, st, styles), "successCriteria": crit,
            "tags": ["hackathon", "final-case"] + ([st] if st else [])}


def simulation_payload(agent_id, name, personas_by_case, cases, concurrency=5, max_seconds=420):
    """The body that freya.run_simulation posts, built here so the dry run prints exactly this shape."""
    selected = [personas_by_case[c["id"]] for c in cases]
    vars_map = {personas_by_case[c["id"]]: {"customerNumber": c["customerNumber"], "now": c["now"]} for c in cases}
    return {"agentId": agent_id, "name": name, "mode": "chat", "selectedPersonaIds": selected,
            "customerVariablesMap": vars_map, "maxConcurrentCalls": concurrency, "runsPerPersona": 1,
            "maxCallDurationSeconds": max_seconds,
            "assistantLlmOverride": freya.AGENT_LLM, "routingLlmOverride": freya.AGENT_LLM,
            "extractionLlmOverride": freya.AGENT_LLM, "personaLlmOverride": freya.SIM_LLM,
            "analysisLlmOverride": freya.SIM_LLM}


def personas_store_key(case, style, styles):
    p = persona_for(case, style, styles)
    return case["id"] + ":" + hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:10], p


def ensure_personas(cases, style, styles):
    """Create (once per text) the personas in Freya; returns {case id: persona id}."""
    store = json.load(open(STORE)) if os.path.exists(STORE) else {}
    keys = {c["id"]: personas_store_key(c, style, styles) for c in cases}
    new = [(c["id"], keys[c["id"]]) for c in cases if keys[c["id"]][0] not in store]
    if new:
        made = freya.create_personas([p for _, (_, p) in new])["personas"]
        for (cid, (k, _)), p in zip(new, made):
            store[k] = p["id"]
        json.dump(store, open(STORE, "w"), indent=1)
    return {c["id"]: store[keys[c["id"]][0]] for c in cases}


def call_facts(call_id):
    """Slowest agent turn and the tools called, from the transcript (same reading as tools/run_cases.py)."""
    c = freya.get_call(call_id)
    last_user, worst, tools = None, 0.0, []
    for m in c.get("messages") or []:
        t = m.get("secondsFromStart")
        if t is not None:
            if m.get("role") == "user":
                last_user = t
            elif last_user is not None:
                worst = max(worst, t - last_user)
                last_user = None if m.get("role") == "assistant" else last_user
        ev = m.get("message")
        if m.get("role") == "system" and isinstance(ev, str) and '"function_call_start"' in ev:
            try:
                e = json.loads(ev)
            except ValueError:
                continue
            if e.get("function") == "api_call":
                tools.append(str((e.get("args") or {}).get("url", "")).rstrip("/").rsplit("/", 1)[-1])
            elif e.get("function"):
                tools.append(e["function"])
    return {"slowest_turn_s": round(worst, 1), "tools": tools, "ended": c.get("endedReason")}


def fetch_state(base, case):
    """Read-only mock state for one customer. The mock's state route is not fixed yet, so this is a hook: it
    GETs {base}/state/{customerNumber} and expects a JSON object. Nothing is written."""
    url = f"{base.rstrip('/')}/state/{case['customerNumber']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (final-runner)"}), timeout=60) as r:
        return json.load(r)


def check_expect(case, state):
    """Compare the expected mock side effects (case['expect']['mock'], a dict) with the state read back."""
    want = (case.get("expect") or {}).get("mock")
    if not want:
        return None, "no mock expectation in this case"
    if state is None:
        return None, "mock state not read (no --mock-state): expectation not checked"
    bad = [f"{k}: {state.get(k)!r} != {v!r}" for k, v in want.items() if state.get(k) != v]
    return (not bad), "; ".join(bad) or "mock side effects as expected"


def run(args):
    cases = load_cases(args.cases, args.allow_unchecked)
    styles = style_table(args.styles)
    style = args.style
    name = f"final {os.path.basename(args.cases)} {time.strftime('%H:%M:%S')}"
    if args.dry_run:
        pids = {c["id"]: f"DRY-{c['id']}" for c in cases}
        print(json.dumps({"personas": [persona_for(c, style, styles) for c in cases],
                          "simulation": simulation_payload(args.agent_id, name, pids, cases, args.concurrency)},
                         ensure_ascii=False, indent=1))
        return 0
    pids = ensure_personas(cases, style, styles)
    reps, errors = [], []
    for rep in range(args.reps):
        try:
            sim_id, it_id, status = freya.run_simulation(args.agent_id, name,
                {pids[c["id"]]: {"customerNumber": c["customerNumber"], "now": c["now"]} for c in cases},
                max_seconds=420, concurrency=args.concurrency)
        except RuntimeError as e:          # 503/504 or any API error: recorded, never re-sent
            errors.append({"rep": rep + 1, "error": str(e)[:300]})
            break
        runs = {r["personaId"]: r for r in freya.get_iteration(sim_id, it_id)["runs"]}
        rows = []
        for c in cases:
            j = runs.get(pids[c["id"]], {})
            facts = call_facts(j["callId"]) if j.get("callId") else {"slowest_turn_s": None, "tools": [], "ended": None}
            judge_ok = j.get("outcome") == "pass"
            state, mock_note = None, "no mock state read"
            if args.mock_state and c.get("expect", {}).get("mock"):
                try:
                    state = fetch_state(args.mock_state, c)
                except (urllib.error.URLError, ValueError) as e:
                    mock_note = f"mock state unreadable: {e}"
            mock_ok, note = check_expect(c, state)
            passed = judge_ok and (mock_ok is not False)
            rows.append({"id": c["id"], "pass": passed, "judge": j.get("outcome"),
                         "reason": " ".join(str(j.get("reason") or "no verdict").split())[:500],
                         "call_id": j.get("callId"), "slowest_turn_s": facts["slowest_turn_s"],
                         "tools": facts["tools"], "ended": facts["ended"],
                         "mock": note if state is not None else mock_note})
        reps.append({"sim": sim_id, "iteration": it_id, "rows": rows})
        print(f"-- rep {rep + 1}/{args.reps}: {sum(r['pass'] for r in rows)}/{len(rows)} pass ({sim_id})", flush=True)
    summary = {c["id"]: {"passes": sum(r["rows"][k]["pass"] for r in reps), "runs": len(reps)} for k, c in enumerate(cases) if reps}
    out = {"agent_id": args.agent_id, "cases_file": args.cases, "style": style, "concurrency": args.concurrency,
           "reps": reps, "summary": summary, "errors": errors}
    if args.out:
        json.dump(out, open(args.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for cid, s in summary.items():
        print(f"{cid}: {s['passes']}/{s['runs']}")
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("agent_id")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--style")
    ap.add_argument("--styles", help="JSON file of extra style paragraphs (name -> text)")
    ap.add_argument("--out")
    ap.add_argument("--mock-state", help="base URL of the mock; read-only GET of /state/{customerNumber}")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--allow-unchecked", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
