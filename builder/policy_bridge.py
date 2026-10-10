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
CONTRACT_SENTENCES = {"change_in_app": "You can change it in the mobile app.",   # no_other_terms: brief wording only (else "")
                      "farewell": "Thank you, goodbye.", "recorded": "Your promise is recorded."}
# Generic instruction forms of a brief ("Say that you are ...", "Tell the customer to ...") -> the sentence they ask
# for, by a fixed grammatical rewrite of the brief's own words (no new wording).
DERIVE = {"debt_intro": (r"\bsay (?:that )?you are (calling (?:from|about) [^,;]+)", lambda m: "I am " + m.group(1)),
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


_SAY = re.compile(r"\b(?:say|tell (?:the customer|them|the caller))(?: that)? (.+)$", re.I)
_OFFER = re.compile(r"\boffer to (connect (?:them|the customer) with .+)$", re.I)
_CUT = re.compile(r"\s*(?:[,;.]|\band (?:then |also )?(?:continue|close|take|call|ask|make|do not|end|offer)\b|\bthen\b|\(rule)", re.I)


def _person(text):
    """Third-person brief wording -> what the agent says to the customer (fixed word swaps only)."""
    t = " " + text.strip() + " "
    # in "say (that) X", a leading "you" is the agent itself; "they/them/their" is the customer
    t = re.sub(r"^ you are ", " I am ", t, flags=re.I)
    t = re.sub(r"^ you ", " I ", t, flags=re.I)
    for a, b in ((" the agent is ", " I am "), (" they can ", " you can "), (" they are ", " you are "),
                 (" their ", " your "), (" them ", " you "), (" the customer's ", " your "), (" the customer can ", " you can "),
                 (" the customer is ", " you are "), (" the customer has ", " you have "), (" the customer ", " you ")):
        t = re.sub(a, b, t, flags=re.I)
    t = t.strip()
    return t[:1].upper() + t[1:] if t else t


def speakable(quotes):
    """Rule-based rewrite of a brief instruction into the line it asks for: 'say (that) X' / 'tell the customer (that) X'
    -> X in the first person; 'offer to connect them with Y' -> 'Would you like me to connect you with Y?'. The content
    words stay the quote's own. Returns '' when no rule applies safely (the contract default is used instead)."""
    for q in quotes:
        for part in re.split(r"(?<=[.!?])\s+", str(q)):
            part = part.strip().strip('"')
            m = _SAY.search(part)
            if m and not re.match(r"(one|a) (short )?sentence|goodbye|thank", m.group(1), re.I):
                x = _CUT.split(m.group(1).strip().strip('"“”'), maxsplit=1)[0].strip().strip('"“”')
                if 3 <= len(x.split()) <= 30 and "`" not in x:
                    line = _person(x)
                    line = line if line.endswith((".", "?", "!")) else line + "."
                    if not INSTRUCTION.search(line):
                        return line
            m = _OFFER.search(part)
            if m:
                x = _CUT.split(m.group(1).strip(), maxsplit=1)[0].strip()
                if 3 <= len(x.split()) <= 20 and "`" not in x:
                    return "Would you like me to " + _person(x)[0].lower() + _person(x)[1:] + "?"
    return ""


# ---- gap 1: required sentences as hooks with timing ------------------------------------------------------------
HOOK_POINTS = ("opening", "after_debt", "on_refusal", "on_no_promise", "before_close", "on_promise_recorded")
_HOOK_VERB = re.compile(r"\b(?:say|tell|inform|warn|remind|mention|disclose|explain|state)"
                        r"(?: (?:the customer|the caller|the person|the policyholder|customers|them|him|her))?(?: (that))? (.+)$", re.I)
_TELL_TO = re.compile(r"\btell (?:the customer|the caller|the person|the policyholder|them|him|her) to ([^.;]+)", re.I)
# a quote tied to a situation (if/when/after/below ... or a 'Situation:' label): its line belongs to that situation
_SITUATIONAL = re.compile(r"\b(if|when|whenever|after|before|below|above|unless|once|until|while|during|instead|otherwise)\b|^[^.:]{2,60}:|`", re.I)
_QUOTED = re.compile(r"[\"“]([^\"”]{6,}?[.?!])[\"”]")
_NOT_A_LINE = re.compile(r"^(nothing|no |not |why |it\b|so\b|this sentence|one (short )?sentence|a sentence|goodbye|"
                         r"thank|the past.due|how many|the product|the amount|the debt)", re.I)


def hook_lines(quote):
    """The spoken line(s) a say/tell/warn rule asks for, by a fixed rewrite of the rule's own words (no paraphrase):
    a quoted sentence is kept verbatim; 'say (that) A, and that B' -> 'A. B.' in the first person. '' when no rule
    applies safely (the hook is then unplaced)."""
    q = str(quote or "").strip()
    m = re.search(r"\bthank (?:the customer|them|the caller) for ([^.;]+)", q, re.I)
    if m and 2 <= len(m.group(1).split()) <= 15:     # 'thank the customer for X' -> 'Thank you for X.'
        return "Thank you for " + _person(m.group(1))[0].lower() + _person(m.group(1))[1:].rstrip(".") + "."
    m = _TELL_TO.search(q)
    if m and 2 <= len(m.group(1).split()) <= 20 and "`" not in m.group(1):
        return "Please " + m.group(1).strip().rstrip(".") + "."
    quoted = _QUOTED.findall(q)
    if quoted and re.search(r"\b(say|ask|tell|read|use|sentence|line|words?)\b", q, re.I):
        return " ".join(x.strip() for x in quoted)
    out = []
    for part in re.split(r"(?<=[.!?])\s+", q):
        m = _HOOK_VERB.search(part.strip().strip('"'))
        if not m:
            continue
        verb_that, body = m.group(1), m.group(2).strip().strip('"“”')
        verb = re.match(r"\w+", m.group(0)).group(0).lower()
        if verb in ("state", "explain", "mention", "disclose") and not verb_that:
            continue             # "state the past-due amount" is an action, not a line
        for clause in re.split(r",? and that ", body):
            x = _CUT.split(clause.strip(), maxsplit=1)[0].strip().strip('"“”')
            if not (3 <= len(x.split()) <= 30) or "`" in x or _NOT_A_LINE.search(x):
                continue
            line = _person(x)
            line = line if line.endswith((".", "?", "!")) else line + "."
            if not INSTRUCTION.search(line):
                out.append(line)
    return " ".join(out)


def _hook_condition(cond, p, types):
    """-> (condition string 'k=v;k=v' or None, problem or None). Closed set of keys: band, product_type, outcome (the
    reducer's grammar: terms joined by ';', all must hold). The extractor may give a dict or such a string."""
    if not cond:
        return None, None
    if isinstance(cond, dict):
        terms = list(cond.items())
    else:
        terms = [tuple(x.split("=", 1)) for x in re.split(r"[;,&]", str(cond)) if x.strip()]
        if any(len(t) != 2 for t in terms):
            return None, f"condition {cond!r} is not key=value terms"
    names = [b.get("name") for b in (p.get("deadline") or {}).get("bands") or []]
    outs = {r.get("outcome") for r in (p.get("closing") or {}).get("table") or []}
    out = []
    for k, v in terms:
        k, v = str(k).strip(), str(v).strip()
        if k == "band" and v not in names:
            return None, f"band {v!r} is not a deadline band {names}"
        if k == "product_type":
            v = _ptype(v)
            if types and v not in types:
                return None, f"product type {v!r} not in the OAS enum"
        if k == "outcome" and v not in outs:
            return None, f"outcome {v!r} is not in closing.table"
        if k not in ("band", "product_type", "outcome"):
            return None, f"condition key {k!r} is not one of band / product_type / outcome"
        out.append(f"{k}={v}")
    return ";".join(out), None


def _reducer_lines():
    """The contract-default lines the reducer itself speaks (its module-level D_* strings, read-only): a hook that only
    repeats one of them is a duplicate."""
    try:
        from builder.engine import reducer as _r
    except Exception:
        return set()
    return {_norm(v) for k, v in vars(_r).items() if k.startswith("D_") and isinstance(v, str) and "<" not in v and "{" not in v}


def build_hooks(p, types):
    """policy.hooks (extractor: point, condition, quote) -> (hooks, unplaced, notes). A hook keeps the point the material
    gives; an unsure or invalid point, an invalid condition, or no speakable rewrite -> unplaced (never moved). A hook
    whose line is already spoken by a fixed sentence, an event or a date line is dropped as a duplicate."""
    spoken, src_quotes = set(), set()
    for k, v in (p.get("sentences") or {}).items():
        if isinstance(v, dict) and k in FIXED_SENTENCES:     # only the keys the reducer speaks
            spoken.add(_norm(v.get("text") or ""))
            src_quotes |= {_norm(s.get("quote") or "") for s in v.get("source") or [] if isinstance(s, dict)}
    for r in (p.get("date_rules") or {}).values():     # a date-refusal line is spoken by the date decision itself
        if isinstance(r, dict) and r.get("say"):
            spoken.add(_norm(r["say"]))
            src_quotes |= {_norm(s.get("quote") or "") for s in r.get("source") or [] if isinstance(s, dict)}
    for ev in (p.get("events") or []) + list(((p.get("topic_checklist") or {}).values())):
        if isinstance(ev, dict) and ev.get("say"):
            spoken.add(_norm(ev["say"]))
    spoken |= _reducer_lines()
    spoken.discard("")
    src_quotes.discard("")
    hooks, unplaced, notes = [], [], []
    for i, h in enumerate(p.get("hooks") or []):
        if not isinstance(h, dict):
            continue
        quote = _first_quote(h)
        hid = str(h.get("id") or f"hook_{i + 1}")
        text = hook_lines(quote)
        cond, problem = _hook_condition(h.get("condition"), p, types)
        point = h.get("point")
        item = {"id": hid, "point": point, "condition": cond, "text": text,
                "expects_answer": bool(h.get("expects_answer")) or text.rstrip().endswith("?"), "quote": quote,
                "source": h.get("source") or []}
        if _norm(text) in spoken or (_norm(quote) in src_quotes and not point == "opening"):
            notes.append(f"hook {hid}: already spoken by a sentence or an event line, dropped")
            continue
        if point in ("unsure", None, "") and text and not cond and not problem and not item["expects_answer"] \
                and not _SITUATIONAL.search(quote):
            item["point"], point = "before_close", "before_close"   # a timeless statement: said once, in the goodbye
            item["placed"] = "no moment given"
            notes.append(f"hook {hid}: placed at before_close (no moment given): {text[:60]!r}")
        why = (None if point in HOOK_POINTS else f"point {point!r} is not a known moment") or problem \
            or (None if text else "no speakable rewrite of the quote")
        if why:
            unplaced.append(dict(item, why=why))
            continue
        if any(x["point"] == point and x["text"] == text and x["condition"] == cond for x in hooks):
            continue
        hooks.append(item)
    return hooks, unplaced, notes


_REC_CLAUSE = re.compile(r"\b((?:the|this|all|our|every) (?:calls?|conversations?) (?:is|are|will be|may be)"
                         r" (?:being )?recorded(?: for [a-z ]+)?)", re.I)
_OPENING_CUE = re.compile(r"first (?:sentence|thing|words?|line)|opening|greet\w*|introduc\w*|start of (?:the |each |every )?call|at the start", re.I)


def recording_hook(p, stable, hooks, unplaced):
    """The opening must carry the recording clause when the brief requires it: if no opening hook says it, a quote that
    puts 'the call is recorded' into the opening gives it (only the recording clause of that quote). -> note or None."""
    if any(h["point"] == "opening" and re.search(r"\brecord", h["text"], re.I) for h in hooks):
        return None
    for q in _all_quotes(p, stable) + [u["quote"] for u in unplaced]:
        if re.search(r"\brecord(?:ed|ing)\b", q, re.I) and re.search(r"\b(call|conversation)\b", q, re.I) and _OPENING_CUE.search(q):
            lines = [x for x in re.split(r"(?<=[.!?])\s+", hook_lines(q)) if re.search(r"\brecord", x, re.I)]
            if not lines:   # verbless form ("First sentence: ..., and the call is recorded"): the clause itself
                m = _REC_CLAUSE.search(q)
                lines = [m.group(1)[0].upper() + m.group(1)[1:].rstrip() + "."] if m else []
            if lines:
                hooks.append({"id": "recording_notice", "point": "opening", "condition": None, "text": " ".join(lines),
                              "expects_answer": " ".join(lines).endswith("?"), "quote": q,
                              "source": [{"file": "derived", "quote": q}]})
                unplaced[:] = [u for u in unplaced if u["quote"] != q]
                return f"hook recording_notice: the opening carries the recording clause of {q[:70]!r}"
    return None


# ---- gap 2: identity answer formats ---------------------------------------------------------------------------------
FORMATS = re.compile(r"^(date|digits\(\d+\)|name|alnum|postcode|free)$")
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def answer_format(q, oas_text=""):
    """identity question -> (format in {date, digits(n), name, alnum, postcode, free}, how). The extractor's value is
    kept when it is already one of them; otherwise a fixed reading of its own words, the question and the OAS text."""
    f = str(q.get("format") or "").strip().lower()
    said = " ".join([f, str(q.get("format_brief") or "")] + [str(s_.get("quote") if isinstance(s_, dict) else s_)
                    for s_ in ((q.get("format_evidence") or {}).get("source") or [])])
    if re.search(r"\bexactly as (?:the customer |they |he |she )?(?:said|says|given|gave|spoken|heard)", said, re.I):
        return "free", "exactly as said"          # the brief's own instruction wins over any format inference
    if FORMATS.match(f):
        return f, "extractor"
    own = " ".join(str(q.get(k) or "") for k in ("format", "brief_name", "ask", "field")).lower().replace("_", " ")
    got = _format_words(own)
    if got == "free" and oas_text:      # the brief's own words first; the OAS text only when they say nothing
        got = _format_words(oas_text.lower())
        return got, ("oas" if got != "free" else "default")
    return got, ("words" if got != "free" else "default")


def _format_words(s):
    if re.search(r"\bpost ?codes?\b|\bzip\b", s):
        return "postcode"
    m = re.search(r"\b(\d+|" + "|".join(_NUM) + r")\s+(?:\w+\s+)?digits?\b", s)
    if m:
        n = m.group(1)
        return f"digits({int(n) if n.isdigit() else _NUM[n]})"
    if re.search(r"\byyyy\b(?!-mm)|\byear\b(?! *-?mm)", s) and not re.search(r"yyyy-mm-dd|date of birth", s):
        return "digits(4)"
    if re.search(r"yyyy-mm-dd|\bdate\b|\bbirthday\b", s):
        return "date"
    if re.search(r"alphanumeric|letters and digits|letters and numbers|\bcharacters?\b|reference|\bcode\b", s):
        return "alnum"
    if re.search(r"\bname\b|maiden|\bcity\b|\btown\b|place of birth", s):
        return "name"
    return "free"


def _oas_answer_text(oas_path):
    try:
        d = json.load(open(oas_path))
    except Exception:
        return ""
    for path, ops in (d.get("paths") or {}).items():
        if path.strip("/").endswith("verify_identity"):
            for op in ops.values():
                s = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
                return " ".join(str((v or {}).get("description") or "") for v in (s.get("properties") or {}).values())
    return ""


# ---- gap 3: floor and acceptance ------------------------------------------------------------------------------------
FLOOR_KINDS = ("field", "percent", "fixed", "max_fixed_percent")
ACCEPTANCE = ("floor_to_full", "full_only", "above_full_allowed")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def floor_spec(v, acct_fields):
    """One floor_by_type entry (extractor, old or new shape) -> (Fork 3's flat rule, problem). Shapes:
    {kind: field, field} | {kind: percent, percent, round, to} | {kind: fixed, amount} |
    {kind: max_fixed_percent, amount, percent, round, to}. Old kinds account_field / percent_of_past_due are read."""
    if not isinstance(v, dict):
        return None, f"floor {v!r} is not a rule"
    prm = dict(v.get("params") or {}, **{k: x for k, x in v.items() if k != "params"})
    kind = {"account_field": "field", "percent_of_past_due": "percent"}.get(prm.get("kind"), prm.get("kind"))
    rnd = prm.get("round") or (prm.get("rounding") or {}).get("mode") if isinstance(prm.get("rounding"), dict) else prm.get("round")
    to = prm.get("to") or ((prm.get("rounding") or {}).get("to") if isinstance(prm.get("rounding"), dict) else None)
    to = {0.01: "cent", "0.01": "cent", 1: "unit", "1": "unit", 1.0: "unit"}.get(to, to)
    out = {"kind": kind, "source": v.get("source") or DEFAULT}
    if kind == "field":
        f = prm.get("field")
        if not f:
            return None, "floor kind field without a field"
        if acct_fields and f not in acct_fields:
            return None, f"floor field {f!r} is not an account field of the OAS get_account response"
        out["field"] = f
    elif kind in ("percent", "max_fixed_percent", "fixed"):
        if kind != "fixed":
            pct = _num(prm.get("percent"))
            if pct is None or not 0 < pct <= 100:
                return None, f"floor percent {prm.get('percent')!r} is not in (0, 100]"
            out["percent"] = pct
            if rnd in ("up", "down", "nearest"):
                out["round"] = rnd
            if to in ("cent", "unit"):
                out["to"] = to
        if kind != "percent":
            amt = _num(prm.get("amount"))
            if amt is None or amt <= 0:
                return None, f"floor amount {prm.get('amount')!r} is not a positive number"
            out["amount"] = amt
    else:
        return None, f"floor kind {kind!r} is not one of {FLOOR_KINDS}"
    return out, None


def acceptance_rule(a):
    """amounts.acceptance -> Fork 3's value ('floor_to_full' | 'full_only' | 'above_full_allowed' | {kind: min_x, min})
    and a note, or (None, problem)."""
    if a in (None, "", {}):
        return "floor_to_full", "amounts.acceptance not stated: floor_to_full (contract default)"
    if isinstance(a, dict):
        kind, mn = a.get("kind"), _num(a.get("min"))
        if kind == "min_x":
            return ({"kind": "min_x", "min": mn}, None) if mn is not None and mn > 0 else (None, f"min_x without a positive min: {a!r}")
        a = kind
    return (a, None) if a in ACCEPTANCE else (None, f"acceptance {a!r} is not one of {ACCEPTANCE + ('min_x',)}")


# ---- gap 4: date refusal policy ------------------------------------------------------------------------------------
DATE_SITUATIONS = ("weekend", "holiday", "after_deadline", "today_not_allowed", "past")
DATE_ACTIONS = ("shift_next_business_day", "shift_previous_business_day", "offer_deadline", "refuse")
_LEGACY_ACTION = {"next_business_day": "shift_next_business_day", "previous_business_day": "shift_previous_business_day",
                  "reject": "refuse", "offer_deadline": "offer_deadline"}


def _brief_worded(text, quotes):
    """A sentence is the brief's own when its words (tokens aside) are in the quotes; else it is the extractor's."""
    words = [w for w in re.split(r"<[A-Z]+>", str(text or "")) if w.strip(" .,?")]
    return bool(words) and all(_norm(w.strip()) in _norm(" ".join(quotes)) for w in words) and not INSTRUCTION.search(text)


_EXPLICIT_REFUSE = re.compile(r"\b(refus\w*|reject\w*|not (?:be )?accept\w*|cannot (?:be )?(?:record|accept)\w*|"
                              r"not allowed|is not possible|decline\w*|do not record)\b", re.I)
_SHIFT_LINE = re.compile(r"next business day|next working day|<DATE>", re.I)
_UNSTATED = {"weekend": "shift_next_business_day", "holiday": "shift_next_business_day", "after_deadline": "offer_deadline"}


def date_rules(p):
    """-> (date_rules {situation: {action, say?, source}}, notes). The extractor's date_rules first; a situation it does
    not answer comes from the legacy sections (on_non_business_day for weekend and holiday, on_after_deadline,
    earliest.allow_today, past = refuse). A say is kept only when the brief words it; else omitted (reducer default)."""
    ext = p.get("date_rules") if isinstance(p.get("date_rules"), dict) else {}
    nbd, aft, ear = p.get("on_non_business_day") or {}, p.get("on_after_deadline") or {}, p.get("earliest") or {}
    legacy = {"weekend": nbd, "holiday": nbd, "after_deadline": aft}
    out, notes = {}, []
    for sit in DATE_SITUATIONS:
        e = ext.get(sit) if isinstance(ext.get(sit), dict) else {}
        q = [str(x.get("quote") if isinstance(x, dict) else x) for x in (e.get("source") or [])]
        act = e.get("action") if e.get("action") in DATE_ACTIONS else None
        how = "extractor"
        if not act or not q:
            sec = legacy.get(sit)
            if sec is not None and _LEGACY_ACTION.get(sec.get("action")):
                act, q, e, how = _LEGACY_ACTION[sec["action"]], [str(x.get("quote") if isinstance(x, dict) else x) for x in sec.get("source") or []], {"say": sec.get("say"), "source": sec.get("source")}, "legacy"
            elif sit == "today_not_allowed":
                if ear.get("allow_today") is not False:
                    continue        # today is allowed: no rule for this situation
                act, q, e, how = act or "refuse", [str(x.get("quote") if isinstance(x, dict) else x) for x in ear.get("source") or []], {"source": ear.get("source")}, "legacy"
            elif sit == "past":
                act, how = act or "refuse", "contract default"
            elif not act:
                notes.append(f"date_rules.{sit}: no rule in the material")
                continue
        if act == "refuse" and sit in _UNSTATED and not any(_EXPLICIT_REFUSE.search(x) for x in q):
            notes.append(f"date_rules.{sit}: refuse with no explicit refusal in the material -> {_UNSTATED[sit]} (legacy behaviour)")
            act, how = _UNSTATED[sit], how + "+unstated"
        rule = {"action": act, "source": e.get("source") or DEFAULT, "from": how}
        say = str(e.get("say") or "").strip()
        if act == "refuse" and _SHIFT_LINE.search(say):
            say = ""            # a shift line is never paired with a refusal
        if say and _brief_worded(say, q):
            rule["say"] = say
        elif say and say not in CONTRACT_DATE_SAY.values():
            notes.append(f"date_rules.{sit}.say {say[:50]!r} is not the brief's wording: omitted (reducer default)")
        out[sit] = rule
    # the date core reads the legacy section: keep it consistent with the weekend rule (a shift is never a reject)
    if nbd.get("action") == "reject" and (out.get("weekend") or {}).get("action") == "shift_next_business_day":
        nbd["action"] = "next_business_day"
        notes.append("on_non_business_day.action reject -> next_business_day (no explicit refusal in the material)")
    return out, notes


_CB_REASON = re.compile(r"\bcall.?back\b", re.I)
_NO_CB_REASON = re.compile(r"\bno.?call.?back\b", re.I)


def callback_who_rules(p):
    """The effect of a who row comes from its reason / effect, never from words anywhere in its quote: no_callback when
    the reason says no callback, callback when the reason or effect says callback. A relative row in a brief with a
    callback window and a callback row in closing.table books a callback and carries that row's reason (an extraction
    that left the reason empty, or quoted another rule, must not close with no reason). -> notes"""
    notes = []
    live = [r for r in (p.get("closing") or {}).get("table") or [] if not r.get("blocked") and r.get("reason")]
    cb = next((r for r in live if _CB_REASON.search(str(r["reason"])) and not _NO_CB_REASON.search(str(r["reason"]))), None)
    cbw = (p.get("writes") or {}).get("callback") or {}
    window = bool(cbw.get("start") and cbw.get("end"))
    for w in p.get("who_rules") or []:
        r = str(w.get("reason") or "")
        if _NO_CB_REASON.search(r):
            w["effect_kind"] = "no_callback"
        elif _CB_REASON.search(r) or w.get("effect_kind") == "callback":
            w["effect_kind"] = "callback"
        else:
            w["effect_kind"] = "" if w.get("effect_kind") in ("callback", "no_callback") else w.get("effect_kind", "")
        if w.get("party") == "relative" and window and cb and (w.get("effect_kind") != "callback" or not w.get("reason")):
            notes.append(f"who relative: {w.get('outcome')}/{w.get('reason')} -> callback {cb['outcome']}/{cb['reason']} (callback window + callback row)")
            w.update(effect_kind="callback", outcome=cb["outcome"], reason=cb["reason"])
        if w.get("effect_kind") == "callback" and not w.get("reason") and cb:
            w.update(outcome=cb["outcome"], reason=cb["reason"])
    return notes


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
            nt = "*" if str(t).strip() in ("*", "any", "all") else _ptype(t)
            if types and nt not in types and nt != "*":
                nt = resolve(f"products.{k}.{t}", nt, "get_account.products[].type", types)
            if nt:
                m[nt] = v
        if k in prod:
            prod[k] = m
    acct_fields = response_fields(oas_path, "get_account")
    floors = {}
    for t, v in (prod.get("floor_by_type") or {}).items():
        rule, problem = floor_spec(v, acct_fields)
        if rule:
            floors[t] = rule
        else:
            mism.append({"policy_path": f"products.floor_by_type.{t}", "value": v.get("field") if isinstance(v, dict) else v,
                         "field": "get_account.products[]", "oas_enum": None,
                         "action": f"block ({problem}; the floor is the full amount)"})
    prod["floor_by_type"] = floors
    am = p.setdefault("amounts", {})
    acc, anote = acceptance_rule(am.get("acceptance"))
    am["acceptance"] = acc or "floor_to_full"
    if anote:
        notes.append(anote if acc else f"amounts.acceptance: {anote}; floor_to_full used")
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
    oas_txt = re.split(r"(?<=[.;])\s+", _oas_answer_text(oas_path))
    for q in idn.get("questions") or []:
        words = [w for w in re.findall(r"[a-z]+", str(q.get("field") or "").lower()) if len(w) > 2]
        own = " ".join(s_ for s_ in oas_txt if words and any(w in s_.lower() for w in words))
        q["format_brief"], (q["format"], how) = q.get("format"), answer_format(q, own)
        q["format_how"] = how
        q.setdefault("format_evidence", {"source": DEFAULT})
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
            # an extra situation of the brief: recorded with its quote for review, never a close by default
            p.setdefault("unmapped_topics", []).append({"topic": ev.get("topic"), "quote": _first_quote(ev),
                                                        "effect": ev.get("effect", ""), "action": "none (out of scope)"})
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
    for ev in evs + who:
        s_ = str(ev.get("say") or "").strip()
        quotes = [str(x.get("quote") if isinstance(x, dict) else x) for x in (ev.get("source") or [])]
        if s_ and (_norm(s_.strip('"')) not in _norm(" ".join(quotes)) or INSTRUCTION.search(s_)):
            ev["say_dropped"], ev["say"] = s_, ""
        if not ev.get("say"):
            line = speakable(quotes)
            if line:
                ev["say"], ev["say_rewritten_from"] = line, True
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
    notes += callback_who_rules(p)
    notes += _date_templates(p)
    p["date_rules"], dnotes = date_rules(p)
    notes += dnotes
    hooks, unplaced, hnotes = build_hooks(p, types)
    rec = recording_hook(p, stable_unmapped or [], hooks, unplaced)
    hnotes += [rec] if rec else []
    p["hooks"], p["unplaced_hooks"] = hooks, unplaced
    notes += hnotes + [f"hook {u['id']} UNPLACED ({u['why']}): {u['quote'][:80]!r}" for u in unplaced]
    words =[x.lower() for x in (p.get("honesty_words") or {}).get("words") or []]
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
