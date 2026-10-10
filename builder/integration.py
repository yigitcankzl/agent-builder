"""Integration seam to Fork 3's modules (reducer, event field). This file holds NO reducer or decision logic.

hub_code(policy)            -> (code string, source)  builder.engine.reducer.hub_source(policy) when delivered, else the stub
ev_field(policy, identity)  -> (field dict, source)   builder.engine.event_field.ev_field(policy), or its field(vocab), else the stub
`source` says which one was used; the builder trace records it.
"""
import importlib, json


def _try(module, name):
    try:
        return getattr(importlib.import_module(module), name, None)
    except ImportError:
        return None


def stub_hub_code(policy):
    """STUB until the reducer lands: one fixed safe action every run (say safe_repeat), a fresh event token."""
    safe = ((policy.get("sentences") or {}).get("safe_repeat") or {}).get("text") or "Sorry, could you say that again?"
    # only json/re/datetime are verified in the code sandbox: the token comes from the clock
    return ("import datetime\n"
            "try:\n"
            "    vars['say_next'] = " + json.dumps(safe) + "\n"
            "    vars['route'] = 'say'\n"
            "    t = datetime.datetime.now().strftime('%f%S%M')\n"
            "    vars['ev_tok'] = ''.join('abcdefghijklmnopqrstuvwxyz'[(int(c) * 7 + i * 3) % 26] for i, c in enumerate(t[:6]))\n"
            "except Exception:\n"
            "    vars['route'] = 'talk_pre'\n")


STUB_EV_PATTERN = r"^n=[a-z]{6};src=user;kind=[a-z_]+;also=[a-z_]+;st=(complete|partial|ambiguous|none);prod=[a-z0-9]*(;[a-z_]+=[^;=]*)*$"


def stub_ev_field():
    return {"name": "ev", "type": "string", "min_confidence": 0.3, "max_retries": 2, "validation_pattern": STUB_EV_PATTERN,
            "description": "The customer's last message as one event code (contract §1)",
            "extraction_prompt": "Code: {{ev_tok}}\nLabel only the customer's last message as one event string: "
                                 "n=<the code>;src=user;kind=<kind>;also=<kind or none>;st=<complete|partial|ambiguous|none>;"
                                 "prod=<n or all or empty>. The value is a code label, never the customer's words."
                                 "\n{{extractor.type_preamble}}\n{{extractor.variables_list}}\nConversation:\n"
                                 "{{extractor.conversation.last-10}}\nLast message: {{extractor.speech}}"}


def hub_code(policy):
    f = _try("builder.engine.reducer", "hub_source")
    return (f(policy), "builder.engine.reducer.hub_source") if f else (stub_hub_code(policy), "stub")


def vocab(policy, identity_enum):
    """Data for the event field: topic names from the bridged policy, identity fields from the OAS enum."""
    return {"topics": sorted({e["topic"] for e in policy.get("events") or [] if e.get("topic")}),
            "identity_fields": list(identity_enum or [])}


def ev_field(policy, identity_enum=()):
    f = _try("builder.engine.event_field", "ev_field")
    if f:
        return f(policy), "builder.engine.event_field.ev_field"
    g = _try("builder.engine.event_field", "field")
    if g:
        return g(vocab(policy, identity_enum)), "builder.engine.event_field.field"
    return stub_ev_field(), "stub"
