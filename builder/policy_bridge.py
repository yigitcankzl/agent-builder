"""Policy -> reducer input (design/REDUCER-CONTRACT.md v3: §7 sections + §11 structural rules). Build-time,
deterministic, no model calls.

to_reducer(policy, oas_path, stable_unmapped=None) -> (reducer_policy, report)
  - every value sent to a tool is checked against its OpenAPI enum; a missing one becomes an `api_mismatch` entry
    {policy_path, value, field, oas_enum, fallback} and the policy carries the fallback value (§11.7). The reducer never
    sends a value outside the enum;
  - product type keys onto the get_account response enum; naming placeholders onto account fields;
  - event topics onto the contract vocabulary by topic NAME (incl. v3 decline/purpose); opening-phase situations
    become `who_rules` (incl. handoff); unknown topics are reported, never guessed;
  - `transfer.pre_verification_queues` (§11.2), `tools.<tool>` retry/on_fail (§11.5, defaults marked source=default),
    `hangup_default` slots (§11.3), `writes.notes.enabled` (§11.4);
  - default continue/safe lines; honesty words separated from disclosure words;
  - `unmapped` is never passed through: only rules stable across runs (consolidate_unmapped) become soft rules.
"""
import copy, difflib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.engine.date_policy import _norm, validate
from builder.policy_extract import oas_summary

DEFAULT = [{"file": "default", "quote": ""}]
# Generic cue words per contract topic (vocabulary of a collections call, not values of any brief); matched on the
# topic NAME with word boundaries. Order matters: the first topic whose cue matches wins.
TOPIC_CUES = {"hardship": ("hardship", "illness", "job loss", "bereavement", "death in the family"),
              "dispute": ("dispute", "not mine", "never had"),
              "paid": ("already paid", "paid"),
              "restructure": ("restructur\\w*", "payment plan", "lower instalments?"),
              "human": ("human", "person", "real agent"),
              "scam": ("scam", "fraud"),
              "robot": ("robot", "ai", "bot"),
              "unknown_info": ("unanswerable", "cannot answer", "unknown", "no information"),
              "stop": ("not want to talk", "dont want to talk", "don t want to talk", "stop talking", "stop"),
              "decline": ("declines? to answer", "refuses? to answer", "won t answer", "declines? identity",
                          "refuses? (the )?security questions?", "refuses? identity", "decline"),
              "purpose": ("purpose", "what (is )?(this|the call|call) is about", "what (this|the call) is about",
                          "why (are you )?calling", "asks why"),
              "injection": ("injection", "ignore instructions")}
WHO_CUES = {"handoff": ("hand", "handoff", "passes the phone", "gets the customer"),
            "wrong_number": ("wrong number",), "deceased": ("deceased", "died", "death of the customer"),
            "other": ("someone else", "third party", "relative"), "unclear": ("unclear", "ambiguous"),
            "callback": ("callback",)}
V3_ALWAYS = ("decline", "purpose")          # §11.6: always present in the generated grammar
DEFAULT_SENTENCES = {"continue_line": "Go on, please.", "safe_repeat": "Sorry, could you say that again?"}
DEFAULT_HONESTY = ["recorded", "scheduled", "transferred", "booked", "confirmed"]
# §11.5 defaults (source=default); a brief value overrides where it states one
TOOL_DEFAULTS = {"verify_identity": {"retries": 1, "on_fail": "close(unclear)"},
                 "get_account": {"retries": 1, "on_fail": "close(unclear)"},
                 "create_promise": {"retries": 1, "on_fail": "close(service_error)"},
                 "schedule_callback": {"retries": 1, "on_fail": "close(no_callback)"},
                 "transfer_to_agent": {"retries": 1, "on_fail": "continue"},
                 "add_note": {"retries": 1, "on_fail": "skip"},
                 "close_call": {"retries": 0, "on_fail": "continue"}}


def _enum(oas, tool, field, response=False):
    e = oas.get(tool + (" (response)" if response else ""), {}).get(field)
    return e if isinstance(e, list) else None


def _ptype(t):
    return re.sub(r"[\s-]+", "_", str(t).strip().lower())


def _first_quote(node):
    for s in (node or {}).get("source") or []:
        if isinstance(s, dict) and s.get("quote"):
            return s["quote"]
        if isinstance(s, str):
            return s
    return ""


def _match(head, cues):
    return any(re.search(r"\b" + c + r"\b", head) for c in cues)


def _topic_of(ev):
    """-> (kind, value): ('topic', t) | ('who', w) | (None, None). By the topic NAME only."""
    head = re.sub(r"[_\-']+", " ", str(ev.get("topic", ""))).lower()
    for t, cues in TOPIC_CUES.items():
        if _match(head, cues):
            return "topic", t
    for w, cues in WHO_CUES.items():
        if _match(head, cues):
            return "who", w
    return None, None


