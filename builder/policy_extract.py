"""Build-time policy extractor: Claude reads the brief files (md, eml, csv, txt) and the tool API file and fills the
policy schema of builder/engine/date_policy.py. Every value carries source = {file, quote}; code verifies every quote
verbatim and sends rejected quotes back for one repair round. Later material (a memo, a mail) overrides earlier text
and the override is recorded in `superseded`. Rules that fit no section go to `unmapped`; they never fail the build.

    python3 builder/policy_extract.py <brief files...> [--openapi tools/openapi.json] [--out policy.json] [--trace trace.jsonl]

Uses the local Claude Code CLI (`claude -p`, the user's subscription). Every model call is logged to the trace.
Nothing from any specific brief is written in this file.
"""
import argparse, json, os, re, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.engine.date_policy import AMOUNT_RULES, DATE_RULES, bad_quotes, core_missing, validate

MODEL = os.environ.get("POLICY_MODEL", "")          # empty: the CLI's default model
TEXT_EXT = (".md", ".txt", ".eml", ".csv", ".json", ".yaml", ".yml")

SCHEMA = r"""
Q means a source list: [{"file": "<file name as given>", "quote": "<text copied VERBATIM from that file, one sentence or table row>"}].
Use {"file": "default", "quote": ""} ONLY when the material says nothing at all about that item.
{
 "meta": {"bank_name": str, "agent_self_description": str, "language": str, "call_vars": {"<role>": "<variable name>"},
          "address_template": str, "source": Q},
 "now": {"var": "<call variable holding the current date/time>", "source": Q},
 "business_days": {"weekdays": [ints, Monday=0 .. Sunday=6], "holidays": ["YYYY-MM-DD"], "source": Q},
 "weekday_words": {"next": "following_week" | "next_occurrence", "rule": "<the material's own definition, or usual meaning>", "source": Q},
 "deadline": {"rule": "business_days_after_today" | "calendar_days_after_today",
              "bands": [{"name": str, "min_days_late": int, "max_days_late": int, "days": int, "attempts": int}], "source": Q},
 "earliest": {"allow_today": bool, "source": Q},
 "on_non_business_day": {"action": "next_business_day" | "previous_business_day" | "reject",
                         "say": "<short agent sentence; may use <NAMED> <DATE> <DEADLINE>>", "source": Q},
 "on_after_deadline": {"action": "offer_deadline" | "reject", "say": str, "source": Q},
 "on_vague": {"asks": int, "then": "offer_deadline" | "ask_again", "say_ask": str, "say_final": str, "source": Q},
 "identity": {"questions": [{"field": "<tool enum value if the tool API has one, else the material's term>",
                             "brief_name": str, "ask": str, "format": str}],
              "max_wrong": int, "on_fail": {"outcome": str, "reason": str}, "on_decline": {"outcome": str, "reason": str},
              "decline_explain_max": int, "hint_rules": [str], "source": Q},
 "products": {"fields": {"id": str, "type": str, "past_due": str, "days_late": str},
              "floor_by_type": {"<product type>": {"kind": "account_field", "field": str} |
                                {"kind": "percent_of_past_due", "percent": number, "round": "up" | "down" | "nearest"}},
              "naming_by_type": {"<product type>": "<how to name it>"}, "order": str, "source": Q},
 "attempts": {"plan": {"<band name as in deadline.bands>": [{"date_rule": DATE_RULE, "amount_rule": AMOUNT_RULE, "source": Q}]},
              "flat_refusal_uses_attempt": {"value": bool, "source": Q},
              "proposal_never_refusal": {"value": bool, "source": Q},
              "no_repeat_refused_offer": {"value": bool, "source": Q},
              "stop_when_exhausted": {"value": bool, "source": Q}},
 "amounts": {"first_ask": str, "too_much": str, "accept_range": str, "below_floor": str, "source": Q},
 "multi_product": {"applies": bool, "state_all_first": bool, "ask_all_today_once": bool, "one_date_clamp": bool,
                   "one_readback": bool, "source": Q},
 "events": [{"topic": str, "say": str, "effect": str, "note_reason": str, "outcome": str, "reason": str, "source": Q}],
 "writes": {"promise": {"retries": int, "fail_say": str},
            "notes": {"enabled": bool, "when": str, "none_if_transfer": bool},
            "callback": {"days": "<e.g. today_or_next_business_day>", "start": "HH:MM", "end": "HH:MM",
                         "inclusive": bool, "after_now": bool},
            "transfer": {"queue_map": {"<situation>": "<queue enum value>"},
                         "pre_verification_queues": ["<queues the material allows BEFORE identity is verified>"]},
            "source": Q},
 "closing": {"table": [{"outcome": "<API outcome string>", "reason": "<API reason string or null>", "when": str}],
             "precedence": [str], "reason_omitted_for": [str], "source": Q},
 "sentences": {"<id>": {"text": "<exact required wording>", "verbatim": true, "max_times": int, "source": Q}},
 "honesty_words": {"words": [str], "source": Q},
 "superseded": [{"rule": "<policy path>", "old_value": any, "new_value": any, "winner_file": str, "loser_file": str,
                 "why": str, "source": Q}],
 "unmapped": [{"rule_id": str, "quote": str, "file": str, "phase_guess": str, "kind_guess": str}]
}
"""

