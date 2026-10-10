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
        src = policy[sec].get("source")
        if not src:
            errs.append(f"{sec}.source: at least one quote from the brief is required")
        elif brief_text is not None:
            for q in src:
                if _norm(q) not in _norm(brief_text):
                    errs.append(f"{sec}.source quote not found in the brief: {q[:60]!r}")
    return errs
