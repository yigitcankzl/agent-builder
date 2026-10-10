#!/usr/bin/env python3
"""Validate the generated utterance bank and print its coverage."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


PRIORITY = ["topic", "identity", "callback", "who", "date_amount", "date", "amount", "accept", "yes", "reject", "no", "other"]
RANK = {kind: index for index, kind in enumerate(PRIORITY)}
TOP_KEYS = {"id", "agent_said", "customer_said", "expect", "trap"}
EXPECT_KEYS = {"kind", "also", "why", "t", "field", "ans", "y", "st", "who", "rel", "d", "m", "wd", "wk", "vague", "tm", "amt"}
DATE_KEYS = {"rel", "d", "m", "wd", "wk", "vague"}
TOPICS = {"dispute", "hardship", "paid", "complaint", "terms", "robot", "stop", "purpose", "restructure", "human", "wrong_number", "deceased"}
IDENTITY_FIELDS = {"date_of_birth", "phone_last4"}
WHO_VALUES = {"self", "other", "voicemail", "unclear"}
REQUIRED_TRAPS = {
    "flat_vs_too_much",
    "refusal_counteroffer",
    "correction",
    "spoken_number",
    "distractor_date",
    "year_carry",
    "question_back",
    "hedged_yes",
    "who_voicemail",
    "mixed_topic_amount",
    "dialect_filler_asr",
}


def prompt_context(agent_said: str) -> str:
    text = agent_said.casefold()
    if any(bit in text for bit in ("speaking with", "is that mr", "have i reached", "am i talking")):
        return "opening"
    if any(bit in text for bit in ("to confirm", "just to check", "got that right", "agreeing to", "read that back")):
        return "readback"
    if any(bit in text for bit in ("minimum", "floor amount", "lowest i can record")):
        return "floor"
    if "today" in text and any(bit in text for bit in ("full", "entire", "whole overdue")):
        return "full_today"
    if any(bit in text for bit in ("friday", "monday", "wednesday", "tomorrow", "december")):
        return "later"
    return "unknown"


def fail(line: int, message: str) -> None:
    raise ValueError(f"line {line}: {message}")


def validate_payload(line: int, expect: dict) -> None:
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        fail(line, f"unknown expect keys: {sorted(unknown)}")
    if not {"kind", "also"} <= set(expect):
        fail(line, "expect must contain kind and also")
    kind, also = expect["kind"], expect["also"]
    if kind not in RANK or (also is not None and also not in RANK):
        fail(line, "unknown kind or also")
    if also in {"yes", "no", "other"}:
        fail(line, f"also={also} is not a meaningful secondary event")
    if also is not None and RANK[kind] >= RANK[also]:
        fail(line, f"also={also} does not follow kind={kind} in priority order")

    labels = {kind} | ({also} if also else set())
    if "topic" in labels and expect.get("t") not in TOPICS:
        fail(line, "topic needs a supported t")
    if "t" in expect and "topic" not in labels:
        fail(line, "t is present without a topic label")
    if "identity" in labels and expect.get("field") not in IDENTITY_FIELDS:
        fail(line, f"identity field must be one of {sorted(IDENTITY_FIELDS)}")
    if "identity" in labels:
        partial_year = expect.get("st") == "partial"
        if partial_year:
            if expect.get("field") != "date_of_birth" or not isinstance(expect.get("y"), int) or not 1000 <= expect["y"] <= 9999 or "ans" in expect:
                fail(line, "partial birth year needs field=date_of_birth, y=YYYY, st=partial, and no ans")
        elif not isinstance(expect.get("ans"), str) or {"y", "st"} & set(expect):
            fail(line, "identity needs ans, except for a partial birth year")
    if ({"field", "ans", "y", "st"} & set(expect)) and "identity" not in labels:
        fail(line, "identity payload is present without an identity label")
    if "who" in labels and expect.get("who") not in WHO_VALUES:
        fail(line, f"who needs one of {sorted(WHO_VALUES)}")
    if "who" in expect and "who" not in labels:
        fail(line, "who payload is present without a who label")

    has_date = bool(DATE_KEYS & set(expect))
    has_amount = "amt" in expect
    if "callback" in labels and (not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(expect.get("tm", ""))) or not has_date):
        fail(line, "callback needs a date field and tm=HH:MM")
    if "date_amount" in labels and not (has_date and has_amount):
        fail(line, "date_amount needs date and amt payloads")
    if "date" in labels and not has_date:
        fail(line, "date needs a date payload")
    if "amount" in labels and not has_amount:
        fail(line, "amount needs amt")
    if has_amount and not isinstance(expect["amt"], (int, float)):
        fail(line, "amt must be numeric")
    if "d" in expect and (not isinstance(expect["d"], int) or not 1 <= expect["d"] <= 31):
        fail(line, "d must be an integer from 1 to 31")
    if "m" in expect and (not isinstance(expect["m"], int) or not 1 <= expect["m"] <= 12):
        fail(line, "m must be an integer from 1 to 12")
    if expect.get("wd") not in {None, "mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
        fail(line, "invalid wd")
    if expect.get("wk") not in {None, "this", "next", "after_next"}:
        fail(line, "invalid wk")
    if expect.get("rel") not in {None, "today", "tomorrow"}:
        fail(line, "invalid rel")
    if expect.get("vague") not in {None, "yes", "no"}:
        fail(line, "vague must be yes or no")
    if expect.get("why") not in {None, "flat", "too_much"}:
        fail(line, "invalid why")
    if "why" in expect and "reject" not in labels:
        fail(line, "why is present without reject")

    # Reconstruct all explicitly represented events, then apply the published priority.
    present = set(labels)
    if "t" in expect:
        present.add("topic")
    if "field" in expect or "ans" in expect:
        present.add("identity")
    if "who" in expect:
        present.add("who")
    if has_date and has_amount and "date_amount" in labels:
        present.add("date_amount")
    elif has_date and "date" in labels:
        present.add("date")
    elif has_amount and "amount" in labels:
        present.add("amount")
    if "why" in expect:
        present.add("reject")
    ordered = sorted(present, key=RANK.get)
    if ordered[0] != kind or (ordered[1] if len(ordered) > 1 else None) != also:
        fail(line, f"priority resolves to {ordered[:2]}, not {[kind, also]}")

    proposed = labels & {"date_amount", "date", "amount"}
    if kind == "reject" and (has_date or has_amount):
        fail(line, "a proposed date or amount cannot be labelled reject")
    if proposed and "why" in expect and also != "reject" and kind != "topic":
        fail(line, "a proposal plus refusal must use also=reject")


def validate_too_much(line: int, row: dict) -> None:
    expect = row["expect"]
    if expect.get("why") != "too_much" or "amt" in expect:
        return
    words = row["customer_said"].casefold()
    if not any(bit in words for bit in ("too much", "cannot afford", "can't afford", "amount", "full balance", "full amount")):
        fail(line, "why=too_much requires an amount objection")


def validate_phrases(line: int, row: dict) -> None:
    words = row["customer_said"].casefold()
    bare = re.sub(r"^(?:(?:well|er|honestly|sorry)[,\s]+)+", "", words).strip()
    expect = row["expect"]
    purpose_question = "who is this" in words or re.fullmatch(r"why are you asking(?: me)?(?: that)?\?", bare)
    if purpose_question:
        if (expect.get("kind"), expect.get("also"), expect.get("t")) != ("topic", None, "purpose"):
            fail(line, "a purpose question must be topic/purpose with no secondary event")
    if "stop calling" in words:
        if (expect.get("kind"), expect.get("also"), expect.get("t")) != ("topic", None, "stop"):
            fail(line, "stop calling must be topic/stop with no secondary event")


def validate(path: Path) -> tuple[Counter, Counter, Counter]:
    rows = []
    for line_number, raw in enumerate(path.read_text().splitlines(), 1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            fail(line_number, f"invalid JSON: {exc.msg}")
        if set(row) != TOP_KEYS:
            fail(line_number, f"top-level keys must be {sorted(TOP_KEYS)}")
        if not all(isinstance(row[key], str) and row[key].strip() for key in ("id", "agent_said", "customer_said", "trap")):
            fail(line_number, "id, utterances, and trap must be non-empty strings")
        if not isinstance(row["expect"], dict):
            fail(line_number, "expect must be an object")
        validate_payload(line_number, row["expect"])
        validate_too_much(line_number, row)
        validate_phrases(line_number, row)
        rows.append(row)

    if len(rows) < 400:
        raise ValueError(f"need at least 400 rows, found {len(rows)}")
    for key, value in (("id", lambda row: row["id"]), ("customer utterance", lambda row: row["customer_said"].strip().casefold())):
        seen = Counter(value(row) for row in rows)
        duplicates = [item for item, count in seen.items() if count > 1]
        if duplicates:
            raise ValueError(f"duplicate {key}: {duplicates[0]}")

    kinds = Counter(row["expect"]["kind"] for row in rows)
    missing = [kind for kind in PRIORITY if kinds[kind] < 25]
    if missing:
        raise ValueError(f"kinds below 25 rows: {missing}")
    contexts = Counter(prompt_context(row["agent_said"]) for row in rows)
    if set(contexts) != {"opening", "full_today", "later", "floor", "readback"} or min(contexts.values()) < 25:
        raise ValueError(f"prompt context coverage is too small: {dict(contexts)}")
    kind_contexts = defaultdict(set)
    for row in rows:
        kind_contexts[row["expect"]["kind"]].add(prompt_context(row["agent_said"]))
    if any(len(found) < 2 for found in kind_contexts.values()):
        raise ValueError("every kind must span at least two prompt contexts")
    traps = Counter(row["trap"] for row in rows)
    if any(traps[trap] < 10 for trap in REQUIRED_TRAPS):
        raise ValueError("each historically difficult trap needs at least 10 rows")
    return kinds, traps, contexts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path(__file__).with_name("utterances.jsonl"))
    args = parser.parse_args()
    try:
        kinds, traps, contexts = validate(args.path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(f"OK: {sum(kinds.values())} utterances")
    print("kinds:", " ".join(f"{key}={kinds[key]}" for key in PRIORITY))
    print("contexts:", " ".join(f"{key}={contexts[key]}" for key in sorted(contexts)))
    print("traps:", " ".join(f"{key}={traps[key]}" for key in sorted(traps)))


if __name__ == "__main__":
    main()
