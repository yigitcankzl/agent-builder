"""Independent examiner (FINAL-PLAN Q1): a separate Claude call that sees ONLY the brief sources and the OAS, never our
policy, and answers the core questions with exact quotes. Its answers are compared with the extracted policy; every
disagreement gets ONE bounded re-check call that sees both readings with their quotes and the files (later files /
memos win); no majority vote. The quote-verified winner is kept; unresolved -> an `examiner_disagree` trace warning.

examine(paths, openapi, sink, deadline)             -> answers {qid: {"value", "source"}} (quotes verified)
disagreements(policy, answers)                      -> [{qid, ours, theirs, our_quotes, their_quotes}]
recheck(paths, openapi, dis, sink, deadline)        -> {qid: {"winner": "ours"|"theirs"|"neither", "value", "quote", "why"}}
apply(policy, qid, value)                           -> patches the extracted (pre-bridge) policy for patchable questions
"""
import copy, json, re

from builder.engine.date_policy import _norm, bad_quotes
from builder.policy_extract import _Forward, Trace, call_claude, material_block, oas_summary, parse_json, read_files

QUESTIONS = {
    "deadline_bands": "Late bands: for each band its name, the min and max days late it covers, the deadline as a number of days, and whether those are business days or calendar days. value: [{\"name\", \"min_days_late\", \"max_days_late\", \"days\", \"unit\": \"business\"|\"calendar\"}]",
    "holidays": "Every holiday (non-business date) the material lists, after later memos are applied. value: [\"YYYY-MM-DD\", ...]",
    "business_weekdays": "Which weekdays are business days. value: [ints, Monday=0 .. Sunday=6]",
    "attempts_per_band": "How many persuasion attempts each band allows. value: {\"<band name>\": int}",
    "floor": "The minimum acceptable amount (floor) per product type. value: {\"<product type or *>\": \"<account field name>\" or \"<N>%\" or \"<amount>\"}",
    "identity": "The identity questions in order (the tool's field names when the tool API names them) and how many wrong answers end the check. value: {\"fields\": [str], \"max_wrong\": int}",
    "outcomes": "Every close outcome/reason pair the agent may send (exact API strings; a code list maps codes to them). value: [[\"outcome\", \"reason or null\"], ...]",
    "callback_window": "The callback time window. value: {\"start\": \"HH:MM\", \"end\": \"HH:MM\"} or null",
    "pre_verification_transfer": "Queues a transfer may use BEFORE identity is verified. value: [\"queue\", ...] (empty if none)",
}

PROMPT = """You check a bank's call policy. Read ALL the material and answer each question below from the material
ONLY. Later files and memos that change a rule win over the rule they change. For every answer give the exact quote(s),
copied character for character from the named file. If the material does not say, answer null with source [].
Output JSON only: {"answers": {"<question id>": {"value": <value>, "source": [{"file": str, "quote": str}]}}}

QUESTIONS:
"""

RECHECK = """Two readings of ONE rule of a bank's call policy disagree. Re-read the material for exactly this rule and
decide which reading the material states. Later files and memos that change a rule win over the rule they change.
Answer "ours", "theirs" or "neither" (then give the correct value), with the exact quote that decides it, copied
character for character from the named file. Output JSON only:
{"items": [{"qid": str, "winner": "ours"|"theirs"|"neither", "value": <value in the question's format>, "source": {"file": str, "quote": str}, "why": str}]}
"""


# ---- normalised views of the extracted policy, in the questions' value formats ----