INSTRUCTIONS = """You extract a bank's call policy for a phone agent that calls customers late on a payment. Read ALL the
material below and return ONE JSON object that follows the schema exactly. Output JSON only, no prose, no code fence.

Rules:
1. Every section and every `sentences` item has `source`: quotes copied character for character from the named file
   (one sentence or one table row each; keep any markdown such as ** or `). Never paraphrase inside a quote.
2. Values come only from the material. Do not use knowledge of any other bank or brief. Where the material is silent,
   use the default marker described in the schema, and never invent business policy.
3. Several files: later or more specific instructions override earlier ones (a memo or mail that changes a policy
   wins over the policy it changes; look at dates and wording such as "supersedes", "replaces", "from now on").
   Use the winning value everywhere and add one `superseded` entry per overridden rule with old and new value, the
   winning and losing file, why, and the quote of the overriding text. Rules the newer file does not mention stay.
4. Tool API: use the exact enum strings from the tool API below for tool fields (identity field, transfer queue, note
   reason, outcome, product type keys in products.*_by_type). Map prose wording and internal codes (a code list) to
   the enum string with the SAME meaning. Never map to an enum value whose meaning differs even partly (a part of a
   value is not the whole value): then keep a short snake_case name of the material's own term. When the material itself states an exact API value (in backticks, or an API column of a code list), keep that
   exact string even if the tool API below lists a different one; the build checks enums afterwards.
5. closing.table lists every outcome/reason pair the material allows (reason null where none is sent).
6. deadline.bands: one entry per band, with the persuasion attempts allowed in that band in `attempts`.
7. sentences: every sentence the material requires the agent to say word for word (quoted wording), with a short id.
8. Any rule you cannot place in a section goes to `unmapped` with its exact quote. Do not drop rules. Do NOT put in
   `unmapped` the rules every agent of this kind enforces anyway: one promise per product; record only after a clear
   yes; the close tool is the last tool call; say goodbye before closing; a tool result decides success.
10. attempts.plan: for each band, one entry per persuasion attempt, in order. DATE_RULE is one of: DATE_RULES_LIST.
    AMOUNT_RULE is one of: AMOUNT_RULES_LIST (floor_if_too_much_else_full = the floor if the customer already said
    the full amount is too much, else the full amount). Also fill the four attempts flags, each with its quote.
11. events checklist: look for each of these situations and add an entry for every one the material covers, with
    the material's own topic name: hardship (illness, job loss, bereavement), dispute, already paid, restructuring or
    payment plan, asks for a human, asks whether the call is a scam, asks whether it is a robot or AI, a question
    the agent cannot answer, does not want to talk, refuses to answer a question, asks what the call is about,
    hands the phone to the customer. Raw material often scatters these over several files: check every file.
9. Holidays and dates as YYYY-MM-DD. Weekdays as integers with Monday = 0.
"""


