"""Policy -> reducer input (design/REDUCER-CONTRACT.md v3: §7 sections + §11 structural rules). Build-time,
deterministic, no model calls.

to_reducer(policy, oas_path, stable_unmapped=None) -> (reducer_policy, report)
  - every value sent to a tool is checked against its OpenAPI enum; a missing one becomes an `api_mismatch` entry
    {policy_path, value, field, oas_enum, action}: map_to only for an exact OAS value or a SOURCED alias, else block
    (safety rules overriding v3.1 §13.2: no closest-name mapping; a required identity field is never skipped). The reducer never
    sends a value outside the enum;
  - product type keys onto the get_account response enum; naming placeholders onto account fields;
  - event topics onto the contract vocabulary by topic NAME (incl. v3 decline/purpose); opening-phase situations
    become `who_rules` (incl. handoff); unknown topics are reported, never guessed;
  - `transfer.pre_verification_queues` (§11.2), `tools.<tool>` retry/on_fail (§11.5, defaults marked source=default),
    `hangup_default` slots (§11.3), `writes.notes.enabled` (§11.4);
  - default continue/safe lines; honesty words separated from disclosure words;
  - `unmapped` is never passed through: only rules stable across runs (consolidate_unmapped) become soft rules.
"""
import copy, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.engine.date_policy import _norm, validate
from builder.policy_extract import oas_summary

DEFAULT = [{"file": "default", "quote": ""}]
# Generic cue words per contract topic (vocabulary of a collections call, not values of any brief); matched on the
# topic NAME with word boundaries. Order matters: the first topic whose cue matches wins.
TOPIC_CUES = {"change_promise": ("(change|cancel|modify)( or (change|cancel|modify))? (the |a )?(recorded )?promise", "change (the )?(recorded )?promise", "change recorded promise", "modify (the )?promise",
                                 "cancel (the )?promise", "change promise"),
              "hardship":("hardship", "illness", "job loss", "bereavement", "death in the family"),
              "dispute": ("dispute", "not mine", "never had"),
              "paid": ("already paid", "paid"),
              "restructure": ("restructur\\w*", "payment plan", "lower instalments?"),
              "terms": ("discount", "waiver", "other terms", "terms"),   # after restructure: a plan request stays restructure
              "human": ("human", "person", "real agent"),
              "scam": ("scam", "fraud"),
              "robot": ("robot", "ai", "bot"),
              "unknown_info": ("unanswerable", "cannot answer", "unknown", "no information"),
              "stop": ("not want to talk", "dont want to talk", "don t want to talk", "stop talking", "stop"),
              "decline": ("declines? to answer", "refuses? to answer", "won t answer", "declines? identity",
                          "refuses? (the )?security questions?", "declines? (the )?security questions?",
                          "not want to answer", "refuses? identity", "decline"),
              "purpose": ("purpose", "what (is )?(this|the call|call) is about", "what (this|the call) is about",
                          "why (are you )?calling", "asks why"),
              "injection": ("injection", "ignore instructions")}
WHO_CUES = {"handoff": ("hand", "handoff", "passes the phone", "gets the customer"),
            "misdialled": ("wrong number",), "deceased": ("deceased", "died", "death of the customer"),
            "other": ("someone else", "third party", "relative"), "unclear": ("unclear", "ambiguous"),
            "busy": ("busy", "voicemail", "answering machine"),   # v3.1: callback or t=stop, closing slot `busy`
            "callback": ("callback",)}
# who_rules -> the contract vocabulary: who in {self, other, unclear, handoff, busy}; party in {relative,
# wrong_number, deceased} (contract §1.2 payload words); callback / no_callback live in `effect`, never in `who`.
WHO_VOCAB = ("self", "other", "unclear", "handoff", "busy")
PARTY_VOCAB = ("relative", "wrong_number", "deceased", "")
WHO_NORMAL = {"handoff": dict(who="handoff", party=""), "misdialled": dict(who="other", party="wrong_number"),
              "deceased": dict(who="other", party="deceased"), "other": dict(who="other", party="relative"),
              "unclear": dict(who="unclear", party=""), "busy": dict(who="busy", party=""),
              "callback": dict(who="other", party="relative", effect_kind="callback")}
