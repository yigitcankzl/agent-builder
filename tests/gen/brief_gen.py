#!/usr/bin/env python3
"""Generate independent synthetic collection briefs, policies, and runnable cases."""

from __future__ import annotations

import argparse
import copy
import json
import random
from datetime import date, timedelta
from pathlib import Path

try:
    from .oracle import band_for, deadline_for, expected_ledger, next_business_day
except ImportError:
    from oracle import band_for, deadline_for, expected_ledger, next_business_day


ROOT = Path(__file__).resolve().parents[2]
TOOLS = [
    "verify_identity",
    "get_account",
    "create_promise",
    "add_note",
    "schedule_callback",
    "transfer_to_agent",
    "close_call",
]
PARAMETER_SPACE = {
    "identity_questions": ["date_of_birth", "phone_last4", "postcode", "birth_year", "full_name"],
    "floor_types": ["account_field", "percent", "fixed", "max_fixed_percent"],
    "deadline_units": ["business", "calendar"],
    "business_weekdays": [[0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5]],
    "product_order": ["account", "highest_days_late"],
}
LIVE_IDENTITY_FIELDS = ["date_of_birth", "phone_last4"]
DEFAULT_TOOL_FIELDS = {
    "verify_identity": {"customer_id": "customer_id", "field": "field", "answer": "answer"},
    "get_account": {"customer_id": "customer_id"},
    "create_promise": {"customer_id": "customer_id", "product_id": "product_id", "amount": "amount", "date": "date"},
    "add_note": {"customer_id": "customer_id", "product_id": "product_id", "reason": "reason", "text": "text"},
    "schedule_callback": {"customer_id": "customer_id", "date": "date", "time": "time"},
    "transfer_to_agent": {"customer_id": "customer_id", "queue": "queue"},
    "close_call": {"customer_id": "customer_id", "outcome": "outcome", "reason": "reason"},
}
HARD_AXES = {
    7: ["renamed outcome/reason codes", "counter-intuitive queue mapping", "single-file raw brief"],
    8: ["calendar deadline landing on a holiday", "three-step identity with full-name confirmation", "single-file raw brief"],
    9: ["add_note absent from OAS", "33.33% floor with nearest-0.05 tie rounding", "single-file raw brief"],
    10: ["transfer tool absent from OAS", "renamed create_promise/close_call fields", "single-file raw brief"],
    11: ["exactly-37.5% partial floor", "last business day of this week offer", "single-file raw brief"],
    12: ["absolute 47.50 minimum floor", "three business-day deadline skipping a holiday", "reversed identity order", "single-file raw brief"],
}


def brief_a_policy() -> dict:
    """Neutral parameterisation of briefs A/B rules used by the public oracle check."""
    return {
        "schema_version": 1,
        "policy_id": "brief-a-reference",
        "bank": {
            "name": "Freya Bank",
            "opening": "I am a digital assistant calling from Freya Bank, and this call is recorded.",
        },
        "identity": {"questions": ["date_of_birth", "phone_last4"], "wrong_answer_limit": 3},
        "calendar": {
            "business_weekdays": [0, 1, 2, 3, 4],
            "holidays": ["2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"],
        },
        "lateness_bands": [
            {
                "name": "early",
                "min_days_late": 1,
                "max_days_late": 7,
                "deadline": {"count": 12, "unit": "business"},
                "persuasion_attempts": [
                    {"amount": "full", "date": {"type": "last_business_day_this_or_next_week"}}
                ],
            },
            {
                "name": "late",
                "min_days_late": 8,
                "max_days_late": 45,
                "deadline": {"count": 7, "unit": "business"},
                "persuasion_attempts": [
                    {"amount": "full", "date": {"type": "last_business_day_this_or_next_week"}},
                    {"amount": "floor", "date": {"type": "deadline"}},
                ],
            },
        ],
        "floor_rule": {
            "type": "account_field",
            "fields": {
                "credit_card": "minimum_payment",
                "personal_loan": "instalment_amount",
                "car_loan": "instalment_amount",
            },
        },
        "accepted_amount_range": {
            "minimum": "floor",
            "maximum": "past_due",
            "minimum_inclusive": True,
            "maximum_inclusive": True,
        },
        "callback_window": {"dates": "today_or_next_business_day", "start": "10:00", "end": "19:00"},
        "codes": _codes(),
        "required_sentences": [
            {"event": "promise_recorded", "text": "You will receive a text message confirming this promise."},
            {"event": "deceased", "text": "I am sorry for your loss."},
        ],
        "special_situations": _special_situations(),
        "multi_product": {
            "enabled": False,
            "max_products": 1,
            "processing_order": "account",
            "shared_date_rule": "clamp_each_to_its_deadline",
            "note_unresolved_products": False,
            "suppress_notes_on_transfer": True,
            "promise_wins": True,
        },
        "tools": TOOLS,
    }