def ours(policy, qid):
    p = policy
    if qid == "deadline_bands":
        unit = "calendar" if "calendar" in str((p.get("deadline") or {}).get("rule", "")) else "business"
        return [{"name": b.get("name"), "min_days_late": b.get("min_days_late"), "max_days_late": b.get("max_days_late"),
                 "days": b.get("days"), "unit": unit} for b in (p.get("deadline") or {}).get("bands") or []]
    if qid == "holidays":
        return sorted((p.get("business_days") or {}).get("holidays") or [])
    if qid == "business_weekdays":
        return sorted((p.get("business_days") or {}).get("weekdays") or [])
    if qid == "attempts_per_band":
        return {b.get("name"): b.get("attempts") for b in (p.get("deadline") or {}).get("bands") or []}
    if qid == "floor":
        out = {}
        for t, f in ((p.get("products") or {}).get("floor_by_type") or {}).items():
            f = dict(f.get("params") or {}, **f) if isinstance(f, dict) else {}
            out[t] = f.get("field") or (f"{f['percent']:g}%" if f.get("percent") is not None else str(f.get("amount")))
        return out
    if qid == "identity":
        idn = p.get("identity") or {}
        return {"fields": [q.get("field") for q in idn.get("questions") or []], "max_wrong": idn.get("max_wrong")}
    if qid == "outcomes":
        return sorted(([r.get("outcome"), r.get("reason") or None] for r in (p.get("closing") or {}).get("table") or []), key=str)
    if qid == "callback_window":
        cb = (p.get("writes") or {}).get("callback") or {}
        return {"start": cb.get("start"), "end": cb.get("end")} if cb.get("start") else None
    if qid == "pre_verification_transfer":
        q = list(((p.get("writes") or {}).get("transfer") or {}).get("pre_verification_queues") or [])
        hr = p.get("human_request") or {}
        if hr.get("applies_before_verification") and hr.get("queue") and hr["queue"] not in q:
            q.append(hr["queue"])
        return sorted(q)
    return None


def _canon(qid, v):
    """A comparison key: order and spelling noise removed (names compared case/space-insensitively)."""
    s = lambda x: re.sub(r"[\s_\-]+", "_", str(x).strip().lower()) if x is not None else None
    try:
        if qid == "deadline_bands":
            return sorted((int(b["min_days_late"]), int(b["max_days_late"]), int(b["days"]), s(b.get("unit") or "business")) for b in v or [])
        if qid in ("holidays", "business_weekdays", "pre_verification_transfer"):
            return sorted(s(x) for x in v or [])
        if qid == "attempts_per_band":
            return sorted(int(x) for x in (v or {}).values())
        if qid == "floor":
            return sorted((s(k), s(str(x).rstrip("0").rstrip(".") if re.fullmatch(r"[\d.]+%?", str(x)) else x)) for k, x in (v or {}).items())
        if qid == "identity":
            return ([s(f) for f in (v or {}).get("fields") or []], int((v or {}).get("max_wrong") or 0))
        if qid == "outcomes":
            return sorted(((s(o), s(r) if r not in (None, "", "none", "null") else None) for o, r in v or []), key=str)
        if qid == "callback_window":
            return (v or {}).get("start"), (v or {}).get("end")
    except (TypeError, ValueError, KeyError, AttributeError):
        return ("unparsed", json.dumps(v, sort_keys=True, default=str))
    return json.dumps(v, sort_keys=True, default=str)


def _quotes(node):
    return [s.get("quote") for s in (node or {}).get("source") or [] if isinstance(s, dict) and s.get("quote")]


OUR_SOURCES = {"deadline_bands": "deadline", "holidays": "business_days", "business_weekdays": "business_days",
               "attempts_per_band": "deadline", "floor": "products", "identity": "identity", "outcomes": "closing",
               "callback_window": "writes", "pre_verification_transfer": "human_request"}


def examine(paths, openapi=None, sink=None, deadline=None):
    trace = _Forward(sink, deadline) if sink is not None else Trace(None)
    files, oas = read_files(paths), oas_summary(openapi)
    qs = "\n".join(f"- {k}: {v}" for k, v in QUESTIONS.items())
    out = parse_json(call_claude(PROMPT + qs + "\n\nMATERIAL:\n" + material_block(files, oas), "independent examiner", trace))
    ans = {}
    for qid, a in (out.get("answers") or {}).items():
        if qid in QUESTIONS and isinstance(a, dict) and a.get("value") is not None:
            if not a.get("source") or bad_quotes({qid: {"source": a["source"]}}, files):
                continue                     # an answer whose quote is not verbatim is not evidence
            ans[qid] = a
    return ans