OPENING = {"wrong_person": ("other", "relative"), "wrong_number": ("other", "wrong_number"), "deceased": ("other", "deceased"),
           "unclear": ("unclear", ""), "busy_voicemail": ("busy", ""), "handoff": ("handoff", "")}
V3_ALWAYS = ("decline", "purpose")          # §11.6: always present in the generated grammar
TOPIC_ORDER = ("hardship", "dispute", "paid", "restructure", "human", "scam", "robot", "unknown_info", "stop", "decline",
               "purpose", "change_promise", "terms")
# instruction prose that must never be spoken as a line (an extractor writing what to do instead of what to say)
INSTRUCTION = re.compile(r"\b(one (short )?sentence of|then offer|say that|tell the customer|close as|call `|offer to connect|"
                         r"do not argue|make no|ask (once|for)|explain once)\b", re.I)
# The fixed sentence keys every bridged policy carries (reducer interface); missing -> contract default or "" + note
FIXED_SENTENCES = ("confirm_who", "pay_today", "debt_intro", "id_fail", "no_other_terms", "change_in_app", "farewell",
                   "continue_line", "safe_repeat", "text_message", "recorded")
DEFAULT_SENTENCES = {"continue_line": "Go on, please.", "safe_repeat": "Sorry, could you say that again?"}
DEFAULT_HONESTY = ["recorded", "scheduled", "transferred", "booked", "confirmed"]
# §11.5 defaults (source=default); a brief value overrides where it states one
TOOL_DEFAULTS = {"verify_identity": {"retries": 1, "on_fail": "close(slot:unclear)"},
                 "get_account": {"retries": 1, "on_fail": "close(slot:unclear)"},
                 "create_promise": {"retries": 1, "on_fail": "close(slot:write_failed)"},
                 "schedule_callback": {"retries": 1, "on_fail": "close(slot:callback_failed)"},
                 "transfer_to_agent": {"retries": 1, "on_fail": "continue"},
                 "add_note": {"retries": 1, "on_fail": "skip"},
                 "close_call": {"retries": 0, "on_fail": "continue"}}


def _enum(oas, tool, field, response=False):
    e = oas.get(tool + (" (response)" if response else ""), {}).get(field)
    return e if isinstance(e, list) else None


def response_fields(oas_path, tool):
    """All property names in a tool's 200 response schema (nested), e.g. the account fields of each product."""
    d = json.load(open(oas_path)) if oas_path and os.path.exists(oas_path) else {}
    out = []

    def walk(s):
        if isinstance(s, dict):
            for k, v in (s.get("properties") or {}).items():
                out.append(k)
                walk(v)
            walk(s.get("items"))
    for path, ops in (d.get("paths") or {}).items():
        if path.strip("/").split("/")[-1] == tool:
            for op in ops.values():
                for resp in (op.get("responses") or {}).values():
                    walk(((resp.get("content") or {}).get("application/json") or {}).get("schema"))
    return out


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


def _alias(policy, field, value, enum):
    """An exact, SOURCED alias from the material (policy.aliases: [{field, brief_value, api_value, source}], e.g. a
    code-list row) that maps value onto an enum member. No fuzzy or closest-name mapping, ever."""
    for a in policy.get("aliases") or []:
        if (a.get("field") in (field, None) and str(a.get("brief_value")) == str(value) and a.get("api_value") in enum
                and any(isinstance(s, dict) and s.get("quote") and s.get("file") != "default" for s in a.get("source") or [])):
            return a["api_value"]
    return None


# Contract defaults (REDUCER-CONTRACT; the date-slice wording) used when the brief gives no exact wording.
CONTRACT_DATE_SAY = {("on_non_business_day", "say"): "<NAMED> is not a business day. The next business day is <DATE>. Could you pay on <DATE>?",
                     ("on_after_deadline", "say"): "The latest date I can record is <DEADLINE>. Could you pay on <DEADLINE>?",
                     ("on_vague", "say_ask"): "Which exact day would that be?",
                     ("on_vague", "say_final"): "Then I can offer <DEADLINE>, the latest date I can record. Could you pay on <DEADLINE>?",
                     ("on_before_earliest", "say"): "That date has already passed. Which day from today on would work for you?",
                     ("on_invalid", "say"): "Sorry, which exact date do you mean?"}
