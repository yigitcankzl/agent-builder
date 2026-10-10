"""Date policy: the brief-driven input of the date engine, and its validator.

Schema (every rule section carries `source`: exact quotes from the brief, checked against the brief text):
{
  "now":        {"var": "now", "source": [...]},                       runtime "today" comes from this call variable
  "business_days": {"weekdays": [0..6], "holidays": ["YYYY-MM-DD"], "source": [...]},
  "deadline":   {"rule": "business_days_after_today" | "calendar_days_after_today",
                 "bands": [{"name": str, "max_days_late": int, "days": int}], "source": [...]},
  "earliest":   {"allow_today": bool, "source": [...]},
  "on_non_business_day": {"action": "next_business_day" | "previous_business_day" | "reject", "say": str, "source": [...]},
  "on_after_deadline":   {"action": "offer_deadline" | "reject", "say": str, "source": [...]},
  "on_vague":   {"asks": int, "then": "offer_deadline" | "ask_again", "say_ask": str, "say_final": str, "source": [...]},
  "on_before_earliest": {"say": str},  "on_invalid": {"say": str},  "on_ok": {"say": ""},
  "weekday_words": {"next": "following_week" | "next_occurrence", "rule": str, "source": [...]}   optional
  "inputs":     {"iso_var": "date_iso", "spec_var": "date_spec", "products_var", "current_product_var", "product_id_field",
                 "days_late_field", "days_late_var"}
}
Sentences may use <NAMED>, <DATE> (the date offered or accepted) and <DEADLINE>.
"""
import datetime, re

ACTIONS = {"on_non_business_day": {"next_business_day", "previous_business_day", "reject"},
           "on_after_deadline": {"offer_deadline", "reject"}}
