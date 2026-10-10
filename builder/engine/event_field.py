"""The `ev` extraction field of reducer contract v2 (design/REDUCER-CONTRACT.md §1), generated from a vocabulary
(topics from policy.events, identity fields from the OAS enum), plus a parser for its value.

field(vocab) -> the extraction_schema entry;  parse(value) -> dict or None.
"""
import re

KINDS = ["identity", "who", "date", "amount", "date_amount", "accept", "reject", "yes", "no", "callback", "topic", "other"]
STATUS = ["complete", "partial", "ambiguous", "none"]
PAYLOAD_KEYS = ["field", "ans", "who", "party", "rel", "d", "m", "wd", "wk", "vague", "amt", "why", "tm", "t"]


def pattern(topics=()):
    """Topic names are also accepted as a kind (an alias the model produces); parse() normalises them to kind=topic."""
    kinds = "|".join(KINDS + [t for t in topics if t not in KINDS])
    return (rf"^n=[a-z0-9]{{1,8}};src=user;kind=({kinds});also=({kinds}|none);st=({'|'.join(STATUS)});"
            rf"prod=([0-9]{{1,2}}|all)?(;({'|'.join(PAYLOAD_KEYS)})=[^;=]*)*$")


def field(vocab):
    """vocab: {"topics": [...], "identity_fields": [...]} (generated from policy.events and the OAS enum)."""
    topics = "|".join(vocab["topics"])
    idf = "|".join(vocab["identity_fields"])
    prompt = (
        "Code: {{ev_tok}}. You label ONLY the customer's LAST message as one code line. Use earlier customer messages only to "
        "complete a number or date they split across turns. The value is a code label, never the customer's words.\n"
        "Format: n=<copy the code above letter by letter>;src=user;kind=<K>;also=<K or none>;st=<S>;prod=<product number 1-3, "
        "all, or empty>;<payload keys>\n"
        f"K, highest priority first (kind = the highest one present, also = the next one): topic (t={topics}) > date_amount > "
        "date > amount > accept (agrees to what the agent just offered) > yes > reject (why=too_much|flat) > no > "
        f"callback > who (who=self|other|unclear;party=relative|wrong_number|deceased or empty) > identity (field={idf};"
        "ans=the answer normalised: dates YYYY-MM-DD, digits only) > other. In the opening and the security questions, who "
        "and identity rank first.\n"
        "S: complete; partial = the customer was cut off mid number or date (then leave d, m and amt empty); ambiguous = "
        "two readings or contradicting parts; none = nothing relevant.\n"
        "Date payload, labels only, never compute a date: rel=today|tomorrow or empty;d=day of month or empty;m=month "
        "number or empty;wd=mon..sun or empty;wk=this|next|after_next|none;vague=yes|no. Amount payload: amt=digits with "
        "optional .dd. Callback adds tm=HH:MM. A date or amount the customer proposes is never a reject: kind=date (or "
        "amount) with also=reject. If the customer corrected themselves, use the corrected value.\n"
        "Examples: code kbmtpq, 'No, not Friday, Tuesday works' -> n=kbmtpq;src=user;kind=date;also=reject;st=complete;"
        "prod=;rel=;d=;m=;wd=tue;wk=none;vague=no\n"
        "code kxzrwa, 'on the twenty-' -> n=kxzrwa;src=user;kind=date;also=none;st=partial;prod=;rel=;d=;m=;wd=;wk=none;"
        "vague=no\n"
        "code kqqhst, 'nice weather today' -> n=kqqhst;src=user;kind=other;also=none;st=none;prod=\n"
        "code kpwrnd, 'I can pay 300 but not today' -> n=kpwrnd;src=user;kind=amount;also=reject;st=complete;prod=;amt=300\n"
        f"code kdvmse, a {vocab['topics'][0]} topic -> n=kdvmse;src=user;kind=topic;also=none;st=complete;prod=;t={vocab['topics'][0]}\n"
        "{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n{{extractor.conversation.last-10}}\n"
        "Last message: {{extractor.speech}}")
    return {"name": "ev", "type": "string", "min_confidence": 0.3, "max_retries": 2, "validation_pattern": pattern(vocab["topics"]),
            "description": "A code label like n=kbmtpq;src=user;kind=date;also=none;st=complete;prod=;d=27;m=;wd=;wk=none;vague=no. "
                           "Never the customer's own words.",
            "extraction_prompt": prompt}


def parse(value, topics=()):
    if not value or not re.match(pattern(topics), str(value)):
        return None
    out = dict()
    for part in str(value).split(";"):
        k, _, v = part.partition("=")
        out[k] = v
    if out.get("kind") in topics and out["kind"] not in KINDS:  # alias kind=<topic> -> kind=topic;t=<topic>
        out["t"], out["kind"] = out["kind"], "topic"
    if out.get("also") in topics and out["also"] not in KINDS:
        out["also"] = "topic"
    return out
