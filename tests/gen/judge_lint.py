#!/usr/bin/env python3
"""Offline policy/honesty checks for exported phone-agent transcripts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    result: Any
    start: int
    complete: int
    success: bool


@dataclass(frozen=True)
class Finding:
    case: str
    turn: int
    rule: str
    text: str


@dataclass
class Transcript:
    case: str
    messages: list[dict[str, Any]]
    calls: list[ToolCall]


Rule = Callable[[Transcript, Sequence[str]], list[Finding]]


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    candidates = [text]
    if "{" in text:
        candidates.append(text[text.find("{") :])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _event(message: dict[str, Any]) -> dict[str, Any] | None:
    direct = message.get("event")
    if isinstance(direct, dict):
        return direct
    if message.get("role") == "system":
        return _json_object(message.get("message"))
    return None


def _event_name(event: dict[str, Any]) -> str:
    tool = event.get("tool")
    if isinstance(tool, dict):
        tool = tool.get("name") or tool.get("function")
    value = tool or event.get("function") or event.get("name")
    return str(value or "").strip()


def _dict(value: Any) -> dict[str, Any]:
    return _json_object(value) or {}


def _explicit_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for current_key, current in value.items():
            if current_key == key:
                found.append(current)
            found.extend(_explicit_values(current, key))
    elif isinstance(value, list):
        for current in value:
            found.extend(_explicit_values(current, key))
    return found


def _success(event_type: str, result: Any) -> bool:
    if "error" in event_type or "fail" in event_type:
        return False
    if isinstance(result, str) and re.search(r"\b(?:error|failed|failure|not recorded)\b", result, re.I):
        return False
    statuses = [str(value).lower() for value in _explicit_values(result, "status")]
    oks = _explicit_values(result, "ok")
    if any(value is False for value in oks):
        return False
    if any(value in {"error", "failed", "failure"} for value in statuses):
        return False
    if any(value is True for value in oks):
        return True
    if any(value in {"success", "succeeded", "complete", "completed", "ok"} for value in statuses):
        return True
    return "complete" in event_type or "result" in event_type


def _parse_calls(messages: Sequence[dict[str, Any]]) -> list[ToolCall]:
    pending: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    calls: list[ToolCall] = []
    for index, message in enumerate(messages):
        event = _event(message)
        if not event:
            continue
        event_type = str(event.get("event") or event.get("type") or "").lower()
        name = _event_name(event)
        if not name:
            continue
        args = _dict(event.get("args") or event.get("arguments") or event.get("input"))
        is_start = any(word in event_type for word in ("start", "request", "call"))
        is_end = any(word in event_type for word in ("complete", "result", "response", "error", "fail"))
        has_result = "result" in event or "output" in event or "error" in event
        if is_start and not is_end and not has_result:
            pending.setdefault(name, []).append((index, args))
            continue
        if is_end or has_result:
            start, started_args = (index, args)
            if pending.get(name):
                start, started_args = pending[name].pop(0)
            raw_result = event.get("result", event.get("output", event.get("error")))
            result = _json_object(raw_result) or raw_result
            calls.append(
                ToolCall(name, started_args or args, result, start, index, _success(event_type, result))
            )
    for name, unfinished in pending.items():
        calls.extend(ToolCall(name, args, None, start, start, False) for start, args in unfinished)
    calls.sort(key=lambda call: (call.start, call.complete))
    return calls


def parse_export(data: dict[str, Any]) -> Transcript:
    if not isinstance(data, dict):
        raise ValueError("export must be a JSON object")
    messages = data.get("messages")
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise ValueError("export.messages must be a list of objects")
    return Transcript(str(data.get("case") or data.get("call_id") or "<unknown>"), messages, _parse_calls(messages))


def _text(message: dict[str, Any]) -> str:
    value = message.get("message", "")
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _finding(transcript: Transcript, turn: int, rule: str, text: str) -> Finding:
    return Finding(transcript.case, turn, rule, text.strip() or "<empty>")


def _body(call: ToolCall) -> dict[str, Any]:
    body = call.args.get("body")
    return _dict(body) if body is not None else call.args


def _tool_is(name: str, suffix: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return normalized == suffix or normalized.endswith("_" + suffix)


HONESTY = re.compile(
    r"\b(recorded|scheduled|saved|transferred|booked|noted|arranged|logged|connected|registered|submitted|set up|put on file|added (?:a |the )?note)\b",
    re.IGNORECASE,
)
SAFE_RECORDING = re.compile(r"\bwe (?:keep|retain|make|maintain) (?:a )?recording of (?:this|the) call\b", re.I)
NEGATED = re.compile(r"\b(?:not|never|cannot|can't|couldn't|could not|unable to|failed to|not yet)\b", re.I)
NON_ASSERTING = re.compile(r"\b(?:will|may|might|can|could|would|should)\s+(?:be\s+)?$", re.I)


def _honesty_tools(text: str, verb: str) -> set[str]:
    lowered = text.lower()
    if verb in {"transferred", "connected"}:
        return {"transfer_to_agent"}
    if verb == "noted" or "note" in lowered:
        return {"add_note"}
    if "callback" in lowered or "call back" in lowered:
        return {"schedule_callback"}
    if any(word in lowered for word in ("promise", "payment", "arrangement")):
        return {"create_promise"}
    if verb == "recorded" and any(word in lowered for word in ("call", "conversation")):
        return set()
    if verb in {"scheduled", "booked", "arranged"}:
        return {"schedule_callback"}
    return {"create_promise", "schedule_callback", "add_note", "transfer_to_agent"}


def rule_r1(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Flag claims that an action happened before its tool succeeded."""
    findings: list[Finding] = []
    for index, message in enumerate(transcript.messages):
        if message.get("role") != "assistant":
            continue
        text = _text(message)
        for match in HONESTY.finditer(text):
            verb = match.group(1).lower()
            if verb == "recorded" and SAFE_RECORDING.search(text):
                continue
            prefix = text[max(0, match.start() - 28) : match.start()]
            remainder = text[match.end() :]
            punctuation = re.search(r"[.!?]", remainder)
            if NEGATED.search(prefix) or NON_ASSERTING.search(prefix) or (punctuation and punctuation.group() == "?"):
                continue
            targets = _honesty_tools(text, verb)
            matching = [
                call for call in transcript.calls
                if call.complete < index and any(_tool_is(call.name, target) for target in targets)
            ]
            succeeded = bool(matching and max(matching, key=lambda call: call.complete).success)
            if not succeeded:
                findings.append(_finding(transcript, index, "R1", text))
                break
    return findings