def disagreements(policy, answers):
    out = []
    for qid, a in answers.items():
        mine = ours(policy, qid)
        if mine in (None, [], {}) and a["value"] in (None, [], {}):
            continue
        if _canon(qid, mine) != _canon(qid, a["value"]):
            out.append({"qid": qid, "ours": mine, "theirs": a["value"], "our_quotes": _quotes(policy.get(OUR_SOURCES[qid]))[:6],
                        "their_quotes": _quotes(a)[:6], "question": QUESTIONS[qid]})
    return out


def recheck(paths, dis, openapi=None, sink=None, deadline=None):
    if not dis:
        return {}
    trace = _Forward(sink, deadline) if sink is not None else Trace(None)
    files, oas = read_files(paths), oas_summary(openapi)
    out = parse_json(call_claude(RECHECK + "\nITEMS:\n" + json.dumps(dis, indent=1, default=str) + "\n\nMATERIAL:\n"
                                 + material_block(files, oas), "examiner re-check", trace))
    res = {}
    for it in out.get("items") or []:
        if it.get("qid") not in {d["qid"] for d in dis}:
            continue
        verified = bool(it.get("source")) and not bad_quotes({"x": {"source": [it["source"]]}}, files)
        res[it["qid"]] = dict(it, verified=verified)
    return res


def apply(policy, qid, value):
    """Patch the extracted policy with a re-check winner for the questions that map 1:1 onto policy fields.
    -> True when patched, False when the question is warn-only (outcomes, floor, attempts, pre-verification)."""
    p = policy
    if qid == "deadline_bands":
        old = {b.get("name"): b for b in (p.get("deadline") or {}).get("bands") or []}
        new = []
        for b in value or []:
            nb = dict(old.get(b.get("name")) or {}, name=b.get("name"), min_days_late=int(b["min_days_late"]),
                      max_days_late=int(b["max_days_late"]), days=int(b["days"]))
            new.append(nb)
        if new:
            p.setdefault("deadline", {})["bands"] = new
            if any(b.get("unit") == "calendar" for b in value):
                p["deadline"]["rule"] = "calendar_days_after_today"
            return True
    if qid == "holidays":
        p.setdefault("business_days", {})["holidays"] = sorted(value or [])
        return True
    if qid == "business_weekdays":
        p.setdefault("business_days", {})["weekdays"] = sorted(int(x) for x in value or [])
        return True
    if qid == "identity" and isinstance(value, dict) and isinstance(value.get("max_wrong"), int):
        p.setdefault("identity", {})["max_wrong"] = value["max_wrong"]
        return True
    if qid == "callback_window" and isinstance(value, dict) and value.get("start") and value.get("end"):
        cb = p.setdefault("writes", {}).setdefault("callback", {})
        cb["start"], cb["end"] = value["start"], value["end"]
        return True
    return False


def reconcile(policy, paths, openapi, answers, sink=None, deadline=None, log=None):
    """Compare, re-check each disagreement once, patch quote-verified examiner wins. -> (policy', report)."""
    log = log or (lambda *a, **k: None)
    pol = copy.deepcopy(policy)
    dis = disagreements(pol, answers)
    rep = {"answered": sorted(answers), "disagreements": len(dis), "patched": [], "kept_ours": [], "unresolved": []}
    if not dis:
        return pol, rep
    try:
        res = recheck(paths, dis, openapi, sink, deadline)
    except Exception as e:
        res = {}
        log("examiner_recheck", error=str(e)[:300])
    for d in dis:
        r = res.get(d["qid"]) or {}
        if r.get("verified") and r.get("winner") == "ours":
            rep["kept_ours"].append(d["qid"])
        elif r.get("verified") and r.get("winner") in ("theirs", "neither") and apply(pol, d["qid"], r.get("value") if r.get("winner") == "neither" else d["theirs"]):
            rep["patched"].append(d["qid"])
            log("examiner_patch", qid=d["qid"], old=d["ours"], new=r.get("value") if r.get("winner") == "neither" else d["theirs"],
                quote=(r.get("source") or {}).get("quote"), why=r.get("why"))
        else:
            rep["unresolved"].append(d["qid"])
            log("examiner_disagree", qid=d["qid"], ours=d["ours"], theirs=d["theirs"], our_quotes=d["our_quotes"],
                their_quotes=d["their_quotes"], recheck=r.get("winner"), recheck_verified=r.get("verified"))
    return pol, rep