def _codes(rng: random.Random | None = None) -> dict:
    reasons = {
        "callback": "callback",
        "no_callback": "no_callback",
        "wrong_number": "wrong_number",
        "deceased": "deceased",
        "unclear": "unclear",
        "failed": "failed",
        "declined": "declined",
        "refused": "refused",
        "hardship": "hardship",
        "dispute": "dispute",
        "service_error": "service_error",
        "restructuring": "restructuring",
        "human": "human",
        "support": "support",
    }
    if rng:
        variants = {
            "refused": ["refused", "payment_declined", "no_commitment"],
            "hardship": ["hardship", "financial_difficulty", "vulnerability"],
            "dispute": ["dispute", "account_dispute", "liability_dispute"],
            "failed": ["failed", "security_failed", "verification_failed"],
            "declined": ["declined", "security_declined", "verification_declined"],
        }
        reasons.update({key: rng.choice(values) for key, values in variants.items()})
    queues = {"restructuring": "restructuring", "general": "general", "support": "support"}
    if rng:
        values = list(queues.values())
        rng.shuffle(values)
        queues = dict(zip(queues, values))
    return {
        "outcomes": {
            "promise": "promise",
            "paid": "paid",
            "transferred": "transferred",
            "no_promise": "no_promise",
            "not_verified": "not_verified",
            "not_reached": "not_reached",
        },
        "reasons": reasons,
        "note_reasons": {
            "refused": "refused",
            "hardship": "hardship",
            "dispute": "dispute",
            "paid": "paid",
            "service_error": "service_error",
        },
        "queues": queues,
    }


def _special_situations() -> dict:
    return {
        "dispute": {"outcome": "no_promise", "reason": "dispute"},
        "paid": {"outcome": "paid", "reason": "paid"},
        "hardship": {"outcome": "no_promise", "reason": "hardship", "transfer_reason": "support", "queue": "support"},
        "restructure": {"outcome": "transferred", "reason": "restructuring", "queue": "restructuring"},
        "human": {"outcome": "transferred", "reason": "human", "queue": "general"},
        "deceased": {"outcome": "not_reached", "reason": "deceased"},
        "wrong_number": {"outcome": "not_reached", "reason": "wrong_number"},
    }


def _random_floor(rng: random.Random) -> dict:
    kind = rng.choice(PARAMETER_SPACE["floor_types"])
    rounding = {"mode": rng.choice(["nearest", "up", "down"]), "increment": rng.choice([0.01, 0.05, 1.0])}
    if kind == "account_field":
        return brief_a_policy()["floor_rule"]
    if kind == "percent":
        return {"type": kind, "percent": rng.choice([20, 25, 30, 35, 40]), "rounding": rounding}
    if kind == "fixed":
        return {"type": kind, "amount": rng.choice([20, 25, 35, 50])}
    return {
        "type": kind,
        "fixed": rng.choice([20, 25, 35]),
        "percent": rng.choice([15, 20, 25, 30]),
        "rounding": rounding,
    }


def _attempt(rng: random.Random, index: int) -> dict:
    date_rule = rng.choice(["last_business_day_this_or_next_week", "deadline", "offset"])
    if date_rule == "offset":
        date_spec = {"type": date_rule, "count": rng.randint(2, 6), "unit": rng.choice(["business", "calendar"])}
    else:
        date_spec = {"type": date_rule}
    return {"amount": "full" if index == 0 and rng.random() < 0.7 else "floor", "date": date_spec}


def generate_policy(
    rng: random.Random,
    policy_id: str,
    identity_pool: list[str] | None = None,
) -> dict:
    banks = ["Juniper Bank", "Northstar Bank", "Copper Finch Bank", "Harbourline Bank", "Mosaic Bank"]
    bank = rng.choice(banks)
    openings = [
        f"This is the automated assistant from {bank}; this call is being recorded.",
        f"You are speaking with {bank}'s digital assistant. Please note that this call is recorded.",
        f"I am the virtual assistant for {bank}, calling on a recorded line.",
    ]
    identity_pool = identity_pool or PARAMETER_SPACE["identity_questions"]
    question_count = len(identity_pool) if identity_pool == LIVE_IDENTITY_FIELDS else rng.randint(1, min(3, len(identity_pool)))
    questions = rng.sample(identity_pool, question_count)
    weekdays = rng.choice(PARAMETER_SPACE["business_weekdays"])
    holiday_pool = ["2026-10-19", "2026-10-26", "2026-11-11", "2026-11-27", "2026-12-25", "2027-01-01"]
    holidays = sorted(rng.sample(holiday_pool, rng.randint(2, 4)))
    band_count = rng.choice([2, 3])
    cuts = sorted(rng.sample([5, 7, 10, 15, 20, 30], band_count - 1))
    limits = [1] + [cut + 1 for cut in cuts]
    ends = cuts + [60]
    bands = []
    for index, (start, end) in enumerate(zip(limits, ends), 1):
        attempts = rng.randint(1, 3)
        bands.append(
            {
                "name": ["early", "mid", "late"][index - 1] if band_count == 3 else ["early", "late"][index - 1],
                "min_days_late": start,
                "max_days_late": end,
                "deadline": {"count": rng.randint(4, 14), "unit": rng.choice(PARAMETER_SPACE["deadline_units"])},
                "persuasion_attempts": [_attempt(rng, attempt) for attempt in range(attempts)],
            }
        )
    start_hour = rng.choice([9, 10, 11])
    end_hour = rng.choice([17, 18, 19, 20])
    sentences = [
        {"event": "promise_recorded", "text": rng.choice([
            "A confirmation of this promise will be sent to you by text message.",
            "You will receive a text message confirming the payment promise.",
        ])},
        {"event": "deceased", "text": rng.choice(["I am sorry for your loss.", "Please accept my condolences."])},
    ]
    multi = rng.choice([True, False])
    return {
        "schema_version": 1,
        "policy_id": policy_id,
        "bank": {"name": bank, "opening": rng.choice(openings)},
        "identity": {"questions": questions, "wrong_answer_limit": rng.randint(2, 4)},
        "calendar": {"business_weekdays": weekdays, "holidays": holidays},
        "lateness_bands": bands,
        "floor_rule": _random_floor(rng),
        "accepted_amount_range": {
            "minimum": rng.choice(["floor", "full"]),
            "maximum": "past_due",
            "minimum_inclusive": True,
            "maximum_inclusive": True,
        },
        "callback_window": {
            "dates": "today_or_next_business_day",
            "start": f"{start_hour:02d}:00",
            "end": f"{end_hour:02d}:00",
        },
        "codes": _codes(rng),
        "required_sentences": sentences,
        "special_situations": _special_situations(),
        "multi_product": {
            "enabled": multi,
            "max_products": 3 if multi else 1,
            "processing_order": rng.choice(PARAMETER_SPACE["product_order"]),
            "shared_date_rule": "clamp_each_to_its_deadline",
            "note_unresolved_products": multi,
            "suppress_notes_on_transfer": True,
            "promise_wins": True,
        },
        "tools": TOOLS,
    }