CONTRACT_SENTENCES = {"no_other_terms": "I am sorry, there are no other terms.", "change_in_app": "You can change it in the mobile app.",
                      "farewell": "Thank you, goodbye.", "recorded": "Your promise is recorded."}
# Generic instruction forms of a brief ("Say that you are ...", "Tell the customer to ...") -> the sentence they ask
# for, by a fixed grammatical rewrite of the brief's own words (no new wording).
DERIVE = {"debt_intro": (r"\bsay (?:that )?you are (calling from [^,;]+)", lambda m: "I am " + m.group(1)),
          "id_fail": (r"\btell (?:the customer|them) to (.+)$", lambda m: "Please " + m.group(1)),
          "change_in_app": (r"say (?:that )?they can (change .+)$", lambda m: "You can " + m.group(1)),
          # verbatim quoted questions in the brief (the words inside the quotes are kept exactly)
          "pay_today": (r"[\"“]([^\"”]*\bpay\b[^\"”]*\btoday\?)[\"”]", lambda m: m.group(1)),
          "confirm_who": (r"[\"“]([^\"”]*\{\w+\}[^\"”]*\?)[\"”]", lambda m: m.group(1))}


def _all_quotes(p, stable):
    out = []
    for _, src in _walk_sources(p):
        out += [s.get("quote") if isinstance(s, dict) else s for s in (src if isinstance(src, list) else [src])]
    out += [u.get("quote") for u in stable]
    out += [u.get("quote") for u in p.get("unmapped") or [] if isinstance(u, dict)]   # verbatim-checked quotes of this run
    return [q for q in out if q]


