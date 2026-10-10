"""Independent ledger oracle for generated debt-collection briefs.

This module intentionally imports no builder code and performs no I/O or network calls.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


def _money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_business_day(day: date, policy: dict) -> bool:
    calendar = policy["calendar"]
    return day.weekday() in calendar["business_weekdays"] and day.isoformat() not in calendar["holidays"]


def next_business_day(day: date, policy: dict) -> date:
    candidate = day + timedelta(days=1)
    while not is_business_day(candidate, policy):
        candidate += timedelta(days=1)
    return candidate


def add_days(day: date, count: int, unit: str, policy: dict) -> date:
    if unit == "calendar":
        return day + timedelta(days=count)
    if unit != "business":
        raise ValueError(f"unknown day unit: {unit}")
    result = day
    for _ in range(count):
        result = next_business_day(result, policy)
    return result


def band_for(policy: dict, days_late: int) -> dict:
    for band in policy["lateness_bands"]:
        if band["min_days_late"] <= days_late <= band["max_days_late"]:
            return band
    raise ValueError(f"no lateness band covers {days_late} days")


def deadline_for(policy: dict, product: dict, today: date) -> date:
    rule = band_for(policy, product["days_late"])["deadline"]
    result = add_days(today, rule["count"], rule["unit"], policy)
    while not is_business_day(result, policy):
        result -= timedelta(days=1)
    return result


def _round_increment(value: Decimal, rounding: dict) -> Decimal:
    increment = Decimal(str(rounding["increment"]))
    modes = {"nearest": ROUND_HALF_UP, "up": ROUND_CEILING, "down": ROUND_FLOOR}
    return (value / increment).quantize(Decimal("1"), rounding=modes[rounding["mode"]]) * increment


def floor_for(policy: dict, product: dict) -> float:
    rule = policy["floor_rule"]
    past_due = Decimal(str(product["past_due"]))
    if rule["type"] == "account_field":
        value = Decimal(str(product[rule["fields"][product["type"]]]))
    elif rule["type"] == "percent":
        value = _round_increment(past_due * Decimal(str(rule["percent"])) / 100, rule["rounding"])
    elif rule["type"] == "fixed":
        value = Decimal(str(rule["amount"]))
    elif rule["type"] == "max_fixed_percent":
        percent = _round_increment(past_due * Decimal(str(rule["percent"])) / 100, rule["rounding"])
        value = max(Decimal(str(rule["fixed"])), percent)
    else:
        raise ValueError(f"unknown floor rule: {rule['type']}")
    return _money(value)


def _code(policy: dict, group: str, semantic: str | None) -> str | None:
    if semantic is None:
        return None
    return policy["codes"][group][semantic]


def _normalise_intent(intent: str | dict) -> dict:
    if isinstance(intent, dict):
        return intent
    text = intent.strip().lower()
    if text == "pay today":
        return {"kind": "pay_today"}
    match = re.fullmatch(r"(?:name )?date[ :]([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    if match:
        return {"kind": "name_date", "date": match.group(1)}
    match = re.fullmatch(r"refuse(?: ×| x|:)?(\d+)", text)
    if match:
        return {"kind": "refuse", "count": int(match.group(1))}
    names = {
        "too much": "too_much",
        "dispute": "dispute",
        "paid": "paid",
        "hardship": "hardship",
        "restructure": "restructure",
        "third party": "third_party",
        "human": "human",
        "wrong number": "wrong_number",
        "deceased": "deceased",
    }
    if text in names:
        return {"kind": names[text]}
    raise ValueError(f"unknown intent: {intent}")


def _last_business_day_of_week(today: date, policy: dict) -> date:
    monday = today - timedelta(days=today.weekday())
    valid = [monday + timedelta(days=i) for i in range(7) if is_business_day(monday + timedelta(days=i), policy)]
    if valid and valid[-1] > today:
        return valid[-1]
    monday += timedelta(days=7)
    valid = [monday + timedelta(days=i) for i in range(7) if is_business_day(monday + timedelta(days=i), policy)]
    if not valid:
        raise ValueError("calendar has a week without a business day")
    return valid[-1]


def _attempt_date(rule: dict, today: date, deadline: date, policy: dict) -> date:
    if rule["type"] == "deadline":
        result = deadline
    elif rule["type"] == "last_business_day_this_or_next_week":
        result = _last_business_day_of_week(today, policy)
    elif rule["type"] == "offset":
        result = add_days(today, rule["count"], rule["unit"], policy)
    else:
        raise ValueError(f"unknown persuasion date rule: {rule['type']}")
    if result > deadline:
        result = deadline
    if not is_business_day(result, policy):
        moved = result
        while not is_business_day(moved, policy):
            moved += timedelta(days=1)
        result = moved if moved <= deadline else deadline
    return result


def _amount_in_range(policy: dict, amount: float, floor: float, past_due: float) -> bool:
    rule = policy["accepted_amount_range"]
    if amount == past_due:
        return True
    if rule.get("partial_mode", "range") == "exact_floor":
        return amount == floor
    lower = floor if rule["minimum"] == "floor" else past_due
    upper = past_due
    low_ok = amount >= lower if rule["minimum_inclusive"] else amount > lower
    high_ok = amount <= upper if rule["maximum_inclusive"] else amount < upper
    return low_ok and high_ok


def _promise_for_product(policy: dict, product: dict, intent: dict, today: date) -> dict | None:
    floor = floor_for(policy, product)
    past_due = _money(product["past_due"])
    deadline = deadline_for(policy, product, today)
    kind = intent["kind"]

    if kind == "pay_today":
        amount, wanted = past_due, today
    elif kind == "name_date":
        amount, wanted = _money(intent.get("amount", past_due)), _day(intent["date"])
    elif kind == "too_much":
        if not intent.get("accept_offer", True):
            return _refusal_offer(policy, product, intent.get("refuse_count", 99), today, prefer_floor=True)
        amount, wanted = floor, _day(intent.get("date", today.isoformat()))
    elif kind == "refuse":
        return _refusal_offer(policy, product, int(intent.get("count", 99)), today, intent.get("prefer_floor", False))
    else:
        return None

    if kind != "too_much" and not _amount_in_range(policy, amount, floor, past_due):
        if amount < floor and intent.get("accept_adjustment", True):
            amount = floor
        else:
            return _refusal_offer(policy, product, 99, today)
    if wanted < today:
        wanted = today
    if wanted > deadline:
        if not intent.get("accept_adjustment", True):
            return _refusal_offer(policy, product, 99, today)
        wanted = deadline
    elif not is_business_day(wanted, policy):
        if not intent.get("accept_adjustment", True):
            return _refusal_offer(policy, product, 99, today)
        moved = wanted
        while not is_business_day(moved, policy):
            moved += timedelta(days=1)
        wanted = moved if moved <= deadline else deadline
    return {"product_id": product["product_id"], "amount": _money(amount), "date": wanted.isoformat()}


def _refusal_offer(policy: dict, product: dict, refused: int, today: date, prefer_floor: bool = False) -> dict | None:
    band = band_for(policy, product["days_late"])
    attempts = band["persuasion_attempts"]
    if refused >= len(attempts):
        return None
    attempt = attempts[refused]
    deadline = deadline_for(policy, product, today)
    amount_rule = "floor" if prefer_floor and attempt["amount"] == "full" else attempt["amount"]
    amount = floor_for(policy, product) if amount_rule == "floor" else _money(product["past_due"])
    day = _attempt_date(attempt["date"], today, deadline, policy)
    return {"product_id": product["product_id"], "amount": amount, "date": day.isoformat()}


def _empty_ledger() -> dict:
    return {"outcome": None, "reason": None, "promises": [], "notes": [], "callbacks": [], "transfers": []}


def _close(ledger: dict, policy: dict, outcome: str, reason: str | None = None) -> dict:
    ledger["outcome"] = _code(policy, "outcomes", outcome)
    ledger["reason"] = _code(policy, "reasons", reason)
    return ledger


def _third_party(policy: dict, intent: dict, now: datetime) -> dict:
    ledger = _empty_ledger()
    kind = intent.get("situation", intent["kind"])
    if kind in ("wrong_number", "deceased"):
        spec = policy["special_situations"][kind]
        return _close(ledger, policy, spec["outcome"], spec["reason"])
    callback = policy["callback_window"]
    wanted_day = _day(intent.get("callback_date", now.date().isoformat()))
    wanted_time = intent.get("callback_time", callback["start"])
    next_day = next_business_day(now.date(), policy)
    valid_day = wanted_day in (now.date(), next_day)
    valid_time = callback["start"] <= wanted_time <= callback["end"]
    valid_future = wanted_day > now.date() or wanted_time > now.strftime("%H:%M")
    if intent.get("accept_callback", True) and valid_day and valid_time and valid_future:
        ledger["callbacks"].append({"date": wanted_day.isoformat(), "time": wanted_time})
        return _close(ledger, policy, "not_reached", "callback")
    return _close(ledger, policy, "not_reached", "no_callback")


def expected_ledger(policy: dict, customer: dict, intent: str | dict) -> dict:
    """Compute the ledger implied by *policy*, *customer*, and a declarative intent.

    Products without ids receive the mock's stable ids p1, p2, ... in input order.
    """
    intent = _normalise_intent(intent)
    now = datetime.fromisoformat(customer["variables"].get("now", "2026-10-14T11:00"))
    kind = intent["kind"]
    if kind in ("third_party", "wrong_number", "deceased"):
        return _third_party(policy, intent, now)
    if kind in ("identity_fail", "identity_decline"):
        ledger = _empty_ledger()
        if kind == "identity_fail" and int(intent.get("wrong_answers", policy["identity"]["wrong_answer_limit"])) < policy["identity"]["wrong_answer_limit"]:
            if "then" in intent:
                return expected_ledger(policy, customer, intent["then"])
            raise ValueError("identity_fail needs at least wrong_answer_limit wrong answers")
        reason = "failed" if kind == "identity_fail" else "declined"
        return _close(ledger, policy, "not_verified", reason)

    products = [dict(product, product_id=product.get("product_id", f"p{i}")) for i, product in enumerate(customer["products"], 1)]
    order = policy["multi_product"]["processing_order"]
    if order == "highest_days_late":
        products.sort(key=lambda item: item["days_late"], reverse=True)
    ledger = _empty_ledger()
    notes: list[tuple[dict, str]] = []
    transfer: tuple[str, str] | None = None

    for product in products:
        product_intent = intent.get("by_product", {}).get(product["product_id"], intent)
        product_intent = _normalise_intent(product_intent)
        product_kind = product_intent["kind"]
        if product_kind in ("restructure", "human") or (product_kind == "hardship" and product_intent.get("accept_transfer", False)):
            situation = policy["special_situations"][product_kind]
            if "transfer_to_agent" in policy["tools"]:
                transfer = (situation.get("transfer_reason", situation["reason"]), situation["queue"])
                break
            notes.append((product, situation["reason"]))
            continue
        if product_kind in ("dispute", "paid", "hardship"):
            notes.append((product, policy["special_situations"][product_kind]["reason"]))
            continue
        promise = _promise_for_product(policy, product, product_intent, now.date())
        if promise:
            ledger["promises"].append(promise)
        else:
            notes.append((product, "refused"))

    if transfer:
        reason, queue = transfer
        ledger["transfers"].append({"queue": _code(policy, "queues", queue)})
        if policy["multi_product"].get("suppress_notes_on_transfer", True):
            notes.clear()
        return _close(ledger, policy, "transferred", reason)

    multi = policy["multi_product"]["enabled"]
    if multi and policy["multi_product"].get("note_unresolved_products", True):
        ledger["notes"] = [
            {"product_id": product["product_id"], "reason": _code(policy, "note_reasons", reason)}
            for product, reason in notes
        ]
    if ledger["promises"] and (not notes or policy["multi_product"].get("promise_wins", True)):
        return _close(ledger, policy, "promise")
    if notes and all(reason == "paid" for _, reason in notes):
        return _close(ledger, policy, "paid")
    if notes:
        first_reason = next(reason for _, reason in notes if reason != "paid")
        return _close(ledger, policy, "no_promise", first_reason)
    return _close(ledger, policy, "promise" if ledger["promises"] else "no_promise", None if ledger["promises"] else "refused")
