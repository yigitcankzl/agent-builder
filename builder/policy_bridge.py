"""Policy -> reducer input (design/REDUCER-CONTRACT.md v2.1 §7). Build-time, deterministic, no model calls.

to_reducer(policy, oas_path, stable_unmapped=None) -> (reducer_policy, report)
  - tool values are checked against the OpenAPI enums; a brief value with no enum entry becomes an explicit
    `api_mismatch` item (value, field, quote), never a silent mapping;
  - product type keys are normalised to the get_account response enum;
  - event topics are mapped onto the contract's topic vocabulary (§1.2); unmapped topics are reported, not guessed;
  - builder-convention sentences the brief never words (continue_line, safe_repeat) are added as source=default;
  - honesty words (success words banned before the matching tool success) are separated from disclosure words
    (words banned before verification);
  - `unmapped` is NOT passed through: only rules that are stable across runs (consolidate_unmapped) are kept, as soft
    rules for the free-talk prompts; unstable ones stay in the report and never become behaviour.
"""
import copy, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.engine.date_policy import _norm, validate
from builder.policy_extract import oas_summary

TOPICS = ("hardship", "dispute", "paid", "restructure", "human", "scam", "robot", "unknown_info", "stop", "injection", "other")
# Generic cue words per contract topic (domain vocabulary of a collections call, not values of any brief)
TOPIC_CUES = {"hardship": ("hardship", "illness", "job loss", "death in the family"),
              "dispute": ("dispute", "not mine", "never had"),
              "paid": ("already paid", "paid"),
              "restructure": ("restructur", "payment plan", "lower instalment"),
              "human": ("human", "person", "real agent"),
              "scam": ("scam", "fraud"),
              "robot": ("robot", "ai question", "are you ai", "bot"),
              "unknown_info": ("unanswerable", "cannot answer", "unknown question", "no information"),
              "stop": ("not want to talk", "dont want to talk", "stop talking", "stop"),
              "injection": ("injection", "ignore instructions")}
# Opening-phase situations are `who`/`callback` events in the contract, not topics: kept as phase rules
WHO_CUES = ("wrong number", "deceased", "died", "someone else", "third party", "relative", "unclear", "callback", "who is on")
DEFAULT_SENTENCES = {"continue_line": "Go on, please.", "safe_repeat": "Sorry, could you say that again?"}
DEFAULT_HONESTY = ["recorded", "scheduled", "transferred", "booked", "confirmed"]


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


def _topic_of(ev):
    """Map by the topic NAME only (descriptions mention many things); -> contract topic, 'who', or None."""
    head = re.sub(r"[_\-]+", " ", str(ev.get("topic", ""))).lower()
    for t, cues in TOPIC_CUES.items():
        if any(re.search(r"\b" + re.escape(c), head) for c in cues):
            return t
    if any(c in head for c in WHO_CUES):
        return "who"
    return None


def consolidate_unmapped(runs):
    """runs: list of policies from repeated extractions of the same brief.
    -> (stable, unstable): normalised, de-duplicated quote-backed rules; stable = present in every run."""
    def key(q):
        return _norm(q).strip(" .\"'")
    per_run = []
    for p in runs:
        seen = {}
        for u in p.get("unmapped") or []:
            if isinstance(u, dict) and u.get("quote"):
                seen.setdefault(key(u["quote"]), u)
        per_run.append(seen)
    allkeys = {k for r in per_run for k in r}

    def in_run(k, r):  # exact, or one quote contains the other (the same rule quoted shorter or longer)
        return k in r or any(k in o or o in k for o in r if min(len(k), len(o)) >= 25)
    stable, unstable = [], []
    for k in sorted(allkeys):
        item = next(r[k] for r in per_run if k in r)
        n = sum(in_run(k, r) for r in per_run)
        (stable if n == len(per_run) else unstable).append(dict(item, runs_seen=n, runs=len(per_run)))
    # drop stable duplicates where one quote contains another
    dedup = []
    for s in sorted(stable, key=lambda x: -len(key(x["quote"]))):
        if not any(key(s["quote"]) in key(d["quote"]) for d in dedup):
            dedup.append(s)
    return dedup, unstable


