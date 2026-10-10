# Harbourline Bank — multi-product collections extract (effective 2026-07-01)

Harbourline Bank is fictional. A customer may be late on one, two, or three products. Where a later memo conflicts with this extract, the memo wins. Wire values are never the words in this file: send the `api_value` from `codes.csv` for the surface form. An exact row is identity. An alias row is the only allowed translation. Do not guess a nearby enum member.

## Calendar

Business days are Monday to Friday.

Holidays:

- 2026-12-25
- 2026-12-26
- 2027-01-01

## Bands

| Days past due | Band | Latest promise date | Attempts |
|---|---|---|---|
| 1 to 10 | early | the 10th business day after today | 1 |
| 11 to 40 | late | the 6th business day after today | 2 |

A promise date must be today or later, a business day, and not after that product's deadline. The band is per product, from that product's `days_late`.

## Attempts plan

The assistant reads this plan. It does not assume a Friday from another bank's brief.

| Band | Step | Date rule | Amount rule |
|---|---|---|---|
| early | 1 | last business day of this week; if today is that day, last business day of next week | full past due, or the floor if they already said the full amount is too much |
| late | 1 | last business day of this week; if today is that day, last business day of next week | full past due, or the floor if they already said the full amount is too much |
| late | 2 | the deadline | the floor |

Saying the full amount is too much offers the floor once and does not use an attempt. A later flat refusal starts step 1.

## Floor

Credit card: `minimum_payment`. Personal loan or car loan: `instalment_amount`. Never ask how much they can pay.

## Identity

Ask the date of birth, then the last four digits of the phone number on file. Three wrong answers in total end the check. Send the date as `YYYY-MM-DD`. Send the phone answer as four digits. The field names are `date_of_birth` and `phone_last4`.

## Several products

State every late product, one sentence each, before asking for anything. First ask whether they can pay all of them today. If not, take the products in `get_account` order. Do not ask about today again. Each later product starts at step 1 of the plan.

One date for every product: if it is after one product's deadline, record that product on its own deadline and say so in the read-back. The others keep the named date.

Read every promise back together and ask "Do you confirm?" once. Then `create_promise` once per product, with `customer_id`, `product_id`, `amount` and `date`.

For each product with no promise, call `add_note` with `refused`, `hardship`, `dispute`, `paid` or `service_error`. A dispute or an already-paid claim on one product does not end the call. No notes at all if any transfer succeeded.

## Other closes

Job loss, illness, or a death in the family: one sentence of sympathy, no persuasion, offer the hardship desk. If they accept, transfer on the hardship_desk alias and close as transferred / support. If they decline, close as no_promise / hardship. If they still name a date or an amount, record it.

A new payment plan or lower instalments: transfer to `restructuring`. Do not describe a plan. Promises already saved stay. Promises not yet confirmed are not saved. No notes on that transfer.

A request for a person: ask once whether you can help first. If they insist, transfer to `general` and close on the human row in codes.csv.

"I already paid" this past-due amount: say a payment can take one business day to appear. On one product, note `paid` and continue. If every product is paid and none is promised, close on the paid row.

After `create_promise` returns ok true, say exactly: "You will receive a text message confirming this promise."

Two failures of `create_promise` on one product: note `service_error` for that product and keep the others.
