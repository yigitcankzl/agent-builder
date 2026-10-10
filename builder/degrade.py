"""L2 degraded build (FINAL-PLAN ladder): when the validator still fails after the repair pass and EVERY error is on an
optional feature, strip those features and regenerate. The core flow (identity -> account -> promise -> close) is
never stripped; an error on it means L3.

degrade(rp, errors) -> (rp', stripped [str]) or (None, core_errors) when a core error remains.
Optional: the add_note / schedule_callback / transfer_to_agent tools (disabled_tools: no node, the hub routes an
unmatched call to free talk), hooks and unplaced hooks, run-stable soft rules, event/who say lines, date-rule say lines.
"""
import copy, re

OPTIONAL_TOOLS = ("add_note", "schedule_callback", "transfer_to_agent")
CORE_TOOLS = ("verify_identity", "get_account", "create_promise", "close_call")


def _tools_named(err):
    return [t for t in OPTIONAL_TOOLS + CORE_TOOLS if re.search(r"\b" + t + r"\b", err)]


def degrade(rp, errors):
    p = copy.deepcopy(rp)
    stripped, core = [], []
    for e in errors:
        num = (re.match(r"^(\d+):", e) or [None, ""])[1]
        named = _tools_named(e)
        if named and all(t in OPTIONAL_TOOLS for t in named):
            for t in named:
                if t not in (p.get("disabled_tools") or []):
                    p.setdefault("disabled_tools", []).append(t)
                    stripped.append(f"tool {t} ({e[:80]})")
        elif num == "17" or (num == "20" and "hook" in e):
            if p.get("hooks") or p.get("unplaced_hooks"):
                p["hooks"], p["unplaced_hooks"] = [], []
                stripped.append("hooks (" + e[:80] + ")")
        elif num == "9":
            if p.get("unmapped_rules"):
                p["unmapped_rules"] = []
                stripped.append("soft rules (" + e[:80] + ")")
        elif num in ("15", "20") and ("events" in e or "who_rules" in e):
            for coll in ("events", "who_rules"):
                for ev in p.get(coll) or []:
                    ev["say"] = ""
            stripped.append("event/who say lines (" + e[:80] + ")")
        elif num == "19" and "date_rules" in e:
            for r in (p.get("date_rules") or {}).values():
                r.pop("say", None)
            stripped.append("date-rule say lines (" + e[:80] + ")")
        else:
            core.append(e)
    if core:
        return None, core
    return p, sorted(set(stripped))
