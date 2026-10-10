"""The exact code-node string for the date engine: engine source + policy literal + call. Tests exec this same string."""
import json, os

from builder.engine.date_policy import validate

ENGINE_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dates.py")


def _break_braces(s):
    while "{{" in s or "}}" in s:
        s = s.replace("{{", "{ {").replace("}}", "} }")
    return s


def code_source(policy):
    """Raises on an invalid policy or if the result would contain double braces."""
    errs = validate(policy)
    if errs:
        raise ValueError("invalid date policy: " + "; ".join(errs))
    lit = json.dumps(_break_braces(json.dumps(policy, ensure_ascii=True, sort_keys=True)))
    code = open(ENGINE_SRC).read() + "\n\nPOLICY = json.loads(" + lit + ")\nrun_safe(vars, POLICY)\n"
    if "{{" in code or "}}" in code:
        raise ValueError("code-node source contains double braces")
    compile(code, "date_resolve", "exec")
    return code