def hard_policy(index: int, seed: int) -> dict:
    """Build one deterministic adversarial policy from the GEN-007..012 matrix."""
    if index not in HARD_AXES:
        raise ValueError(f"hard profile is defined only for GEN-007..012, not GEN-{index:03d}")
    rng = random.Random(seed + index)
    policy = generate_policy(rng, f"GEN-{index:03d}", LIVE_IDENTITY_FIELDS)
    policy["schema_version"] = 2
    policy["codes"] = _codes()
    policy["special_situations"] = _special_situations()
    policy["tools"] = list(TOOLS)
    policy["tool_fields"] = copy.deepcopy(DEFAULT_TOOL_FIELDS)
    policy["identity"]["confirm_full_name"] = False
    policy["accepted_amount_range"]["minimum"] = "floor"
    policy["accepted_amount_range"]["partial_mode"] = "range"
    policy["multi_product"].update({
        "enabled": False,
        "max_products": 1,
        "processing_order": "account",
        "note_unresolved_products": False,
    })

    if index == 7:
        policy["codes"]["outcomes"].update({
            "promise": "commitment_logged",
            "paid": "settled_elsewhere",
            "transferred": "specialist_handoff",
            "no_promise": "no_arrangement",
            "not_verified": "security_incomplete",
            "not_reached": "customer_unavailable",
        })
        policy["codes"]["reasons"].update({
            "refused": "payment_declined",
            "hardship": "affordability_alert",
            "dispute": "liability_challenged",
            "restructuring": "plan_review",
            "human": "person_requested",
            "support": "care_referral",
        })
        policy["codes"]["queues"] = {
            "restructuring": "support",
            "general": "restructuring",
            "support": "general",
        }
    elif index == 8:
        policy["identity"].update({
            "questions": ["phone_last4", "full_name", "date_of_birth"],
            "wrong_answer_limit": 3,
            "confirm_full_name": True,
        })
        policy["calendar"]["business_weekdays"] = [0, 1, 2, 3, 4]
        policy["calendar"]["holidays"] = sorted(set(policy["calendar"]["holidays"] + ["2026-10-19"]))
        for band in policy["lateness_bands"]:
            band["deadline"] = {"count": 5, "unit": "calendar"}
    elif index == 9:
        policy["tools"].remove("add_note")
        policy["tool_fields"].pop("add_note")
        policy["floor_rule"] = {
            "type": "percent",
            "percent": 33.33,
            "rounding": {"mode": "nearest", "increment": 0.05},
        }
    elif index == 10:
        policy["tools"].remove("transfer_to_agent")
        policy["tool_fields"].pop("transfer_to_agent")
        policy["tool_fields"]["create_promise"].update({"amount": "pledged_amount", "date": "due_on"})
        policy["tool_fields"]["close_call"].update({"outcome": "disposition", "reason": "reason_code"})
        policy["special_situations"]["restructure"]["outcome"] = "no_promise"
        policy["special_situations"]["human"]["outcome"] = "no_promise"
    elif index == 11:
        policy["floor_rule"] = {
            "type": "percent",
            "percent": 37.5,
            "rounding": {"mode": "nearest", "increment": 0.01},
        }
        policy["accepted_amount_range"]["partial_mode"] = "exact_floor"
        for band in policy["lateness_bands"]:
            band["persuasion_attempts"] = [
                {"amount": "full", "date": {"type": "last_business_day_this_or_next_week"}},
                {"amount": "floor", "date": {"type": "deadline"}},
            ]
    else:
        policy["identity"]["questions"] = ["phone_last4", "date_of_birth"]
        policy["floor_rule"] = {"type": "fixed", "amount": 47.5}
        policy["calendar"]["business_weekdays"] = [0, 1, 2, 3, 4]
        policy["calendar"]["holidays"] = sorted(set(policy["calendar"]["holidays"] + ["2026-10-16"]))
        for band in policy["lateness_bands"]:
            band["deadline"] = {"count": 3, "unit": "business"}
    return policy