def consolidate_unmapped(runs):
    """runs: policies from repeated extractions of one brief -> (stable, unstable), normalised and de-duplicated.
    stable = present in every run (the same rule quoted shorter or longer counts)."""
    def key(q):
        return _norm(q).strip(" .\"'")
    per_run = []
    for p in runs:
        seen = {}
        for u in p.get("unmapped") or []:
            if isinstance(u, dict) and u.get("quote"):
                seen.setdefault(key(u["quote"]), u)
        per_run.append(seen)

    def in_run(k, r):
        return k in r or any(k in o or o in k for o in r if min(len(k), len(o)) >= 25)
    stable, unstable = [], []
    for k in sorted({k for r in per_run for k in r}):
        item = next(r[k] for r in per_run if k in r)
        n = sum(in_run(k, r) for r in per_run)
        (stable if n == len(per_run) else unstable).append(dict(item, runs_seen=n, runs=len(per_run)))
    dedup = []
    for s in sorted(stable, key=lambda x: -len(key(x["quote"]))):
        if not any(key(s["quote"]) in key(d["quote"]) for d in dedup):
            dedup.append(s)
    return dedup, unstable


def _closest(value, enum, cutoff=0.4):
    m = difflib.get_close_matches(str(value), enum, n=1, cutoff=cutoff)
    return m[0] if m else None


