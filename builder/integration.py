"""Integration seam to Fork 3's modules (reducer, event field). This file holds NO reducer or decision logic.

hub_code(policy)            -> (code string, source)  builder.engine.reducer.hub_source(policy)
ev_field(policy, identity)  -> (field dict, source)   builder.engine.event_field.ev_field(policy), or its field(vocab)
`source` says which one was used; the builder trace records it.

There is NO stub fallback (signal S0): a reducer or event field that does not import, or that raises, raises
EngineNotLoaded. build.py turns it into exit 3 and saves nothing, so a dead agent that only says "Sorry, could you say
that again?" can never pass the build (a missing file in a clean clone, a bad import).
"""
import importlib


class EngineNotLoaded(RuntimeError):
    """The reducer or the event field could not be loaded or run (signal S0)."""


def _load(module, name):
    try:
        f = getattr(importlib.import_module(module), name, None)
    except Exception as e:          # ImportError, SyntaxError or anything raised at import time
        raise EngineNotLoaded(f"{module} failed to import: {type(e).__name__}: {e}") from e
    return f


def hub_code(policy):
    f = _load("builder.engine.reducer", "hub_source")
    if not f:
        raise EngineNotLoaded("builder.engine.reducer has no hub_source")
    try:
        return f(policy), "builder.engine.reducer.hub_source"
    except Exception as e:
        raise EngineNotLoaded(f"hub_source raised {type(e).__name__}: {e}") from e


def vocab(policy, identity_enum):
    """Data for the event field: topic names from the bridged policy, identity fields from the OAS enum."""
    return {"topics": sorted({e["topic"] for e in policy.get("events") or [] if e.get("topic")}),
            "identity_fields": list(identity_enum or [])}


def ev_field(policy, identity_enum=()):
    f = _load("builder.engine.event_field", "ev_field")
    g = None if f else _load("builder.engine.event_field", "field")
    if not (f or g):
        raise EngineNotLoaded("builder.engine.event_field has neither ev_field nor field")
    try:
        return (f(policy), "builder.engine.event_field.ev_field") if f else \
            (g(vocab(policy, identity_enum)), "builder.engine.event_field.field")
    except Exception as e:
        raise EngineNotLoaded(f"event_field raised {type(e).__name__}: {e}") from e