def _floor_text(rule: dict) -> str:
    if rule["type"] == "account_field":
        return "the account's minimum_payment for cards and instalment_amount for loans"
    if rule["type"] == "fixed":
        return f"a fixed {rule['amount']:.2f}"
    rounding = rule["rounding"]
    rounded = f"rounded {rounding['mode']} to {rounding['increment']:.2f}"
    if rule["type"] == "percent":
        return f"{rule['percent']}% of past_due, {rounded}"
    return f"the greater of {rule['fixed']:.2f} and {rule['percent']}% of past_due, with the percentage {rounded}"


def _attempt_text(attempt: dict) -> str:
    date_rule = attempt["date"]
    if date_rule["type"] == "deadline":
        when = "the product deadline"
    elif date_rule["type"] == "last_business_day_this_or_next_week":
        when = "the last business day of this week, or next week if that day is today or past"
    else:
        when = f"{date_rule['count']} {date_rule['unit']} days after today"
    return f"offer the {attempt['amount']} amount on {when}"


def _amount_acceptance_text(policy: dict) -> str:
    if policy["accepted_amount_range"].get("partial_mode") == "exact_floor":
        return "Accept the full past_due amount or a partial amount exactly equal to the calculated floor; reject every other partial amount."
    return f"Customer-proposed amounts are accepted from {policy['accepted_amount_range']['minimum']} through past_due, including both ends."


def _special_text(policy: dict) -> str:
    codes = policy["codes"]
    if "transfer_to_agent" not in policy["tools"]:
        return (
            f"Already paid closes {codes['outcomes']['paid']} with no reason. Dispute closes {codes['outcomes']['no_promise']} / {codes['reasons']['dispute']}. "
            f"The API has no transfer operation: hardship, restructuring, and a human request close {codes['outcomes']['no_promise']} with reasons "
            f"{codes['reasons']['hardship']}, {codes['reasons']['restructuring']}, and {codes['reasons']['human']} respectively; never invent a transfer. "
            f"Deceased closes {codes['outcomes']['not_reached']} / {codes['reasons']['deceased']}; wrong number closes {codes['outcomes']['not_reached']} / {codes['reasons']['wrong_number']}."
        )
    return (
        f"Already paid: explain posting can take one business day and close {codes['outcomes']['paid']} with no reason. "
        f"Dispute: take no promise and close {codes['outcomes']['no_promise']} / {codes['reasons']['dispute']}. "
        f"Hardship: do not persuade; offer queue {codes['queues']['support']}, closing {codes['outcomes']['transferred']} / {codes['reasons']['support']} if accepted or {codes['outcomes']['no_promise']} / {codes['reasons']['hardship']} if declined. "
        f"Restructuring transfers to {codes['queues']['restructuring']} and closes {codes['outcomes']['transferred']} / {codes['reasons']['restructuring']}. "
        f"Ask an insistent human requester once whether you can help, then transfer to {codes['queues']['general']} and close {codes['outcomes']['transferred']} / {codes['reasons']['human']}. "
        f"Deceased closes {codes['outcomes']['not_reached']} / {codes['reasons']['deceased']}; wrong number closes {codes['outcomes']['not_reached']} / {codes['reasons']['wrong_number']}."
    )


def _tool_field_text(policy: dict) -> str:
    renamed = []
    for tool, fields in policy.get("tool_fields", {}).items():
        changed = [f"{semantic}→{actual}" for semantic, actual in fields.items() if semantic != actual]
        if changed:
            renamed.append(f"{tool}: {', '.join(changed)}")
    return " Tool field names are " + "; ".join(renamed) + "." if renamed else ""