def to_reducer(policy, oas_path, stable_unmapped=None):
    oas = oas_summary(oas_path)
    p = copy.deepcopy(policy)
    mism, notes = [], []

    def mismatch(path, value, field, enum, fallback):
        mism.append({"policy_path": path, "value": value, "field": field, "oas_enum": enum, "fallback": fallback})

    # ---- products
    types = _enum(oas, "get_account", "products[].type", response=True)
    prod = p.setdefault("products", {})
    for k in ("floor_by_type", "naming_by_type"):
        m = {}
        for t, v in (prod.get(k) or {}).items():
            nt = _ptype(t)
            if types and nt not in types:
                fb = _closest(nt, types)
                mismatch(f"products.{k}.{t}", t, "get_account.products[].type", types, fb)
                nt = fb or nt
            m[nt] = v
        if k in prod:
            prod[k] = m
    for t, tpl in (prod.get("naming_by_type") or {}).items():
        def repl(mo):
            words = mo.group(1).lower()
            return "{card_last4}" if "last" in words else "{" + re.sub(r"\W+", "_", words).strip("_") + "}"
        prod["naming_by_type"][t] = re.sub(r"<([^>]+)>", repl, str(tpl))
    # ---- identity (§11.7: a field outside the enum is skipped, the next question is used)
    idn = p.setdefault("identity", {})
    e = _enum(oas, "verify_identity", "field")
    for i, q in enumerate(idn.get("questions") or []):
        if e and q.get("field") not in e:
            mismatch(f"identity.questions[{i}].field", q.get("field"), "verify_identity.field", e, "skip")
            q["skip"] = True
    # ---- closing (§11.7: closest enum member by name, else the unclear-family member)
    cl = p.setdefault("closing", {})
    e_out = _enum(oas, "close_call", "outcome")
    table = cl.get("table") or []
    for r in table:
        r["reason"] = r.get("reason") or None
    unclear_row = next((r for r in table if r["reason"] and _match(re.sub(r"_", " ", r["reason"]), WHO_CUES["unclear"])), None)
    for i, r in enumerate(table):
        if e_out and r["outcome"] not in e_out:
            fb = _closest(r["outcome"], e_out) or _closest("not reached unclear", e_out, 0.0)
            if not any(m["value"] == r["outcome"] for m in mism):
                mismatch(f"closing.table[{i}].outcome", r["outcome"], "close_call.outcome", e_out, fb)
            r["brief_outcome"], r["outcome"] = r["outcome"], fb
    by_outcome = {}
    for r in table:
        by_outcome.setdefault(r["outcome"], []).append(r["reason"])
    cl["reason_omitted_for"] = sorted(o for o, rs in by_outcome.items() if all(x is None for x in rs))
    # ---- hang-up defaults (§11.3)
    declined_row = idn.get("on_decline") or next((r for r in table if r["reason"] and "declin" in r["reason"]), None)
    p["hangup_default"] = {
        "before_who": {"outcome": (unclear_row or {}).get("outcome"), "reason": (unclear_row or {}).get("reason")},
        "before_verified": {"outcome": (declined_row or {}).get("outcome"), "reason": (declined_row or {}).get("reason")},
        "after_verified": "computed", "source": DEFAULT}
    if not unclear_row:
        notes.append("no 'unclear' row in the closing table: hangup_default.before_who is empty")
    # ---- writes, transfer, tools
    w = p.setdefault("writes", {})
    tr = w.get("transfer") or {}
    e_q = _enum(oas, "transfer_to_agent", "queue")
    qfb = lambda q: q if not e_q or q in e_q else ("general" if "general" in e_q else e_q[0])
    qmap = {}
    for sit, q in (tr.get("queue_map") or {}).items():
        if e_q and q not in e_q:
            mismatch(f"writes.transfer.queue_map.{sit}", q, "transfer_to_agent.queue", e_q, qfb(q))
        qmap[sit] = qfb(q)
    pre = [qfb(q) for q in tr.get("pre_verification_queues") or []]
    p["transfer"] = {"queue_map": qmap, "pre_verification_queues": pre,
                     "source": w.get("source") or DEFAULT}
    if not tr.get("pre_verification_queues"):
        notes.append("transfer.pre_verification_queues not stated by the brief: empty (no transfer before verification)")
    nt = w.setdefault("notes", {})
    nt["enabled"] = bool(nt.get("enabled", str(nt.get("when", "")).strip().lower() not in ("", "never", "none")))
    e_n = _enum(oas, "add_note", "reason")
    for i, ev in enumerate(p.get("events") or []):
        nr = str(ev.get("note_reason") or "").strip().lower()
        if nr in ("none", "null", "n/a", "-"):
            ev["note_reason"], nr = "", ""
        if nr and e_n and nr not in e_n:
            mismatch(f"events[{i}].note_reason", nr, "add_note.reason", e_n, "skip")
            ev["note_reason"] = ""
    tools = {}
    for tool, d in TOOL_DEFAULTS.items():
        tools[tool] = dict(d, fail_say="", source=DEFAULT)
    pr = w.get("promise") or {}
    if isinstance(pr.get("retries"), int):
        tools["create_promise"].update(retries=pr["retries"], fail_say=pr.get("fail_say", ""), source=w.get("source") or DEFAULT)
    if (p.get("multi_product") or {}).get("applies"):
        tools["create_promise"]["on_fail"] = "continue"   # B11: product failed, note service_error, continue
    p["tools"] = tools
    # ---- events onto the contract topics, brief order = precedence
    evs, who, unknown = [], [], []
    for ev in p.get("events") or []:
        kind, val = _topic_of(ev)
        if kind == "topic":
            evs.append(dict(ev, topic=val, brief_topic=ev.get("topic"), precedence=len(evs)))
        elif kind == "who":
            who.append(dict(ev, who=val, brief_topic=ev.get("topic")))
        else:
            unknown.append(ev.get("topic"))
    for t in V3_ALWAYS:
        if not any(e_["topic"] == t for e_ in evs):
            evs.append({"topic": t, "brief_topic": None, "precedence": len(evs), "source": DEFAULT})
    p["events"], p["who_rules"] = evs, who
    if unknown:
        notes.append(f"event topics with no contract topic (kept out of the reducer, for review): {unknown}")
    # ---- sentences, honesty, free talk
    sent = p.setdefault("sentences", {})
    for sid, text in DEFAULT_SENTENCES.items():
        sent.setdefault(sid, {"text": text, "verbatim": True, "max_times": 99, "source": DEFAULT})
    words = [x.lower() for x in (p.get("honesty_words") or {}).get("words") or []]
    if words and not any(x in DEFAULT_HONESTY for x in words):
        p["disclosure_words"] = p["honesty_words"]
        notes.append(f"honesty_words held pre-verification words {words}; moved to disclosure_words")
        words = []
    if not words:
        p["honesty_words"] = {"words": DEFAULT_HONESTY, "source": DEFAULT}
    p.setdefault("free_talk_nodes", ["talk_pre", "talk_post"])
    # ---- unmapped: only stable rules, as soft rules
    p["unmapped_rules"] = [{k: u.get(k) for k in ("rule_id", "quote", "file", "phase_guess", "kind_guess")} for u in (stable_unmapped or [])]
    p.pop("unmapped", None)
    p["api_mismatch"] = mism
    report = {"api_mismatch": mism, "notes": notes, "errors": validate(p),
              "events": [(e_["brief_topic"], e_["topic"]) for e_ in evs], "who": [(x["brief_topic"], x["who"]) for x in who]}
    return p, report


if __name__ == "__main__":
    pol = json.load(open(sys.argv[1]))
    rp, rep = to_reducer(pol, sys.argv[2] if len(sys.argv) > 2 else "tools/openapi.json")
    print(json.dumps(rep, indent=1))