def oas_summary(path):
    """Tool name -> {field: enum list or type}, read from an OpenAPI file."""
    if not path or not os.path.exists(path):
        return {}
    d = json.load(open(path))
    out = {}
    for p, ops in d.get("paths", {}).items():
        for op in ops.values():
            if not isinstance(op, dict):
                continue
            s = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
            name = p.strip("/").split("/")[-1]
            out[name] = {k: v.get("enum") or v.get("type") for k, v in (s.get("properties") or {}).items()}
            for code, resp in (op.get("responses") or {}).items():  # response enums, e.g. product types
                rs = (((resp.get("content") or {}).get("application/json") or {}).get("schema")) or {}
                enums = {}
                _collect_enums(rs, "", enums)
                if enums:
                    out[name + " (response)"] = enums
    return out


def _collect_enums(s, path, acc):
    if not isinstance(s, dict):
        return
    if s.get("enum"):
        acc[path or "."] = s["enum"]
    for k, v in (s.get("properties") or {}).items():
        _collect_enums(v, f"{path}.{k}" if path else k, acc)
    if isinstance(s.get("items"), dict):
        _collect_enums(s["items"], path + "[]", acc)


def read_files(paths):
    files = {}
    for p in paths:
        if os.path.isdir(p):
            for root, _, fs in os.walk(p):
                for f in sorted(fs):
                    if f.lower().endswith(TEXT_EXT):
                        files[os.path.relpath(os.path.join(root, f), os.path.dirname(p.rstrip("/")))] = open(os.path.join(root, f), errors="replace").read()
        else:
            files[os.path.basename(p)] = open(p, errors="replace").read()
    return files


class Trace:
    def __init__(self, path):
        self.path, self.calls = path, []

    def log(self, **kw):
        kw["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.calls.append(kw)
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(kw) + "\n")


def call_claude(prompt, purpose, trace):
    cmd = ["claude", "-p", "--output-format", "json", "--tools", "", "--no-session-persistence"]
    if MODEL:
        cmd += ["--model", MODEL]
    t0 = time.time()
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1500)
    dt = round(time.time() - t0, 1)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        trace.log(model=MODEL or "default", purpose=purpose, seconds=dt, ok=False, error=(r.stderr or r.stdout)[:300])
        raise RuntimeError(f"claude -p failed: {(r.stderr or r.stdout)[:300]}")
    model = ",".join((out.get("modelUsage") or {}).keys()) or MODEL or "default"
    trace.log(model=model, purpose=purpose, seconds=dt, ok=not out.get("is_error"), cost_usd=out.get("total_cost_usd"))
    return out.get("result", "")


def parse_json(text):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in the model output")
    return json.loads(m.group(0))


def _get(obj, path):
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        obj = obj[int(part[1:-1])] if part.startswith("[") else obj[part]
    return obj


def material_block(files, oas):
    parts = [f"=== FILE: {name} ===\n{text}" for name, text in files.items()]
    return "TOOL API (tool -> field -> enum or type):\n" + json.dumps(oas, indent=1) + "\n\n" + "\n\n".join(parts)


