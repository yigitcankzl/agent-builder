"""L2 degraded build (FINAL-PLAN ladder): when the validator still fails after the repair pass and EVERY error is on an
optional feature, strip those features and regenerate. The core flow (identity -> account -> promise -> close) is
never stripped; an error on it means L3.

degrade(rp, errors) -> (rp', stripped [str]) or (None, core_errors) when a core error remains.
These tools are optional only when the resolved policy does not require them. Sourced speech is not optional.
"""
import copy, re

OPTIONAL_TOOLS = ("add_note", "schedule_callback", "transfer_to_agent")
CORE_TOOLS = ("verify_identity", "get_account", "create_promise", "close_call")


def _tools_named(err):
    return [t for t in OPTIONAL_TOOLS + CORE_TOOLS if re.search(r"\b" + t + r"\b", err)]


def _sourced(entry):
    src = entry.get("source") or []
    src = src if isinstance(src, list) else [src]
    return bool(entry.get("quote")) or any(
        bool(s.get("quote")) and s.get("file") != "default" if isinstance(s, dict) else bool(s) for s in src)


def mandatory_tools(p):
    w = p.get("writes") or {}
    transfers = (p.get("transfer") or {}, w.get("transfer") or {})
    required = set()
    if (w.get("notes") or {}).get("enabled"):
        required.add("add_note")
    if (w.get("callback") or ((p.get("identity") or {}).get("gate") or {}).get("on_no") == "callback"
            or any(e.get("effect_kind", e.get("effect")) == "callback" for e in p.get("who_rules") or [])):
        required.add("schedule_callback")
    if any(tr.get("queue_map") or tr.get("pre_verification_queues") for tr in transfers) or (p.get("human_request") or {}).get("queue"):
        required.add("transfer_to_agent")
    return required


def degrade(rp, errors):
    p = copy.deepcopy(rp)
    stripped, core = [], []
    required = mandatory_tools(p)
    for e in errors:
        num = (re.match(r"^(\d+):", e) or [None, ""])[1]
        named = _tools_named(e)
        if named and all(t in OPTIONAL_TOOLS for t in named):
            if required.intersection(named):
                core.append(e + " (mandatory policy feature; use L3)")
                continue
            for t in named:
                if t not in (p.get("disabled_tools") or []):
                    p.setdefault("disabled_tools", []).append(t)
                    stripped.append(f"tool {t} ({e[:80]})")
        elif num == "17" or (num == "20" and "hook" in e):
            if any(_sourced(h) for h in (p.get("hooks") or []) + (p.get("unplaced_hooks") or [])):
                core.append(e + " (sourced speech; use L3)")
                continue
            if p.get("hooks") or p.get("unplaced_hooks"):
                p["hooks"], p["unplaced_hooks"] = [], []
                stripped.append("hooks (" + e[:80] + ")")
        elif num == "9":
            if p.get("unmapped_rules"):
                p["unmapped_rules"] = []
                stripped.append("soft rules (" + e[:80] + ")")
        elif num in ("15", "20") and ("events" in e or "who_rules" in e):
            if any(ev.get("say") and _sourced(ev) for c in ("events", "who_rules") for ev in p.get(c) or []):
                core.append(e + " (sourced speech; use L3)")
                continue
            for coll in ("events", "who_rules"):
                for ev in p.get(coll) or []:
                    ev["say"] = ""
            stripped.append("event/who say lines (" + e[:80] + ")")
        elif num == "19" and "date_rules" in e:
            if any(r.get("say") and _sourced(r) for r in (p.get("date_rules") or {}).values()):
                core.append(e + " (sourced speech; use L3)")
                continue
            for r in (p.get("date_rules") or {}).values():
                r.pop("say", None)
            stripped.append("date-rule say lines (" + e[:80] + ")")
        else:
            core.append(e)
    if core:
        return None, core
    return p, sorted(set(stripped))
