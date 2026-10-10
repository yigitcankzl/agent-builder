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