def render_clean(policy: dict, rng: random.Random) -> str:
    weekdays = ", ".join(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i] for i in policy["calendar"]["business_weekdays"])
    bands = "\n".join(
        f"- {band['name']}: {band['min_days_late']}-{band['max_days_late']} days late; deadline {band['deadline']['count']} {band['deadline']['unit']} days after today; "
        + "; then ".join(_attempt_text(item) for item in band["persuasion_attempts"])
        for band in policy["lateness_bands"]
    )
    codes = policy["codes"]
    identity_step = " Confirm the full name as its own verification step." if policy["identity"].get("confirm_full_name") else ""
    note_rule = (
        "For paid, dispute, hardship, service error or exhausted refusals on one product, add the matching note and continue; if any promise is recorded it wins, while all-paid closes paid and otherwise the first non-paid product reason wins."
        if policy["multi_product"]["enabled"] and "add_note" in policy["tools"]
        else "No product notes are recorded."
    )
    sections = [
        ("Identity", f"Ask these questions one at a time in this order: {', '.join(policy['identity']['questions'])}.{identity_step} Verify each answer and retry a wrong answer. Stop after {policy['identity']['wrong_answer_limit']} wrong answers in total and close {codes['outcomes']['not_verified']} / {codes['reasons']['failed']}. A second refusal closes {codes['outcomes']['not_verified']} / {codes['reasons']['declined']}.") ,
        ("Calendar and lateness", f"Business weekdays are {weekdays}. Holidays are {', '.join(policy['calendar']['holidays'])}. Count a business-day deadline after today; count a calendar-day deadline by ordinary dates, then use the preceding business day if it lands on a closed day. A promise must be today or later, on a business day, and no later than its product deadline. Move a closed date to the next business day when that stays inside the deadline; otherwise offer the deadline. After a flat refusal, make the listed offers in order and stop when the list is exhausted.\n{bands}"),
        ("Amounts", f"Ask for past_due first. The floor is {_floor_text(policy['floor_rule'])}. {_amount_acceptance_text(policy)} If full is too much, offer the floor and say the rest remains overdue; that explicit floor offer is allowed even when unsolicited partial amounts are not."),
        ("Callbacks", f"For a third party, disclose no account information. A callback may be today or the next business day, later than now, from {policy['callback_window']['start']} through {policy['callback_window']['end']} inclusive. Ask once for a valid alternative; otherwise close {codes['outcomes']['not_reached']} / {codes['reasons']['no_callback']}. A valid booking closes {codes['outcomes']['not_reached']} / {codes['reasons']['callback']}."),
        ("Special situations", _special_text(policy)),
        ("Multiple products", f"Multiple products are {'enabled, up to ' + str(policy['multi_product']['max_products']) if policy['multi_product']['enabled'] else 'not enabled'}. Process in {policy['multi_product']['processing_order']} order and count attempts per product. A shared date is clamped separately to each deadline. {note_rule} Any transfer suppresses all notes."),
        ("Required wording", " ".join(f"At [{item['event']}], say exactly: \"{item['text']}\"" for item in policy["required_sentences"])),
    ]
    rng.shuffle(sections)
    intro = rng.choice(["Operating rules", "Call handling specification", "Collections playbook"])
    lines = [f"# {intro}: {policy['bank']['name']}", "", "All names and accounts are synthetic. Internal campaign scheduling text is not a customer rule.", "", f"1. Open exactly with: \"{policy['bank']['opening']}\" Do not reveal the purpose before identity passes.", "2. After verification call get_account, state every late product, and ask for the full past_due amount today."]
    for number, (heading, body) in enumerate(sections, 3):
        lines.extend(["", f"## {number}. {heading}", "", body])
    lines.extend(["", "## Tool and closing rules", "", f"Use only these {len(policy['tools'])} tools: {', '.join(policy['tools'])}.{_tool_field_text(policy)} Confirm amount, product and date before create_promise. close_call is exactly once and last. Outcomes: {', '.join(codes['outcomes'].values())}. Reasons: {', '.join(codes['reasons'].values())}."])
    return "\n".join(lines) + "\n"


def _raw_base(final: dict, rng: random.Random) -> tuple[dict, list[dict]]:
    base = copy.deepcopy(final)
    choices = ["wrong_limit", "callback", "deadline", "opening"]
    selected = rng.sample(choices, rng.randint(1, 3))
    overrides = []
    for choice in selected:
        if choice == "wrong_limit":
            path = "identity.wrong_answer_limit"
            before, after = 5 if final["identity"]["wrong_answer_limit"] != 5 else 2, final["identity"]["wrong_answer_limit"]
            base["identity"]["wrong_answer_limit"] = before
        elif choice == "callback":
            path = "callback_window.start"
            before, after = "08:00" if final["callback_window"]["start"] != "08:00" else "12:00", final["callback_window"]["start"]
            base["callback_window"]["start"] = before
        elif choice == "deadline":
            path = "lateness_bands.0.deadline.count"
            before, after = final["lateness_bands"][0]["deadline"]["count"] + 3, final["lateness_bands"][0]["deadline"]["count"]
            base["lateness_bands"][0]["deadline"]["count"] = before
        else:
            path = "bank.opening"
            before, after = f"Hello, this is {final['bank']['name']}.", final["bank"]["opening"]
            base["bank"]["opening"] = before
        overrides.append({"path": path, "before": before, "after": after})
    return base, overrides