RULED = ("now", "business_days", "deadline", "earliest", "on_non_business_day", "on_after_deadline", "on_vague")


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[*_`|]", "", s)).strip().lower()


def validate(policy, brief_text=None):
    """-> list of problems (empty = valid). With brief_text, every source quote must appear in it."""
    errs = []
    for k in RULED + ("inputs",):
        if not isinstance(policy.get(k), dict):
            errs.append(f"missing section {k}")
    if errs:
        return errs
    bd = policy["business_days"]
    if not bd.get("weekdays") or not all(isinstance(w, int) and 0 <= w <= 6 for w in bd["weekdays"]):
        errs.append("business_days.weekdays must be ints 0..6 (Monday=0)")
    for h in bd.get("holidays", []):
        try:
            datetime.date.fromisoformat(h)
        except (TypeError, ValueError):
            errs.append(f"holiday {h!r} is not YYYY-MM-DD")
    dl = policy["deadline"]
    if dl.get("rule", "business_days_after_today") not in ("business_days_after_today", "calendar_days_after_today"):
        errs.append("deadline.rule unknown")
    if not dl.get("bands") or not all(isinstance(b.get("max_days_late"), int) and isinstance(b.get("days"), int) and b["days"] >= 0
                                      for b in dl["bands"]):
        errs.append("deadline.bands need int max_days_late and days")
    for sec, allowed in ACTIONS.items():
        if policy[sec].get("action") not in allowed:
            errs.append(f"{sec}.action must be one of {sorted(allowed)}")
    if policy["on_vague"].get("then") not in ("offer_deadline", "ask_again"):
        errs.append("on_vague.then must be offer_deadline or ask_again")
    if not policy["now"].get("var"):
        errs.append("now.var is required")
    for sec, sv in policy.items():
        if isinstance(sv, dict):
            for key, val in sv.items():
                if key.startswith("say") and isinstance(val, str):
                    bad = set(re.findall(r"<[A-Z_]+>", val)) - {"<NAMED>", "<DATE>", "<DEADLINE>"}
                    if bad:
                        errs.append(f"{sec}.{key} uses unknown tokens {sorted(bad)}")
                    if "{{" in val or "}}" in val:
                        errs.append(f"{sec}.{key} must not contain double braces")
    ww = policy.get("weekday_words")
    if isinstance(ww, dict) and ww.get("next", "following_week") not in ("following_week", "next_occurrence"):
        errs.append("weekday_words.next must be following_week or next_occurrence")
    for sec in RULED + tuple(k for k in ("weekday_words",) if isinstance(policy.get(k), dict)):
        if not policy[sec].get("source"):
            errs.append(f"{sec}.source: at least one quote from the brief is required")
    errs += _check_sections(policy)
    if brief_text is not None:
        errs += [f"{path}.source quote not found in {f or 'the brief'}: {q[:60]!r}" for path, f, q in bad_quotes(policy, brief_text)]
    return errs


# ---- sections added for the reducer (design/REDUCER-CONTRACT.md §7); same file, same validator, same source rule
#  "meta":        {bank_name, agent_self_description, language, call_vars{role: var}, address_template, source}
#  "sentences":   {id: {text, verbatim: bool, max_times, source}}            required exact wording
#  "identity":    {questions[{field (OAS enum when one exists), brief_name, ask, format}], max_wrong,
#                  on_fail{outcome, reason}, on_decline{outcome, reason}, decline_explain_max, hint_rules[], source}
#  "products":    {fields{id, type, past_due, days_late}, floor_by_type{type: {kind: account_field|percent_of_past_due,
#                  field | percent, round}}, naming_by_type{type: text}, order, source}
#  deadline.bands[] may also carry min_days_late and attempts (persuasion attempts per band)
#  "amounts", "multi_product", "events": free-form dicts with source
#  "writes":      {promise{retries}, notes{when, none_if_transfer}, callback{days, start, end, inclusive, after_now},
#                  transfer{queue_map}, source}
#  "closing":     {table[{outcome, reason, when}], precedence[], reason_omitted_for[], source}
#  "honesty_words": {words[], source}
#  "superseded":  [{rule, old_value, new_value, winner_file, loser_file, why, source}]
#  "unmapped":    [{rule_id, quote, file, phase_guess, kind_guess}]                 never fails the build
# A source item is a quote string or {file, quote}; {file: "default"} marks a default used because the brief is silent.
CORE = ("identity", "products", "deadline", "closing")


def _src_items(src):
    for s in src if isinstance(src, list) else [src]:
        if isinstance(s, str):
            yield None, s
        elif isinstance(s, dict):
            yield s.get("file"), s.get("quote", "")


def _walk(x, path=""):
    if isinstance(x, dict):
        if "source" in x:
            yield path or "(root)", x["source"]
        for k, v in x.items():
            if k != "source":
                yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def bad_quotes(policy, brief_text):
    """-> [(path, file, quote)] for every quote not found verbatim (whitespace and markdown markers ignored).
    brief_text: one string, or {file name: text} so a quote is checked against the file it names."""
    files = brief_text if isinstance(brief_text, dict) else {None: brief_text}
    alltext = _norm(" ".join(files.values()))
    out = []
    for path, src in _walk(policy):
        for f, q in _src_items(src):
            if f == "default":
                continue
            if not q:
                out.append((path, f, q))
                continue
            hay = alltext
            if f is not None:
                match = [t for name, t in files.items() if name and (name == f or name.endswith("/" + f) or f.endswith("/" + str(name)) or name.split("/")[-1] == f.split("/")[-1])]
                hay = _norm(" ".join(match)) if match else alltext
            if _norm(q) not in hay:
                out.append((path, f, q))
    for i, u in enumerate(policy.get("unmapped") or []):
        if isinstance(u, dict) and u.get("quote") and _norm(u["quote"]) not in alltext:
            out.append((f"unmapped[{i}]", u.get("file"), u["quote"]))
    return out


def _check_sections(policy):
    errs = []
    for b in policy.get("deadline", {}).get("bands", []):
        for k in ("min_days_late", "attempts"):
            if k in b and not isinstance(b[k], int):
                errs.append(f"deadline.bands.{k} must be an int")
    idn = policy.get("identity")
    if isinstance(idn, dict):
        if not idn.get("questions"):
            errs.append("identity.questions is empty")
        if not isinstance(idn.get("max_wrong"), int):
            errs.append("identity.max_wrong must be an int")
    cl = policy.get("closing")
    if isinstance(cl, dict) and not all(isinstance(r, dict) and r.get("outcome") for r in cl.get("table") or []):
        errs.append("closing.table rows need an outcome")
    cb = (policy.get("writes") or {}).get("callback")
    if isinstance(cb, dict):
        for k in ("start", "end"):
            if k in cb and not re.match(r"^[0-2][0-9]:[0-5][0-9]$", str(cb[k])):
                errs.append(f"writes.callback.{k} must be HH:MM")
    return errs


def core_missing(policy):
    """Core sections that are absent or empty: the builder must switch that brief to the whole-builder fallback."""
    miss = [k for k in CORE if not policy.get(k)]
    if policy.get("closing") and not policy["closing"].get("table"):
        miss.append("closing.table")
    if policy.get("deadline") and not policy["deadline"].get("bands"):
        miss.append("deadline.bands")
    return miss