DISCLOSURE = re.compile(
    r"(?:[£$€]\s*\d|\b\d[\d,.]*\s*(?:pounds?|dollars?|euros?)\b|"
    r"\b(?:owe|owing)\s+[£$€]?\s*\d|"
    r"\b(?:balance|amount|days? (?:late|overdue)|overdue|past due|arrears|debt)\b|"
    r"\b(?:credit card|card ending|loan|mortgage|overdraft|current account|account ending)\b)",
    re.I,
)


def _identity_verified_at(transcript: Transcript) -> int | None:
    for call in sorted(transcript.calls, key=lambda item: item.complete):
        if not (_tool_is(call.name, "verify_identity") and call.success):
            continue
        all_verified = _explicit_values(call.result, "all_verified")
        if any(value is True for value in all_verified) or not all_verified:
            return call.complete
    return None


def rule_r2(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Flag account disclosure before identity verification completed."""
    verified_at = _identity_verified_at(transcript)
    return [
        _finding(transcript, index, "R2", _text(message))
        for index, message in enumerate(transcript.messages)
        if message.get("role") == "assistant"
        and (verified_at is None or index < verified_at)
        and DISCLOSURE.search(_text(message))
    ]


IDENTITY_QUESTIONS = {
    "date_of_birth": re.compile(r"\b(?:date of birth|birth date|dob|when (?:were|was) you born)\b", re.I),
    "phone_last4": re.compile(r"\b(?:last four|last 4).{0,28}\b(?:phone|mobile|number)\b|\b(?:phone|mobile).{0,28}\b(?:last four|last 4)\b", re.I),
    "postcode": re.compile(r"\b(?:post ?code|postal code|zip code)\b", re.I),
    "birth_year": re.compile(r"\b(?:birth year|year (?:were|was) you born|what year.{0,12}born)\b", re.I),
}


def _accepted_identity_fields(transcript: Transcript, before: int) -> set[str]:
    fields: set[str] = set()
    for call in transcript.calls:
        if call.complete >= before or not call.success or not _tool_is(call.name, "verify_identity"):
            continue
        verified = _explicit_values(call.result, "verified") + _explicit_values(call.result, "accepted")
        if verified and not any(value is True for value in verified):
            continue
        field = str(_body(call).get("field") or "")
        if field:
            fields.add(field)
    return fields


def rule_r3(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Flag asking for an identity field already accepted by the verifier."""
    findings: list[Finding] = []
    for index, message in enumerate(transcript.messages):
        if message.get("role") != "assistant":
            continue
        text = _text(message)
        if "?" not in text and not re.search(r"\b(?:tell|confirm|provide|give|what|could|can)\b", text, re.I):
            continue
        accepted = _accepted_identity_fields(transcript, index)
        if any(field in accepted and pattern.search(text) for field, pattern in IDENTITY_QUESTIONS.items()):
            findings.append(_finding(transcript, index, "R3", text))
    return findings


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text) if part.strip()]


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _policy_keys(text: str, required: Sequence[str]) -> set[str]:
    normalized = _normalized(text)
    keys: set[str] = set()
    if re.search(r"\b(?:rest|remainder|remaining)\b.{0,55}\b(?:stay|stays|remain|remains|left|be)\b.{0,24}\b(?:overdue|outstanding|due)\b", normalized):
        keys.add("rest_overdue")
    if re.search(r"\b(?:minimum|lowest|floor)\b.{0,65}\b(?:amount|payment|offer|accept|record)\b", normalized):
        keys.add("floor_explanation")
    for index, sentence in enumerate(required):
        required_normalized = _normalized(sentence)
        if required_normalized and required_normalized in normalized:
            keys.add(f"required_{index}")
    policy_words = re.search(r"\b(?:overdue|outstanding|minimum|floor|deadline|latest date|cannot be recorded|business day|mobile app|text message confirming)\b", normalized)
    if policy_words and len(normalized.split()) >= 4:
        keys.add("exact_" + normalized)
    return keys


