# Pebble Mutual — sources pasted into one file

## Source: email from dialler ops

From: dialler-ops@pebblemutual.example
To: builder@pebblemutual.example
Subject: Pebble Mutual multi-product dialler
Date: Wed, 01 Jul 2026 09:00:00 +0000

Pebble Mutual is fictional.

Opening. First sentence: you are a digital assistant calling from Pebble Mutual, and the call is recorded. Do not say "collections", "debt" or "payment" before identity is verified.

Then ask exactly: Am I speaking with {title} {last_name}?

Only yes, that's me, speaking, or their own name counts. If it is still unclear, use the unclear row in codes.csv.

Callback. Today or the next business day, from 10:00 to 18:00, both included, and later than now. Then close with the callback row in codes.csv. A time outside that window: ask once more. If that is also outside, do not schedule.

Wrong number and deceased use the rows in codes.csv. Deceased: say "I am sorry for your loss." and ask nothing else.

A relative may not answer security questions and may not be told the balance.

This email does not change bands, holidays, or the confirmation sentence.

## Source: policy extract, effective 2026-07-01

# Pebble Mutual — multi-product collections extract (effective 2026-07-01)

Pebble Mutual is fictional. A customer may be late on one, two, or three products. A later memo wins where it conflicts with this extract. Send the `api_value` from `codes.csv`. An alias row is the only allowed translation. Do not guess a nearby enum member.

## Calendar

Business days are Monday to Friday.

Holidays:

- 2026-12-25
- 2026-12-26
- 2027-01-01

Monday 26 October 2026 is not on this list.

## Bands

| Days past due | Band | Latest promise date | Attempts |
|---|---|---|---|
| 1 to 10 | early | the 8th business day after today | 1 |
| 11 to 40 | late | the 6th business day after today | 2 |

The band is per product, from that product's `days_late`. A promise date is today or later, a business day, and not after that product's deadline.

## Floor

The floor is 50 percent of `past_due`, rounded half up to the penny. `minimum_payment` and `instalment_amount` are not the floor.

Worked examples: 2125.10 past due has a floor of 1062.55. 1320.00 past due has a floor of 660.00.

If they say the full amount is too much, offer the floor once, on that product's deadline. That offer does not use an attempt. Never ask how much they can pay.

## Attempts

| Band | Step | Date rule | Amount rule |
|---|---|---|---|
| early | 1 | last business day of this week; if today is that day, last business day of next week | full past due, or the floor if they already said the full amount is too much |
| late | 1 | last business day of this week; if today is that day, last business day of next week | full past due, or the floor if they already said the full amount is too much |
| late | 2 | the deadline | the floor |

A date or an amount they propose is never a refusal. A flat refusal uses one attempt. Do not assume a Friday from another bank's brief.

## Identity

Ask the date of birth, then the last four digits of the phone number on file. Three wrong answers end the check. One wrong answer does not. Fields: `date_of_birth`, then `phone_last4`.

## Several products

State every late product, then ask whether they can pay all of them today. If they name one date for every product, do not start the per-product plan. If that date is not a business day, move it to the next business day and say so. If it is after one product's deadline, record that product on its own deadline and say so. The others keep the named date, after the business-day move.

Otherwise take the products in `get_account` order. Each later product starts at step 1. A date they name for the current product is accepted when it is a business day on or before that product's deadline. It does not use an attempt.

Read every promise back together and ask "Do you confirm?" once. Then `create_promise` once per product, with `customer_id`, `product_id`, `amount` and `date`.

For each product with no promise, call `add_note` with `refused`, `hardship`, `dispute`, `paid` or `service_error`. No notes if any transfer succeeded.

## Other closes

A new plan or lower instalments: transfer to `restructuring`. Promises already saved stay. No notes on that transfer.

After a successful `create_promise`, say exactly: "You will receive a text message confirming this promise."

When any promise was saved, the outcome surface form is `arranged`.

## Source: memo, 8 October 2026

# Pebble Mutual memo 2026-10-08

This memo supersedes the 2026-07-01 policy extract wherever the two conflict. The operations email remains in force where this memo is silent.

## Holiday

Add 16 October 2026 to the holiday list. Business-day counts skip weekends and this holiday. Monday 26 October 2026 remains a business day.

From Wednesday 14 October 2026 the business days after today are Thursday 15 October, Monday 19 October, Tuesday 20 October, Wednesday 21 October, Thursday 22 October, Friday 23 October, Monday 26 October, Tuesday 27 October.

The 4th business day after today is Wednesday 21 October 2026. The 8th is Tuesday 27 October 2026. The next business day after Friday 16 October 2026 is Monday 19 October 2026.

## Late deadline

For the late band (11 to 40 days past due), the latest promise date is now the 4th business day after today, not the 6th.

The early band stays the 8th business day after today. Attempt counts stay 1 early and 2 late.

## Confirmation sentence

Do not use the July sentence about a text message confirming this promise.

After a successful `create_promise`, say exactly:

A confirmation email will be sent to the address on file.

## Source: code list codes.csv

```csv
surface_form,api_field,api_value,mapping
arranged,close_call.outcome,promise,alias
paid_up,close_call.outcome,paid,alias
hardship_desk,transfer_to_agent.queue,support,alias
promise,close_call.outcome,promise,exact
paid,close_call.outcome,paid,exact
transferred,close_call.outcome,transferred,exact
no_promise,close_call.outcome,no_promise,exact
not_verified,close_call.outcome,not_verified,exact
not_reached,close_call.outcome,not_reached,exact
refused,close_call.reason,refused,exact
restructuring,transfer_to_agent.queue,restructuring,exact
callback,close_call.reason,callback,exact
no_callback,close_call.reason,no_callback,exact
```
