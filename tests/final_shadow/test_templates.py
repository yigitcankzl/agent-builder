"""Checks for the shadow-persona templates and renderer.   python3 tests/final_shadow/test_templates.py"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render as R  # noqa: E402

TEMPLATES = json.load(open(os.path.join(HERE, "persona_templates.json"), encoding="utf-8"))
PERSONAS = TEMPLATES["personas"]
STYLES = {"pieces", "corrects", "talkative", "asks_back", "in_words"}
TEXT_FIELDS = ("name", "description", "risk_focus")

# Final-case facts and contract vocabulary must never appear in the persona text.
BANNED_WORDS = [
    # outcome / reason codes
    "promise", "no_promise", "not_verified", "not_reached", "transferred", "refused", "declined", "paid",
    "dispute", "hardship", "service_error", "callback", "unclear",
    # queues
    "restructuring", "support", "general",
    # tool names
    "verify_identity", "get_account", "create_promise", "close_call", "add_note", "schedule_callback",
    "transfer_to_agent",
    # API fields
    "customer_id", "product_id", "past_due", "days_late", "card_last4", "minimum_payment", "outcome", "reason",
]
BANNED_PATTERNS = [r"\d"]  # no digits at all: no ISO dates, amounts, phone numbers or years


def texts(p):
    return [p[k] for k in TEXT_FIELDS] + list(p["turns"])


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_schema():
    check(set(TEMPLATES) >= {"version", "placeholders", "personas"}, "top-level keys")
    for p in PERSONAS:
        check(tuple(sorted(p)) == tuple(sorted(R.PERSONA_KEYS)), f"{p.get('id')}: keys {sorted(p)}")
        check(isinstance(p["turns"], list) and p["turns"] and all(isinstance(t, str) for t in p["turns"]), p["id"])
        check(isinstance(p["tags"], list) and isinstance(p["requires"], list), p["id"])
        check(isinstance(p["conditional"], bool), p["id"])
        check((p["branch"] is None) != p["conditional"], f"{p['id']}: branch must be set iff conditional")
        check(set(p["requires"]) <= set(TEMPLATES["placeholders"]), f"{p['id']}: undeclared requires")


def test_ids_and_count():
    ids = [p["id"] for p in PERSONAS]
    check(len(ids) == len(set(ids)), "duplicate ids")
    check(15 <= len(ids) <= 20, f"{len(ids)} templates")


def test_styles_covered():
    tags = {t for p in PERSONAS for t in p["tags"]}
    check(STYLES <= tags, f"missing styles {STYLES - tags}")
    for p in PERSONAS:
        check(len(STYLES & set(p["tags"])) <= 2, f"{p['id']}: more than two styles")


def test_placeholders_declared():
    for p in PERSONAS:
        used = set().union(*(R.placeholders(t) for t in texts(p)))
        check(used <= set(p["requires"]), f"{p['id']}: uses {sorted(used - set(p['requires']))} not in requires")


def test_no_fixed_facts():
    for p in PERSONAS:
        for t in texts(p):
            low = t.lower()
            for w in BANNED_WORDS:
                check(not re.search(r"\b" + re.escape(w) + r"\b", low), f"{p['id']}: banned word {w!r}")
            for pat in BANNED_PATTERNS:
                check(not re.search(pat, R.PLACEHOLDER.sub("", t)), f"{p['id']}: digits in {t!r}")


def full_bindings(**extra):
    vals = {k: f"‹{k}›" for k in TEMPLATES["placeholders"]}
    b = {"values": vals, "enable_branches": []}
    b.update(extra)
    return b


def test_render_and_conditionals():
    out = R.render(TEMPLATES, full_bindings())
    ids = {r["id"] for r in out["rendered"]}
    conditional = {p["id"] for p in PERSONAS if p["conditional"]}
    check(conditional and not (ids & conditional), "conditional rendered without enable_branches")
    check(ids == {p["id"] for p in PERSONAS} - conditional, "all non-conditional rendered with full bindings")
    branches = sorted({p["branch"] for p in PERSONAS if p["conditional"]})
    out2 = R.render(TEMPLATES, full_bindings(enable_branches=branches))
    check(len(out2["rendered"]) == len(PERSONAS), "every persona renders when all branches enabled")
    part = R.render(TEMPLATES, {"values": {"amount": "x"}, "enable_branches": []})
    check(all(set(next(p for p in PERSONAS if p["id"] == r["id"])["requires"]) <= {"amount"}
              for r in part["rendered"]), "personas with missing requires are skipped")


def test_unresolved_fails():
    bad = {"personas": [{"id": "x", "name": "", "description": "", "tags": [], "requires": [], "risk_focus": "",
                         "conditional": False, "branch": None, "turns": ["Merhaba {{customer_name}}"]}]}
    try:
        R.render(bad, {"values": {}})
    except R.RenderError:
        return
    raise AssertionError("unresolved placeholder must raise")


def test_turkish_roundtrip():
    tr = "Çağrı Işıl Öztürk, şöyle ğüşiöç"
    b = full_bindings()
    b["values"]["customer_name"] = tr
    text = R.dumps(R.render(TEMPLATES, b))
    check(tr in text and "\\u" not in text, "Turkish characters escaped or lost")
    check(json.loads(text) == R.render(TEMPLATES, b), "JSON round trip")
    check(text == R.dumps(R.render(TEMPLATES, b)), "deterministic output")
    for p in PERSONAS:
        check(json.loads(json.dumps(p, ensure_ascii=False)) == p, p["id"])


def test_offline_only():
    banned = re.compile(r"\b(freya|anthropic|claude|openai|requests|urllib|http\.client|socket|subprocess)\b", re.I)
    for f in ("render.py", "persona_templates.json"):
        src = open(os.path.join(HERE, f), encoding="utf-8").read()
        check(not banned.search(src), f"{f} references a network/model API")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
