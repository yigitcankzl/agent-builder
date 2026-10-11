"""Shadow personas (tests/final_shadow/render.py output) -> final runner cases.

    python3 tests/final_runner/convert_shadow.py <rendered.json> --meta <meta.json> -o <cases.json>

rendered.json: the render.py output ({"rendered": [...], "skipped": [...]}).
meta.json: the case facts that are NOT in the shadow personas, written by the case owner, never by this tool:
    {"customerNumber": "...", "now": "...", "checks": ["..."], "expect": {"mock": {...}}, "title": "..."}
    (a per-persona override is allowed: {"per_persona": {"<persona id>": {"checks": [...], "customerNumber": ...}}})
The customer's turns become the script (the customer's lines in order); the shadow text carries no case facts,
so the checks must come from meta. A persona without checks is written as unchecked and the runner refuses it
unless --allow-unchecked is passed.
"""
import argparse, json, sys


def script_from_turns(turns):
    lines = ["Konuşmanın sırası (her turda bir kısa cümle, karşı taraf ne derse ona göre):"]
    lines += [f"{i}. {t}" for i, t in enumerate(turns, 1)]
    return "\n".join(lines)


def convert(rendered, meta):
    per = meta.get("per_persona") or {}
    cases = []
    for p in rendered.get("rendered", []):
        over = dict(meta, **(per.get(p["id"]) or {}))
        case = {"id": p["id"], "title": p["name"], "customerNumber": over.get("customerNumber", ""),
                "now": over.get("now", ""), "script": script_from_turns(p["turns"])}
        checks = over.get("checks") or []
        if checks:
            case["checks"] = checks
        else:
            case["unchecked"] = True
            case["checks"] = []
        if over.get("expect"):
            case["expect"] = over["expect"]
        cases.append(case)
    return cases


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rendered")
    ap.add_argument("--meta", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    rendered = json.load(open(a.rendered, encoding="utf-8"))
    meta = json.load(open(a.meta, encoding="utf-8"))
    cases = convert(rendered, meta)
    json.dump(cases, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    unchecked = sum(1 for c in cases if c.get("unchecked"))
    print(f"{len(cases)} cases written, {unchecked} unchecked (need checks before a run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