def render_raw(policy: dict, rng: random.Random) -> tuple[dict[str, str], list[dict]]:
    base, overrides = _raw_base(policy, rng)
    email = f"""Subject: campaign hand-off / please configure\n\nTeam,\nUse the attached policy for {base['bank']['name']}. Start calls with: \"{base['bank']['opening']}\"\nThe board meeting moved to Thursday; that scheduling note is unrelated to customer promises. The seven API actions remain {', '.join(TOOLS)}.\nThanks,\nOperations\n"""
    extract = render_clean(base, rng).replace("# Call handling specification", "# POLICY EXTRACT").replace("# Operating rules", "# POLICY EXTRACT").replace("# Collections playbook", "# POLICY EXTRACT")
    memo_lines = ["Subject: LATER MEMO — effective immediately", "", "This memo takes precedence over the email and policy extract where they conflict."]
    for item in overrides:
        memo_lines.append(f"- Replace `{item['path']}` with `{item['after']}` (the earlier value `{item['before']}` is withdrawn).")
    memo_lines.append("Everything not named above remains unchanged.")
    alias_words = ["PROMISE", "SETTLED", "HANDOFF", "NO_DEAL", "ID_STOP", "NO_CONTACT"]
    csv_lines = ["kind,semantic,alias,canonical"]
    for (semantic, canonical), alias in zip(policy["codes"]["outcomes"].items(), alias_words):
        csv_lines.append(f"outcome,{semantic},{alias},{canonical}")
    for semantic, canonical in policy["codes"]["queues"].items():
        csv_lines.append(f"queue,{semantic},{semantic.upper()}_DESK,{canonical}")
    for semantic, canonical in policy["codes"]["note_reasons"].items():
        csv_lines.append(f"note_reason,{semantic},{semantic.upper()}_NOTE,{canonical}")
    files = {
        "email.md": email,
        "policy-extract.md": extract,
        "later-memo.md": "\n".join(memo_lines) + "\n",
        "codes.csv": "\n".join(csv_lines) + "\n",
    }
    files["brief.md"] = "\n\n".join(f"--- {name} ---\n{text.rstrip()}" for name, text in files.items()) + "\n"
    return files, overrides


def _codes_csv(policy: dict) -> str:
    lines = ["group,semantic,literal"]
    for group in ("outcomes", "reasons", "note_reasons", "queues"):
        for semantic, literal in policy["codes"][group].items():
            lines.append(f"{group},{semantic},{literal}")
    return "\n".join(lines) + "\n"