def _walk_sources(x):
    if isinstance(x, dict):
        if "source" in x:
            yield None, x["source"]
        for k, v in x.items():
            if k != "source":
                yield from _walk_sources(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk_sources(v)


def _map_sentence_keys(p):
    """Map the extractor's own sentence ids onto the fixed keys by the sentence's form (its text is kept verbatim)."""
    sent, notes = p.setdefault("sentences", {}), []
    forms = [("confirm_who", lambda t: re.search(r"\{\w+\}", t) and t.rstrip().endswith("?")),
             ("pay_today", lambda t: t.rstrip().endswith("?") and re.search(r"\bpay\b", t, re.I) and re.search(r"\btoday\b", t, re.I)),
             ("recorded", lambda t: not t.rstrip().endswith("?") and re.search(r"\b(recorded|saved|registered|logged)\b", t, re.I)),
             ("text_message", lambda t: not t.rstrip().endswith("?") and re.search(r"confirm", t, re.I)
              and re.search(r"\b(text|sms|email|message|sent|send|receive)\b", t, re.I)),
             ("farewell", lambda t: re.search(r"\b(goodbye|bye)\b", t, re.I))]
    used = {v.get("mapped_from") for v in sent.values() if isinstance(v, dict) and v.get("mapped_from")}
    used |= {k for k in FIXED_SENTENCES if isinstance(sent.get(k), dict) and sent[k].get("text")}
    for key, form in forms:
        if isinstance(sent.get(key), dict) and sent[key].get("text"):
            continue
        hits = [(k, v) for k, v in sent.items() if k not in FIXED_SENTENCES and k not in used and isinstance(v, dict)
                and v.get("text") and form(v["text"])]
        if hits:   # one extractor sentence fills one key only, so the same line is never spoken twice
            k, v = hits[0]
            sent[key] = dict(v, mapped_from=k)
            used.add(k)
            notes.append(f"sentence {key} <- extractor id {k!r}")
    return notes


def _derived_sentences(p, stable):
    notes, sent, quotes = [], p.setdefault("sentences", {}), None
    for sid, (pat, fn) in DERIVE.items():
        if sid in sent:
            continue
        quotes = quotes if quotes is not None else _all_quotes(p, stable)
        for q in quotes:
            for part in re.split(r"(?<=[.!?])\s+", q):
                m = re.search(pat, part.strip().strip('"'), re.I)
                if m:
                    txt = fn(m).strip()
                    txt = txt if txt.endswith((".", "!", "?")) else txt + "."
                    sent[sid] = {"text": txt, "verbatim": False, "max_times": 99,
                                 "source": [{"file": "derived", "quote": q}]}
                    break
            if sid in sent:
                break
    for sid, text in CONTRACT_SENTENCES.items():
        if sid not in sent:
            sent[sid] = {"text": text, "verbatim": True, "max_times": 99, "source": DEFAULT}
            notes.append(f"sentence {sid}: no brief wording, contract default used")
    return notes


def _date_templates(p):
    """A date-decision sentence is kept only if the brief gives that wording (its words, tokens aside, appear in a
    quote of the same section); otherwise the contract template replaces the extractor's own wording."""
    notes = []
    for (sec, key), default in CONTRACT_DATE_SAY.items():
        node = p.setdefault(sec, {})
        txt = node.get(key)
        quotes = [s.get("quote") if isinstance(s, dict) else s for s in node.get("source") or []]
        if txt:
            words = [w for w in re.split(r"<[A-Z]+>", txt) if w.strip()]
            if words and all(any(_norm(w) in _norm(q or "") for q in quotes) for w in words):
                continue
        node[key] = default
        if txt and txt != default:
            notes.append(f"{sec}.{key}: extractor wording replaced by the contract template")
    return notes


def to_reducer(policy, oas_path, stable_unmapped=None):
    oas = oas_summary(oas_path)
    p = copy.deepcopy(policy)
    mism, notes = [], []

    def resolve(path, value, field, enum):
        """-> the value to use, or None = BLOCKED. Exact OAS value, or an explicit sourced alias; else api_mismatch."""
        if not enum or value in enum:
            return value
        mapped = _alias(p, field, value, enum)
        mism.append({"policy_path": path, "value": value, "field": field, "oas_enum": enum,
                     "action": ("map_to:" + mapped) if mapped else "block"})
        return mapped

    # ---- products
    types = _enum(oas, "get_account", "products[].type", response=True)
    prod = p.setdefault("products", {})
    for k in ("floor_by_type", "naming_by_type"):
        m = {}
        for t, v in (prod.get(k) or {}).items():
            nt = _ptype(t)
            if types and nt not in types:
                nt = resolve(f"products.{k}.{t}", nt, "get_account.products[].type", types)
            if nt:
                m[nt] = v
        if k in prod:
            prod[k] = m
    acct_fields = response_fields(oas_path, "get_account")
    for t, tpl in (prod.get("naming_by_type") or {}).items():
        def repl(mo):
            words = mo.group(1).lower()
            # the account field the placeholder names: an OAS response field sharing its key words, else a slug
            keys = [k for k in re.findall(r"[a-z0-9]+", words) if len(k) > 2]
            hit = [f for f in acct_fields if any(k in f.lower() for k in keys)]
            return "{" + (hit[0] if hit else re.sub(r"\W+", "_", words).strip("_")) + "}"
        prod["naming_by_type"][t] = re.sub(r"<([^>]+)>", repl, str(tpl))
    # ---- closing: rows whose outcome is outside the enum (and has no sourced alias) are BLOCKED, never re-labelled
    cl = p.setdefault("closing", {})
    e_out = _enum(oas, "close_call", "outcome")
    table = cl.get("table") or []
    for i, r in enumerate(table):
        r["reason"] = r.get("reason") or None
        if e_out and r["outcome"] not in e_out:
            r["brief_outcome"] = r["outcome"]
            r["outcome"] = resolve(f"closing.table[{i}].outcome", r["outcome"], "close_call.outcome", e_out)
            r["blocked"] = r["outcome"] is None
    by_outcome = {}
    for r in table:
        if not r.get("blocked"):
            by_outcome.setdefault(r["outcome"], []).append(r["reason"])
    cl["reason_omitted_for"] = sorted(o for o, rs in by_outcome.items() if all(x is None for x in rs))
    live = [r for r in table if not r.get("blocked")]
    row = lambda *cues: next((r for r in live if r["reason"] and _match(re.sub(r"_", " ", r["reason"]), cues)), None)
    # closing slots the reducer refers to (v3.1 §13.1); a slot may be empty -> noted
    slots = {"unclear": row(*WHO_CUES["unclear"]), "declined": row("declin\\w*"), "id_failed": row("fail\\w*"),
             "busy": row("busy", "voicemail"), "callback_failed": row("no callback"),
             "write_failed": row("service\\w*", "error")}
    # promise / paid slots: reason-less rows told apart by their `when` text (a success row vs an already-paid row)
    nulls = [r for r in live if not r["reason"]]
    paid_row = next((r for r in nulls if re.search(r"\b(paid|settled|already)\b", str(r.get("when", "")) + " " + str(r["outcome"]), re.I)), None)
    promise_row = next((r for r in nulls if r is not paid_row and re.search(r"\b(promise|arrangement|recorded|saved|agreed)\w*", str(r.get("when", "")) + " " + str(r["outcome"]), re.I)), None) \
        or next((r for r in nulls if r is not paid_row), None)
    slots.update(promise=promise_row, paid=paid_row)
    cl["slots"] = {k: ({"outcome": v["outcome"], "reason": v["reason"]} if v else None) for k, v in slots.items()}
    # ---- identity: a required field outside the enum is BLOCKED; it is never skipped silently (safety rule 2)
    idn = p.setdefault("identity", {})
    e = _enum(oas, "verify_identity", "field")
    blocked = []
    for i, q in enumerate(idn.get("questions") or []):
        if e and q.get("field") not in e:
            mapped = resolve(f"identity.questions[{i}].field", q.get("field"), "verify_identity.field", e)
            if mapped:
                q["field"] = mapped
            else:
                q["blocked"] = True
                blocked.append(q.get("field"))
    if blocked:
        fail = idn.get("on_fail") or cl["slots"]["id_failed"] or cl["slots"]["unclear"]
        idn["blocked"] = {"fields": blocked, "action": "close", "close": fail,
                          "why": "the brief requires identity fields the tool API cannot verify; identity cannot pass"}
        notes.append(f"identity BLOCKED: {blocked} are not in verify_identity.field; the call closes on {fail} before any account fact")
    # ---- hang-up defaults (§11.3); before_who falls back to a defined row when the brief has no 'unclear' row
    before_who, src = slots["unclear"], DEFAULT
    if not before_who:
        before_who = slots["callback_failed"] or row("callback") or slots["busy"]
        notes.append("no 'unclear' row: hangup_default.before_who = " + (f"{before_who['outcome']}/{before_who['reason']}" if before_who else "NONE (reducer must end without close_call)"))
    declined = idn.get("on_decline") if (idn.get("on_decline") or {}).get("outcome") in (e_out or [(idn.get("on_decline") or {}).get("outcome")]) else slots["declined"]
    p["hangup_default"] = {
        # defined even when every opening-phase row is blocked: end the call without an explicit close_call
        "before_who": ({"outcome": before_who["outcome"], "reason": before_who["reason"]} if before_who
                       else {"outcome": None, "reason": None, "action": "end_without_close",
                             "why": "no usable not-reached row in the OAS enum"}),
        "before_verified": {"outcome": (declined or {}).get("outcome"), "reason": (declined or {}).get("reason")},
        "after_verified": "computed", "source": src}
    # ---- writes, transfer, tools
    w = p.setdefault("writes", {})
    tr = w.get("transfer") or {}
    e_q = _enum(oas, "transfer_to_agent", "queue")
    qmap = {}
    for sit, q in (tr.get("queue_map") or {}).items():
        v = resolve(f"writes.transfer.queue_map.{sit}", q, "transfer_to_agent.queue", e_q)
        if v:
            qmap[sit] = v
    pre = [v for i, q in enumerate(tr.get("pre_verification_queues") or [])
           if (v := resolve(f"writes.transfer.pre_verification_queues[{i}]", q, "transfer_to_agent.queue", e_q))]
    hr = p.get("human_request") or {}
    if hr.get("applies_before_verification") and hr.get("queue"):
        v = resolve("human_request.queue", hr["queue"], "transfer_to_agent.queue", e_q)
        if v and v not in pre:
            pre.append(v)
    # queue_map keys are contract topics (restructure, human, hardship); the brief's own labels are mapped by name
    qtopic = {}
    for label, q in qmap.items():
        kind, t = _topic_of({"topic": label})
        qtopic[t if kind == "topic" else label] = q
    if hr.get("queue") and "human" not in qtopic:
        v = resolve("human_request.queue", hr["queue"], "transfer_to_agent.queue", e_q)
        if v:
            qtopic["human"] = v
    p["transfer"] = {"queue_map": qtopic, "pre_verification_queues": pre,
                     "source": (hr.get("source") or []) + (w.get("source") or []) or DEFAULT}
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
            ev["note_reason"] = resolve(f"events[{i}].note_reason", nr, "add_note.reason", e_n) or ""
    tools = {}
    for tool, d in TOOL_DEFAULTS.items():
        tools[tool] = dict(d, fail_say="", source=DEFAULT)
    pr = w.get("promise") or {}
    if isinstance(pr.get("retries"), int):
        tools["create_promise"].update(retries=pr["retries"], fail_say=pr.get("fail_say", ""), source=w.get("source") or DEFAULT)
    if (p.get("multi_product") or {}).get("applies"):
        tools["create_promise"]["on_fail"] = "continue"   # multi-product: that product fails with a note, the call continues
    p["tools"] = tools
    # tool_args: the ONE table (computed by generator.arg_map) that both the generator (baked placeholders) and the
    # reducer (written w_<tool>_<OAS field> variables) read. customer_id is the call variable, not in the table.
    from builder.generator import CALL_VARS, arg_map, oas_tools
    ta = {}
    for tool, spec in oas_tools(oas_path).items():
        amap, unmapped_req, _ = arg_map(tool, spec)
        ta[tool] = {c: f for f, c in amap.items() if c not in CALL_VARS}
        for f in unmapped_req:
            mism.append({"policy_path": f"tool_args.{tool}", "value": f, "field": f"{tool}.body", "oas_enum": None,
                         "action": "block (no canonical role for this required OAS field)"})
    p["tool_args"] = ta
    # tool_results: where the reducer reads each fact in the tool responses (exact OAS response fields)
    from builder.oas_bindings import tool_results
    tr_, missing = tool_results(oas_path, p)
    p["tool_results"] = tr_
    for tool, fact in missing:
        mism.append({"policy_path": f"tool_results.{tool}.{fact}", "value": fact, "field": f"{tool}.response", "oas_enum": None,
                     "action": "block (no unique OAS response field for this fact)"})
    # ---- events onto the contract topics, brief order = precedence
    evs, who, unknown = [], [], []
    for ev in p.get("events") or []:
        kind, val = _topic_of(ev)
        if kind == "topic":
            evs.append(dict(ev, topic=val, brief_topic=ev.get("topic"), precedence=len(evs)))
        elif kind == "who":
            who.append(dict(ev, brief_topic=ev.get("topic"), **WHO_NORMAL[val]))
        else:
            unknown.append(ev.get("topic"))
    # a fixed topic checklist from the extractor (every contract topic answered) replaces the free event list
    tc = p.get("topic_checklist")
    if isinstance(tc, dict) and tc:
        order = [e_["topic"] for e_ in evs] + [t for t in TOPIC_ORDER if t not in [e_["topic"] for e_ in evs]]
        evs, absent = [], []
        for t in order:
            it = tc.get(t) or {}
            if t not in TOPIC_ORDER or t in [e_["topic"] for e_ in evs]:
                continue
            if not it.get("present"):
                absent.append(t)
                continue
            evs.append({"topic": t, "brief_topic": t, "precedence": len(evs), "say": it.get("say", ""), "effect": it.get("effect", ""),
                        "outcome": it.get("outcome") or "", "reason": it.get("reason") or "", "note_reason": it.get("note_reason") or "",
                        "source": it.get("source") or DEFAULT})
        p["topics_absent"] = absent
        for i, ev in enumerate(evs):   # the checklist's tool values go through the same exact-enum rule
            if ev.get("note_reason") and e_n and ev["note_reason"] not in e_n:
                ev["note_reason"] = resolve(f"topic_checklist.{ev['topic']}.note_reason", ev["note_reason"], "add_note.reason", e_n) or ""
            if ev.get("reason") and _enum(oas, "close_call", "reason") and ev["reason"] not in _enum(oas, "close_call", "reason"):
                ev["reason"] = resolve(f"topic_checklist.{ev['topic']}.reason", ev["reason"], "close_call.reason", _enum(oas, "close_call", "reason")) or ""
    for t in V3_ALWAYS:
        if not any(e_["topic"] == t for e_ in evs):
            evs.append({"topic": t, "brief_topic": None, "precedence": len(evs), "source": DEFAULT})
    # an event's `say` is speakable text: the brief's exact words (found in its own quotes) or empty, never effect prose
    for ev in evs:
        s_ = str(ev.get("say") or "").strip()
        quotes = " ".join(str(x.get("quote") if isinstance(x, dict) else x) for x in (ev.get("source") or []))
        if s_ and (_norm(s_.strip('"')) not in _norm(quotes) or INSTRUCTION.search(s_)):
            ev["say_dropped"], ev["say"] = s_, ""
    # outcomes/reasons carried by event and who rules are sent to close_call too: same enum rule, same block
    for coll, name in ((evs, "events"), (who, "who_rules")):
        for i, ev in enumerate(coll):
            o = ev.get("outcome")
            if o and e_out and o not in e_out:
                ev["brief_outcome"], ev["outcome"] = o, resolve(f"{name}[{i}].outcome", o, "close_call.outcome", e_out)
                ev["blocked"] = ev["outcome"] is None
                if ev["outcome"] is None:
                    ev.pop("outcome")
    # opening situations: a fixed checklist from the extractor (all six ids answered) beats the events-derived set
    os_ = p.get("opening_situations")
    if isinstance(os_, dict) and os_:
        who, checklist = [], {}
        for sid, (wv, party) in OPENING.items():
            it = os_.get(sid) or {}
            checklist[sid] = bool(it.get("present"))
            if not it.get("present"):
                continue
            rule = {"who": wv, "party": party, "brief_topic": sid, "say": it.get("say", ""), "source": it.get("source") or DEFAULT,
                    "effect_kind": {"callback": "callback"}.get(it.get("effect"), "") or ("no_callback" if "no_callback" in str(it.get("reason")) else "")}
            o, r = it.get("outcome"), it.get("reason")
            if o:
                ov = resolve(f"opening_situations.{sid}.outcome", o, "close_call.outcome", e_out) if e_out else o
                if ov:
                    rule["outcome"] = ov
                else:
                    rule["blocked"], rule["brief_outcome"] = True, o
            if r:
                rule["reason"] = r
            who.append(rule)
        p["who_checklist"] = checklist
    p["events"], p["who_rules"] = evs, who
    if unknown:
        notes.append(f"event topics with no contract topic (kept out of the reducer, for review): {unknown}")
    # ---- sentences, honesty, free talk
    sent = p.setdefault("sentences", {})
    for sid, text in DEFAULT_SENTENCES.items():
        sent.setdefault(sid, {"text": text, "verbatim": True, "max_times": 99, "source": DEFAULT})
    notes += _map_sentence_keys(p)
    notes += _derived_sentences(p, stable_unmapped or [])
    for sid in FIXED_SENTENCES:
        if sid not in sent:
            sent[sid] = {"text": "", "verbatim": True, "max_times": 99, "source": DEFAULT}
            notes.append(f"sentence {sid}: the brief has none; empty (the reducer's fallback applies)")
    for w in p.get("who_rules") or []:   # callback / no_callback rows carry the effect, never a who value
        if re.search(r"\bno.?callback\b", json.dumps(w).lower()):
            w["effect_kind"] = "no_callback"
        elif "callback" in json.dumps(w).lower() and not w.get("effect_kind"):
            w["effect_kind"] = "callback"
    notes += _date_templates(p)
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