def to_reducer(policy, oas_path, stable_unmapped=None):
    oas = oas_summary(oas_path)
    p = copy.deepcopy(policy)
    mism, notes = [], []

    def mismatch(value, field, node):
        mism.append({"value": value, "field": field, "quote": _first_quote(node)})

    # products: type keys onto the get_account response enum
    types = _enum(oas, "get_account", "products[].type", response=True)
    prod = p.get("products") or {}
    for k in ("floor_by_type", "naming_by_type"):
        m = {}
        for t, v in (prod.get(k) or {}).items():
            nt = _ptype(t)
            if types and nt not in types:
                mismatch(t, f"products.{k} (get_account products[].type)", prod)
            m[nt] = v
        if k in prod:
            prod[k] = m
    # spoken names: a <placeholder> becomes the account field it names (e.g. the last digits field)
    fields = list((oas.get("get_account (response)") or {}).keys())
    for t, tpl in (prod.get("naming_by_type") or {}).items():
        def repl(mo):
            words = mo.group(1).lower()
            cand = [f for f in ("card_last4", "last4", "account_last4") if "last" in words]
            return "{" + (cand[0] if cand else re.sub(r"\W+", "_", words).strip("_")) + "}"
        prod["naming_by_type"][t] = re.sub(r"<([^>]+)>", repl, str(tpl))
    # identity fields
    idn = p.get("identity") or {}
    e = _enum(oas, "verify_identity", "field")
    for q in idn.get("questions") or []:
        if e and q.get("field") not in e:
            mismatch(q.get("field"), "verify_identity.field", idn)
            q["api_mismatch"] = True
    # closing table
    cl = p.get("closing") or {}
    e = _enum(oas, "close_call", "outcome")
    seen = set()
    for r in cl.get("table") or []:
        r["reason"] = r.get("reason") or None
        if e and r.get("outcome") not in e and r.get("outcome") not in seen:
            seen.add(r.get("outcome"))
            mismatch(r.get("outcome"), "close_call.outcome", cl)
    by_outcome = {}
    for r in cl.get("table") or []:
        by_outcome.setdefault(r["outcome"], []).append(r["reason"])
    cl["reason_omitted_for"] = sorted(o for o, rs in by_outcome.items() if all(x is None for x in rs))
    # writes: transfer queues and note reasons
    w = p.get("writes") or {}
    e = _enum(oas, "transfer_to_agent", "queue")
    for sit, q in ((w.get("transfer") or {}).get("queue_map") or {}).items():
        if e and q not in e:
            mismatch(q, "transfer_to_agent.queue", w)
    e = _enum(oas, "add_note", "reason")
    for ev in p.get("events") or []:
        nr = str(ev.get("note_reason") or "").strip().lower()
        if nr in ("none", "null", "n/a", "-"):
            ev["note_reason"], nr = "", ""
        if nr and e and nr not in e:
            mismatch(nr, "add_note.reason", ev)
    # events onto the contract topics, in the brief's order (= precedence)
    evs, who, unknown = [], [], []
    for i, ev in enumerate(p.get("events") or []):
        t = _topic_of(ev)
        if t is None:
            unknown.append(ev.get("topic"))
        elif t == "who":
            who.append(dict(ev, brief_topic=ev.get("topic")))
        else:
            evs.append(dict(ev, topic=t, brief_topic=ev.get("topic"), precedence=len(evs)))
    p["events"], p["who_rules"] = evs, who
    if unknown:
        notes.append(f"event topics with no contract topic (kept out of the reducer, listed for review): {unknown}")
    # sentences the reducer needs but a brief never words
    sent = p.setdefault("sentences", {})
    for sid, text in DEFAULT_SENTENCES.items():
        sent.setdefault(sid, {"text": text, "verbatim": True, "max_times": 99, "source": [{"file": "default", "quote": ""}]})
    # honesty vs disclosure words
    hw = p.get("honesty_words") or {}
    words = [x.lower() for x in hw.get("words") or []]
    if words and not any(x in DEFAULT_HONESTY for x in words):
        p["disclosure_words"] = hw  # these are words banned before verification, not success words
        notes.append(f"honesty_words held pre-verification words {words}; moved to disclosure_words")
        p["honesty_words"] = {"words": DEFAULT_HONESTY, "source": [{"file": "default", "quote": ""}]}
    elif not words:
        p["honesty_words"] = {"words": DEFAULT_HONESTY, "source": [{"file": "default", "quote": ""}]}
    p.setdefault("free_talk_nodes", ["talk_pre", "talk_post"])
    # unmapped: only stable ones, as soft rules
    p["unmapped_rules"] = [{k: u.get(k) for k in ("rule_id", "quote", "file", "phase_guess", "kind_guess")} for u in (stable_unmapped or [])]
    p.pop("unmapped", None)
    p["api_mismatch"] = mism
    report = {"api_mismatch": mism, "notes": notes, "errors": validate(p), "events": [(e_["brief_topic"], e_["topic"]) for e_ in evs]}
    return p, report


if __name__ == "__main__":
    pol = json.load(open(sys.argv[1]))
    rp, rep = to_reducer(pol, sys.argv[2] if len(sys.argv) > 2 else "tools/openapi.json")
    print(json.dumps(rep, indent=1))