def extract(paths, openapi=None, trace_path=None, repair=True):
    """-> (policy, report). report: quotes_rejected, quotes_repaired, unmapped, superseded, oas_warnings, errors,
    fallback_required, seconds, model_calls."""
    t0 = time.time()
    trace = Trace(trace_path)
    files, oas = read_files(paths), oas_summary(openapi)
    block = material_block(files, oas)
    instr = INSTRUCTIONS.replace("DATE_RULES_LIST", " | ".join(DATE_RULES)).replace("AMOUNT_RULES_LIST", " | ".join(AMOUNT_RULES))
    policy = parse_json(call_claude(instr + "\nSCHEMA:\n" + SCHEMA + "\n\nMATERIAL:\n" + block, "extract policy from brief", trace))
    # runtime variable names are the builder's own wiring convention, not brief content
    policy.setdefault("inputs", {"iso_var": "date_iso", "spec_var": "date_spec", "products_var": "products",
                                 "current_product_var": "current_product_id", "product_id_field": "product_id",
                                 "days_late_field": "days_late", "days_late_var": "days_late"})
    bad = bad_quotes(policy, files)
    rejected, repaired = len(bad), 0
    if bad and repair:
        ask = ("Some quotes in your policy are not verbatim in the named file. For each item return a corrected source "
               "list copied character for character from the file, or [] if no such text exists. Output JSON only: "
               '{"fixes": [{"path": "<path>", "source": [{"file": str, "quote": str}]}]}\n\nItems:\n'
               + json.dumps([{"path": p, "file": f, "quote": q} for p, f, q in bad], indent=1) + "\n\nMATERIAL:\n" + block)
        fixes = parse_json(call_claude(ask, "repair rejected quotes", trace)).get("fixes", [])
        for fx in fixes:
            try:
                node = policy if fx["path"] == "(root)" else _get(policy, fx["path"])
                if isinstance(node, dict) and fx.get("source"):
                    node["source"] = fx["source"]
                elif fx["path"].startswith("unmapped[") and fx.get("source"):
                    node["quote"] = fx["source"][0]["quote"]
            except (KeyError, IndexError, TypeError):
                continue
        still = bad_quotes(policy, files)
        repaired = rejected - len(still)
        bad = still
    for path, f, q in bad:  # an unverifiable quote never survives: the value is kept but marked unverified
        try:
            node = policy if path == "(root)" else _get(policy, path)
            if isinstance(node, dict):
                node["source_unverified"] = node.pop("source", None)
        except (KeyError, IndexError, TypeError):
            pass
    warns = []
    enum = lambda tool, field: oas.get(tool, {}).get(field) if isinstance(oas.get(tool, {}).get(field), list) else None
    for q in (policy.get("identity") or {}).get("questions", []):
        e = enum("verify_identity", "field")
        if e and q.get("field") not in e:
            warns.append(f"identity field {q.get('field')!r} is not in the tool enum {e}")
    for r in (policy.get("closing") or {}).get("table", []):
        e = enum("close_call", "outcome")
        if e and r.get("outcome") not in e:
            warns.append(f"outcome {r.get('outcome')!r} is not in the tool enum {e}")
    for q in ((policy.get("writes") or {}).get("transfer") or {}).get("queue_map", {}).values():
        e = enum("transfer_to_agent", "queue")
        if e and q not in e:
            warns.append(f"queue {q!r} is not in the tool enum {e}")
    missing = core_missing(policy)
    report = {"files": list(files), "quotes_rejected": rejected, "quotes_repaired": repaired, "quotes_unverified": len(bad),
              "unmapped": policy.get("unmapped") or [], "superseded": policy.get("superseded") or [],
              "oas_warnings": warns, "errors": validate(policy), "fallback_required": bool(missing), "core_missing": missing,
              "seconds": round(time.time() - t0, 1), "model_calls": trace.calls}
    return policy, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("briefs", nargs="+")
    ap.add_argument("--openapi", default="tools/openapi.json")
    ap.add_argument("--out", default="policy.json")
    ap.add_argument("--trace", default="")
    a = ap.parse_args()
    policy, report = extract(a.briefs, a.openapi, a.trace or None)
    json.dump(policy, open(a.out, "w"), indent=1)
    json.dump(report, open(a.out.replace(".json", ".report.json"), "w"), indent=1)
    print(json.dumps({k: report[k] for k in ("quotes_rejected", "quotes_repaired", "quotes_unverified", "fallback_required", "seconds")}
                     | {"unmapped": len(report["unmapped"]), "superseded": len(report["superseded"]), "errors": report["errors"][:5]}))


if __name__ == "__main__":
    main()