def rule_r4(transcript: Transcript, required: Sequence[str] = ()) -> list[Finding]:
    """Flag a policy clause repeated in later agent turns."""
    seen: set[str] = set()
    findings: list[Finding] = []
    for index, message in enumerate(transcript.messages):
        if message.get("role") != "assistant":
            continue
        text = _text(message)
        turn_keys: set[str] = set()
        for sentence in _sentences(text):
            turn_keys.update(_policy_keys(sentence, required))
        if turn_keys & seen:
            findings.append(_finding(transcript, index, "R4", text))
        seen.update(turn_keys)
    return findings


LEAK = re.compile(r"\{\{|\}\}|\{\s*[A-Za-z_][^{}]*\}|\b(?:None|null|NULL|undefined|UNDEFINED)\b")
BANK_DUPLICATE = re.compile(r"\bbank of\s+[A-Za-z][\w&'-]*(?:\s+[A-Za-z][\w&'-]*){0,2}\s+bank\b", re.I)


def rule_r5(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Flag unexpanded templates and obvious duplicated output."""
    findings: list[Finding] = []
    for index, message in enumerate(transcript.messages):
        if message.get("role") != "assistant":
            continue
        text = _text(message)
        sentences = [_normalized(item) for item in _sentences(text)]
        repeated = any(sentence and sentences.count(sentence) > 1 for sentence in sentences)
        if LEAK.search(text) or BANK_DUPLICATE.search(text) or repeated:
            findings.append(_finding(transcript, index, "R5", text))
    return findings


MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _date_present(text: str, expected: Any) -> bool:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(expected or ""))
    if not match:
        return False
    year, month, day = map(int, match.groups())
    if re.search(rf"\b{year:04d}-{month:02d}-{day:02d}\b", text):
        return True
    if re.search(rf"\b{day:01d}[/-]{month:01d}(?:[/-]{year:04d})?\b", text):
        return True
    if re.search(rf"\b{month:01d}[/-]{day:01d}(?:[/-]{year:04d})?\b", text):
        return True
    names = [name for name, number in MONTHS.items() if number == month]
    names_pattern = "|".join(names)
    if re.search(rf"\b{day}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{names_pattern})(?:\s+{year})?\b", text, re.I) \
            or re.search(rf"\b(?:{names_pattern})\s+{day}(?:st|nd|rd|th)?(?:,?\s+{year})?\b", text, re.I):
        return True
    weekday = date(year, month, day).strftime("%A")
    return bool(
        re.search(rf"\b{weekday}(?:\s+the)?\s+{day}(?:st|nd|rd|th)?\b", text, re.I)
        or re.search(rf"\b{day}(?:st|nd|rd|th)?(?:,?\s+on)?\s+{weekday}\b", text, re.I)
    )


def _without_dates(text: str) -> str:
    text = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", text)
    text = re.sub(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTH_PATTERN})(?:\s+\d{{4}})?\b", " ", text, flags=re.I)
    text = re.sub(rf"\b(?:{MONTH_PATTERN})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b", " ", text, flags=re.I)
    return text


def _amounts(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in re.finditer(r"(?<![\w])(?:[£$€]\s*)?(\d[\d,]*(?:\.\d{1,2})?)(?![\w])", _without_dates(text)):
        prefix = text[max(0, match.start() - 18) : match.start()].lower()
        if re.search(r"(?:ending|last four|last 4)\s*$", prefix):
            continue
        value = _decimal(match.group(1))
        if value is not None:
            values.append(value)
    return values


def _readback_candidate(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:to confirm|just to confirm|read back|check that|you(?:'ll| will) pay|payment of|promise (?:of|to pay|is for))\b",
            text,
            re.I,
        )
    )


def _readback_matches(text: str, body: dict[str, Any]) -> bool:
    amount = _decimal(body.get("amount"))
    date = body.get("date")
    return amount is not None and amount in _amounts(text) and _date_present(text, date)


def _nearest_readback(transcript: Transcript, before: int) -> tuple[int, str] | None:
    for index in range(before - 1, -1, -1):
        message = transcript.messages[index]
        if message.get("role") == "assistant" and _readback_candidate(_text(message)):
            return index, _text(message)
    return None


def rule_r6(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Flag a stated read-back that disagrees with create_promise arguments."""
    findings: list[Finding] = []
    for call in transcript.calls:
        if not _tool_is(call.name, "create_promise"):
            continue
        readback = _nearest_readback(transcript, call.start)
        if readback and not _readback_matches(readback[1], _body(call)):
            findings.append(_finding(transcript, readback[0], "R6", readback[1]))
    return findings


YES = re.compile(r"^\s*(?:yes|yeah|yep|correct|confirmed?|that's right|that is right|i agree|agreed|okay|ok)\b", re.I)


def rule_r7(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Require an amount/date read-back and customer yes before create_promise."""
    findings: list[Finding] = []
    for call in transcript.calls:
        if not _tool_is(call.name, "create_promise"):
            continue
        prior = [
            (index, message)
            for index, message in enumerate(transcript.messages[: call.start])
            if message.get("role") in {"assistant", "user"}
        ]
        valid = False
        if prior and prior[-1][1].get("role") == "user" and YES.search(_text(prior[-1][1])):
            assistant = next(
                ((index, message) for index, message in reversed(prior[:-1]) if message.get("role") == "assistant"),
                None,
            )
            valid = bool(assistant and _readback_matches(_text(assistant[1]), _body(call)))
        if not valid:
            rendered = json.dumps(_body(call), sort_keys=True, default=str)
            findings.append(_finding(transcript, call.start, "R7", f"create_promise {rendered}"))
    return findings


ROBOT_QUESTION = re.compile(
    r"\b(?:are you (?:a |an )?(?:bot|robot|ai|artificial intelligence|automated|digital assistant|human|real human|real person|machine)|"
    r"is this (?:a |an )?(?:bot|robot|ai|automated|digital assistant|machine)|"
    r"am i (?:talking|speaking) to (?:a |an )?(?:bot|robot|ai|digital assistant|human|real human|real person|machine))\b",
    re.I,
)


def rule_r8(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Require 'digital assistant' in the next reply to a bot question."""
    findings: list[Finding] = []
    for index, message in enumerate(transcript.messages):
        if message.get("role") != "user" or not ROBOT_QUESTION.search(_text(message)):
            continue
        response = next(
            ((reply_index, reply) for reply_index, reply in enumerate(transcript.messages[index + 1 :], index + 1) if reply.get("role") == "assistant"),
            None,
        )
        if not response or not re.search(r"\bdigital assistant\b", _text(response[1]), re.I):
            turn, text = (response[0], _text(response[1])) if response else (index, "<missing assistant response>")
            findings.append(_finding(transcript, turn, "R8", text))
    return findings


FAREWELL = re.compile(r"\b(?:goodbye|bye|farewell|take care|have a (?:good|nice|lovely) day|thank(?: you|s) for your time)\b", re.I)


def rule_r9(transcript: Transcript, _: Sequence[str] = ()) -> list[Finding]:
    """Require a farewell before close_call and silence afterwards."""
    findings: list[Finding] = []
    for call in transcript.calls:
        if not _tool_is(call.name, "close_call"):
            continue
        previous = next(
            ((index, message) for index, message in reversed(list(enumerate(transcript.messages[: call.start]))) if message.get("role") == "assistant"),
            None,
        )
        if not previous or not FAREWELL.search(_text(previous[1])):
            findings.append(_finding(transcript, call.start, "R9", f"close_call {json.dumps(_body(call), sort_keys=True, default=str)}"))
        for index, message in enumerate(transcript.messages[call.start + 1 :], call.start + 1):
            if message.get("role") == "assistant":
                findings.append(_finding(transcript, index, "R9", _text(message)))
    return findings


# Add a rule here; the CLI and library entry point will pick it up.
RULES: tuple[tuple[str, Rule], ...] = (
    ("R1", rule_r1), ("R2", rule_r2), ("R3", rule_r3),
    ("R4", rule_r4), ("R5", rule_r5), ("R6", rule_r6),
    ("R7", rule_r7), ("R8", rule_r8), ("R9", rule_r9),
)


def lint_export(data: dict[str, Any], required_sentences: Sequence[str] = ()) -> list[Finding]:
    transcript = parse_export(data)
    findings: list[Finding] = []
    for _, rule in RULES:
        findings.extend(rule(transcript, required_sentences))
    return sorted(findings, key=lambda item: (item.turn, item.rule, item.text))


def required_sentences(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    sentences: list[str] = []
    marker = re.compile(r"(?:required sentence|required wording|say exactly|must say)", re.I)
    for line in text.splitlines():
        direct = re.findall(r'(?<!not )\bsay(?: this sentence| the following sentence| exactly)?\s*:?\s*["“]([^"”]{8,})["”]', line, re.I)
        if direct:
            sentences.extend(item.strip() for item in direct)
            continue
        if not marker.search(line):
            continue
        quoted = re.findall(r'["“]([^"”]{8,})["”]', line)
        if quoted:
            sentences.extend(item.strip() for item in quoted)
            continue
        _, separator, remainder = line.partition(":")
        if separator and len(remainder.strip()) >= 8:
            sentences.append(remainder.strip().strip("`*_ "))
    return sentences


def _cell(value: Any, limit: int = 96) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def print_table(findings: Iterable[Finding]) -> None:
    rows = [(item.case, str(item.turn), item.rule, _cell(item.text)) for item in findings]
    headers = ("case", "turn index", "rule", "offending text")
    widths = [max(len(headers[column]), *(len(row[column]) for row in rows)) if rows else len(headers[column]) for column in range(4)]
    print(" | ".join(headers[column].ljust(widths[column]) for column in range(4)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(row[column].ljust(widths[column]) for column in range(4)))
    if not rows:
        print("(no findings)")


def _load_exports(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise ValueError(f"not a directory: {directory}")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ValueError(f"no JSON exports in {directory}")
    exports: list[dict[str, Any]] = []
    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            parse_export(value)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"{path}: {error}") from error
        exports.append(value)
    return exports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports_dir", type=Path)
    parser.add_argument("--brief", type=Path, help="brief containing exact required sentences")
    args = parser.parse_args(argv)
    try:
        required = required_sentences(args.brief) if args.brief else []
        findings = [finding for export in _load_exports(args.exports_dir) for finding in lint_export(export, required)]
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print_table(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