def _openapi(policy: dict) -> str:
    spec = json.loads((ROOT / "tools" / "openapi.json").read_text())
    spec["info"]["title"] = f"{policy['bank']['name']} synthetic collection tools"
    spec["info"]["version"] = policy["policy_id"].lower()
    spec["info"]["description"] = f"Synthetic offline schema for {policy['policy_id']}; it exposes {len(policy['tools'])} operations and omitted operations are unavailable."
    spec["paths"] = {
        path: operation
        for path, operation in spec["paths"].items()
        if path.removeprefix("/") in policy["tools"]
    }
    for tool, fields in policy.get("tool_fields", {}).items():
        if tool not in policy["tools"]:
            continue
        schema = spec["paths"][f"/{tool}"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        for semantic, actual in fields.items():
            if semantic == actual or semantic not in schema["properties"]:
                continue
            schema["properties"][actual] = schema["properties"].pop(semantic)
            schema["required"] = [actual if item == semantic else item for item in schema.get("required", [])]
    if "verify_identity" in policy["tools"]:
        fields = policy["tool_fields"]["verify_identity"]
        field_name = fields["field"]
        schema = spec["paths"]["/verify_identity"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        schema["properties"][field_name]["enum"] = policy["identity"]["questions"]
        schema["properties"][fields["answer"]]["description"] += " For full_name: the first and last name from the call variables."
        spec["paths"]["/verify_identity"]["post"]["summary"] = f"Check one security answer. {policy['identity']['wrong_answer_limit']} wrong answers in total end the check."
        spec["paths"]["/get_account"]["post"]["summary"] = "The late products. Refused until all configured identity questions are passed."
    if "close_call" in policy["tools"]:
        fields = policy["tool_fields"]["close_call"]
        schema = spec["paths"]["/close_call"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        schema["properties"][fields["outcome"]]["enum"] = list(policy["codes"]["outcomes"].values())
        schema["properties"][fields["reason"]]["enum"] = sorted(set(policy["codes"]["reasons"].values()))
    if "add_note" in policy["tools"]:
        field_name = policy["tool_fields"]["add_note"]["reason"]
        schema = spec["paths"]["/add_note"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        schema["properties"][field_name]["enum"] = list(policy["codes"]["note_reasons"].values())
    if "transfer_to_agent" in policy["tools"]:
        field_name = policy["tool_fields"]["transfer_to_agent"]["queue"]
        schema = spec["paths"]["/transfer_to_agent"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        schema["properties"][field_name]["enum"] = sorted(set(policy["codes"]["queues"].values()))
    return json.dumps(spec, indent=2) + "\n"


def render_hard_raw(policy: dict, rng: random.Random) -> tuple[dict[str, str], list[dict]]:
    base, overrides = _raw_base(policy, rng)
    codes_csv = _codes_csv(policy)
    first_deadline = base["lateness_bands"][0]["deadline"]
    table = "\n".join([
        "| Item | Earlier policy extract |",
        "|---|---|",
        f"| Identity order | {', '.join(base['identity']['questions'])} |",
        f"| Wrong-answer limit | {base['identity']['wrong_answer_limit']} |",
        f"| First-band deadline | {first_deadline['count']} {first_deadline['unit']} days after today |",
        f"| Floor | {_floor_text(base['floor_rule'])} |",
        f"| Available tools | {', '.join(base['tools'])} |",
    ])
    memo = ["## LATER OVERRIDE MESSAGE — effective immediately", "", "This message wins over every earlier email, table, and policy sentence where they conflict."]
    for item in overrides:
        before = json.dumps(item["before"], ensure_ascii=False)
        after = json.dumps(item["after"], ensure_ascii=False)
        memo.append(f"- `{item['path']}`: replace {before} with {after}.")
    memo.append("- Everything not listed above remains in force.")
    brief = "\n".join([
        f"# Forwarded campaign email: {policy['bank']['name']}",
        "",
        "Operations says the quarterly planning dates below are background only; customer promises follow the policy extract and the later override.",
        "",
        "## Attachment summary table",
        "",
        table,
        "",
        "## Policy extract",
        "",
        render_clean(base, rng).rstrip(),
        "",
        "## codes.csv (authoritative literal values)",
        "",
        "```csv",
        codes_csv.rstrip(),
        "```",
        "",
        "\n".join(memo),
        "",
    ])
    return {
        "brief.md": brief,
        "codes.csv": codes_csv,
        "openapi.json": _openapi(policy),
    }, overrides


def _identity_text(customer: dict, questions: list[str]) -> str:
    identity = customer["identity"]
    values = {
        "date_of_birth": identity.get("date_of_birth", "the date in the profile"),
        "phone_last4": identity.get("phone_last4", "the four digits in the profile"),
        "birth_year": identity.get("date_of_birth", "0000")[:4],
        "postcode": "AB12 3CD",
        "full_name": f"{customer['variables']['first_name']} {customer['variables']['last_name']}",
    }
    return ", then ".join(f"{question} {values[question]}" for question in questions)


def _script(customer: dict, policy: dict, intent: dict) -> tuple[str, str, str]:
    kind = intent["kind"]
    verified = f"Confirms the name and answers { _identity_text(customer, policy['identity']['questions']) }."
    if kind == "pay_today":
        return "Happy path", "Pays in full today", f"{verified} Can pay every past-due product in full today and confirms the read-back."
    if kind == "name_date":
        return "Dates", "Names a payment date", f"{verified} Cannot pay today and offers {intent['date']}. Accepts any policy-compliant adjusted date and confirms."
    if kind == "too_much":
        return "Amounts", "Full amount is too much", f"{verified} Says the full amount is too much, accepts the caller's floor offer for {intent['date']}, and confirms."
    if kind == "refuse":
        return "Refusal", "Refuses every allowed offer", f"{verified} Flatly refuses the initial request and all {intent['count']} permitted follow-up offers."
    if kind == "dispute":
        return "Dispute", "Disputes the debt", f"{verified} Says the debt is not theirs."
    if kind == "paid":
        return "Already paid", "Already paid", f"{verified} Says the past-due amount was already paid today."
    if kind == "hardship":
        return "Hardship", "Reports hardship", f"{verified} Says they lost their job, cannot pay, and declines a support transfer."
    if kind == "restructure":
        return "Restructuring", "Requests lower instalments", f"{verified} Requests a new plan with lower instalments."
    if kind == "human":
        return "Human", "Insists on a person", f"{verified} Requests a human and insists after the agent offers to help."
    if kind == "third_party":
        return "Third party", "Relative requests a callback", f"A relative answers, reveals nothing about the customer, and asks for a callback on {intent['callback_date']} at {intent['callback_time']}."
    actions = []
    for index, product in enumerate(customer["products"], 1):
        choice = intent["by_product"][f"p{index}"]["kind"]
        label = product["type"].replace("_", " ")
        action = {"pay_today": "pays in full today", "refuse": "refuses every offer", "dispute": "says the debt is not theirs"}[choice]
        actions.append(f"for the {label}, {action}")
    return "Multi-product", "Different choices by product", f"{verified} " + "; ".join(actions) + ". Confirms all accepted promises together."


def _checks(expected: dict, policy: dict) -> list[str]:
    checks = [f"close_call uses outcome {expected['outcome']}" ]
    if expected["reason"]:
        checks.append(f"close_call uses reason {expected['reason']}")
    checks.append(f"exactly {len(expected['promises'])} promises, {len(expected['notes'])} notes, {len(expected['callbacks'])} callbacks and {len(expected['transfers'])} transfers are recorded")
    if expected["promises"]:
        checks.append("every promise is read back and confirmed before it is recorded")
        sentence = next(item["text"] for item in policy["required_sentences"] if item["event"] == "promise_recorded")
        checks.append(f"after recording a promise the agent says exactly: {sentence}")
    checks.append(f"the opening identifies {policy['bank']['name']} and says the call is recorded")
    return checks


def generate_cases(policy: dict, public_cases: list[dict]) -> list[dict]:
    public = {case["id"]: case for case in public_cases}
    today = date.fromisoformat(public["PUB-01"]["variables"]["now"][:10])
    next_day = next_business_day(today, policy)
    sample_product = dict(public["PUB-03"]["products"][0], product_id="p1")
    after_deadline = deadline_for(policy, sample_product, today) + timedelta(days=3)
    attempts = len(band_for(policy, public["PUB-05"]["products"][0]["days_late"])["persuasion_attempts"])
    plans: list[tuple[str, dict]] = [
        ("PUB-01", {"kind": "pay_today"}),
        ("PUB-02", {"kind": "third_party", "callback_date": next_day.isoformat(), "callback_time": "12:00"}),
        ("PUB-03", {"kind": "name_date", "date": after_deadline.isoformat(), "accept_adjustment": True}),
        ("PUB-04", {"kind": "too_much", "date": next_day.isoformat()}),
        ("PUB-05", {"kind": "refuse", "count": attempts}),
        ("PUB-06", {"kind": "dispute"}),
        ("PUB-07", {"kind": "paid"}),
        ("PUB-08", {"kind": "hardship", "accept_transfer": False}),
        ("PUB-09", {"kind": "restructure"}),
        ("PUB-10", {"kind": "human"}),
    ]
    if policy["multi_product"]["enabled"]:
        shared = (max(deadline_for(policy, dict(product, product_id=f"p{i}"), today) for i, product in enumerate(public["PUB-13"]["products"], 1)) + timedelta(days=3)).isoformat()
        plans[-3:] = [
            ("PUB-11", {"kind": "pay_today"}),
            ("PUB-12", {"kind": "per_product", "by_product": {"p1": {"kind": "pay_today"}, "p2": {"kind": "refuse", "count": 99}, "p3": {"kind": "dispute"}}}),
            ("PUB-13", {"kind": "name_date", "date": shared, "accept_adjustment": True}),
        ]
    cases = []
    for case_id, intent in plans:
        source = public[case_id]
        expected = expected_ledger(policy, source, intent)
        family, title, script = _script(source, policy, intent)
        case = {
            "id": source["id"],
            "brief": policy["policy_id"],
            "family": family,
            "level": "medium",
            "title": title,
            "variables": copy.deepcopy(source["variables"]),
            "identity": copy.deepcopy(source["identity"]),
            "products": copy.deepcopy(source["products"]),
            "script": script,
            "expected": expected,
            "checks": _checks(expected, policy),
            "intent": intent,
        }
        if intent["kind"] == "third_party":
            case["third_party"] = True
        cases.append(case)
    return cases


def write_set(
    output: Path,
    count: int,
    seed: int,
    style: str = "mixed",
    start_index: int = 1,
    profile: str = "random",
) -> None:
    rng = random.Random(seed)
    public_cases = json.loads((ROOT / "public-test-set.json").read_text())
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": seed, "profile": profile, "briefs": []}
    for offset in range(count):
        index = start_index + offset
        selected_style = "raw" if profile == "hard" else (("clean" if offset < (count + 1) // 2 else "raw") if style == "mixed" else style)
        policy_id = f"GEN-{index:03d}"
        policy = hard_policy(index, seed) if profile == "hard" else generate_policy(rng, policy_id, LIVE_IDENTITY_FIELDS)
        axes = HARD_AXES[index] if profile == "hard" else []
        policy["generation"] = {
            "seed": seed,
            "index": index,
            "style": selected_style,
            "profile": profile,
            "axes": axes,
            "memo_overrides": [],
        }
        directory = output / policy_id.lower()
        directory.mkdir(parents=True, exist_ok=True)
        if profile == "hard":
            files, overrides = render_hard_raw(policy, rng)
            policy["generation"]["memo_overrides"] = overrides
        elif selected_style == "raw":
            files, overrides = render_raw(policy, rng)
            policy["generation"]["memo_overrides"] = overrides
        else:
            files = {"brief.md": render_clean(policy, rng)}
        for name, contents in files.items():
            (directory / name).write_text(contents)
        (directory / "expected_policy.json").write_text(json.dumps(policy, indent=2) + "\n")
        cases = generate_cases(policy, public_cases)
        (directory / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
        manifest["briefs"].append({
            "id": policy_id,
            "style": selected_style,
            "directory": directory.name,
            "cases": len(cases),
            "axes": axes,
        })
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--count", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--style", choices=["clean", "raw", "mixed"], default="mixed")
    parser.add_argument("--profile", choices=["random", "hard"], default="random")
    parser.add_argument("--start-index", type=int)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("generated"))
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    if args.out.exists() and not args.out.is_dir():
        parser.error(f"{args.out} is not a directory")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} is not empty; choose an empty output directory")
    start_index = args.start_index if args.start_index is not None else (7 if args.profile == "hard" else 1)
    if start_index < 1:
        parser.error("--start-index must be positive")
    if args.profile == "hard" and (start_index < 7 or start_index + args.count - 1 > 12):
        parser.error("the hard profile covers GEN-007 through GEN-012")
    write_set(args.out, args.count, args.seed, args.style, start_index, args.profile)
    print(f"wrote {args.count} briefs to {args.out}")


if __name__ == "__main__":
    main()
