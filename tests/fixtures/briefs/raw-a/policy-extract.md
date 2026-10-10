# Freya Bank — Early Collections Policy Extract (effective 2026-07-01)

**Status:** superseded in part by Collections Memo 2026-10-01. Where the memo and this extract disagree, the memo controls.

Freya Bank is fictional. All figures and dates in examples are synthetic.

## Business calendar

Working days for deadline and promise dating are Monday through Friday.

Recognised bank holidays for 2026–2027 early-collections dating:

- 26 October 2026
- 11 November 2026
- 26 November 2026
- 25 December 2026
- 1 January 2027

## Lateness bands and payment deadlines

| Days past due | Band name | Latest promise date | Soft persuasion tries |
|---|---|---|---|
| 1–7 inclusive | early | 12 business days after the call date (`now`) | 1 |
| 8–45 inclusive | late | 7 business days after the call date (`now`) | 2 |

A promise date must be on or after `now`'s calendar date, must fall on a working day, and must not fall after the latest promise date for the band.

If the customer names a weekend or holiday that is still on or before the latest promise date, move them to the next working day. If they name a day after the latest promise date, tell them the latest date you can record is that deadline and offer it. Refusal of the deadline is a flat refusal.

Vague periods ("next week", "end of the month"): ask once for an exact day; if still vague, propose the deadline.

## Amount floor

- Credit card: floor equals the account field `minimum_payment`.
- Personal loan or car loan: floor equals the account field `instalment_amount`.

Always propose the full past-due amount first. Never ask the customer how much they can pay. If the full amount is too high, offer the floor once and note that the remainder stays overdue. Amounts from the floor up to the full past-due amount (inclusive) may be accepted.

## Persuasion sequence (flat refusal / non-answer)

A "no" to paying today with neither a date nor an amount is a flat refusal and consumes one try.

1. First try: propose the last working day of the current week (or of next week if today is already that day), for the full past-due amount — or for the floor if they already rejected the full amount.
2. Second try (late band only): propose the floor amount on the deadline date.

When tries are exhausted, close `no_promise` / `refused`. Do not re-offer a refused option.

## Identity (policy baseline)

Security check: date of birth, then last four digits of phone on file. Cap of three incorrect answers across both questions.

## Required customer-facing sentences (policy baseline)

On a successfully recorded promise, the agent must say:

> You will receive a text message confirming this promise.

## Closing outcomes (policy vocabulary)

Every call ends with one `close_call`. Outcome/reason pairs in use for early collections:

- promise (no reason) — at least one promise recorded
- paid (no reason) — customer asserts this past-due amount was already paid
- transferred — reasons restructuring | human | support
- no_promise — reasons refused | hardship | dispute | service_error
- not_verified — reasons failed | declined
- not_reached — reasons callback | no_callback | wrong_number | deceased | unclear

Brief A / early-stage dialler does not use `add_note`.
