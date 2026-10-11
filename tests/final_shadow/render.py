"""Render the shadow-persona templates with a bindings file. Offline only: stdlib, no network or model calls.

    python3 tests/final_shadow/render.py tests/final_shadow/persona_templates.json bindings.json [-o out.json]

bindings.json: {"values": {"<placeholder>": "<text>", ...}, "enable_branches": ["hardship", ...]}
A persona is rendered only if every name in its `requires` has a value; a conditional persona also needs its
`branch` in enable_branches. Any placeholder left unresolved raises.
"""
import argparse
import json
import re
import sys

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_0-9]+)\s*\}\}")
PERSONA_KEYS = ("id", "name", "description", "tags", "requires", "turns", "risk_focus", "conditional", "branch")


class RenderError(ValueError):
    pass


def placeholders(text):
    return set(PLACEHOLDER.findall(text))


def fill(text, values, persona_id):
    out = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    left = placeholders(out)
    if left or "{{" in out or "}}" in out:
        raise RenderError(f"{persona_id}: unresolved placeholder(s) {sorted(left) or out!r}")
    return out


def render(templates, bindings):
    values = {k: str(v) for k, v in (bindings.get("values") or {}).items() if v not in (None, "")}
    enabled = set(bindings.get("enable_branches") or [])
    rendered, skipped = [], []
    for p in templates["personas"]:
        if p["conditional"] and p["branch"] not in enabled:
            skipped.append({"id": p["id"], "reason": f"branch {p['branch']} not enabled"})
            continue
        missing = [r for r in p["requires"] if r not in values]
        if missing:
            skipped.append({"id": p["id"], "reason": "missing " + ", ".join(missing)})
            continue
        rendered.append({"id": p["id"], "name": p["name"], "tags": p["tags"], "risk_focus": p["risk_focus"],
                         "turns": [fill(t, values, p["id"]) for t in p["turns"]]})
    return {"rendered": rendered, "skipped": skipped}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("templates")
    ap.add_argument("bindings")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    with open(a.templates, encoding="utf-8") as f:
        templates = json.load(f)
    with open(a.bindings, encoding="utf-8") as f:
        bindings = json.load(f)
    text = dumps(render(templates, bindings))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
