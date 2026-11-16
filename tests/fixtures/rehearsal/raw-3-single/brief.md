# Lark Credit — sources pasted into one file

Lark Credit is fictional. A customer may be late on one, two, or three products. The practice customers keep the identity and the balances the mock already has.

## Source: handbook extract

From: I. Rahman, Credit policy
Date: Wed, 15 Jul 2026 08:30:00 +0000
Subject: Lark Credit collections handbook

Say you are calling from Lark Credit and that the call is recorded. Do not say collections, debt, payment or a product before identity is verified. Ask "Am I speaking with {title} {last_name}?"

Date of birth first, then the last four digits of the phone number. Three wrong answers end the check as not verified, failed, and the account is not stated. A second refusal to answer is not verified, declined.

Business days are Monday to Friday. Today does not count. Skip weekends and the holidays below.

Holidays:

- 2026-12-25
- 2026-12-26
- 2027-01-01

State every late product, one sentence each, then ask whether they can pay all of them today. If not, go through the products in the order get_account returned them. Do not ask about today again for each product. Each product starts at attempt 1.

A promise has to be today or later, a business day, and not after that product's deadline. If they name a weekend or a holiday that is not after the deadline, offer the next business day. If the named day is after the deadline, say the latest date is the deadline and offer the full balance on it.

Ask for the full past-due amount. Never ask how much they can pay. If the full amount is too much, offer the floor once, on that product's deadline. That offer does not use an attempt.

Attempt 1 is the full balance on the deadline. Attempt 2, late band only, is the floor on the deadline. A flat no with no date and no amount uses an attempt. A date they name that is a business day on or before the deadline does not use an attempt.

One date for every product. If it is not a business day, move it to the next business day when that day is on or before the product's deadline, and say so. If it is past a product's deadline, that product is recorded on its own deadline.

Read every promise back together. Ask "Do you confirm?" once. Then create_promise once per product. For each product with no promise, add a note: refused, hardship, dispute, paid or service_error. No notes at all if the call is transferred.

Close with one close_call, last. promise has no reason. no_promise uses refused when the attempts are used up.

| Days past due | Band | Latest promise date | Attempts | Floor |
|---|---|---|---|---|
| 1 to 10 | early | the 12th business day after today | 1 | minimum_payment or instalment_amount |
| 11 to 40 | late | the 7th business day after today | 2 | minimum_payment or instalment_amount |

The band is per product, from that product's days_late.

**Superseded on 1 September 2026. Do not use this paragraph.**

After a successful create_promise, say "You will receive a text message confirming this promise."

## Source: ops chat, in passing

**Nia Okonkwo** — 2026-10-02T14:22:11

Jordan is covering the late queue on Monday because I am at the dentist, and someone keeps taking mugs from the kitchen. Tuesday 20 October 2026 the branch is shut, so count that Tuesday as a holiday when you count business days. Bring your own mug.

## Source: HR weekly — not a collections rule

From: People team <hr@larkcredit.example>
To: all-staff@larkcredit.example
Date: Mon, 5 Oct 2026 09:00:00 +0000
Subject: Roof picnic

The all-hands picnic is Friday 16 October 2026 on the roof. Dress code is smart casual. This HR note does not add a holiday and does not change any collections rule, deadline, or amount.

## Source: email that replaces the handbook table

From: Mira Shah <mira.shah@larkcredit.example>
To: collections@larkcredit.example
Subject: Handbook table of 15 July
Date: Fri, 9 Oct 2026 11:05:00 +0100

Where this note conflicts with the 15 July handbook, this note wins. It does not cancel Nia Okonkwo's holiday sentence of 2 October. The HR picnic note is not a collections rule.

The latest-promise-date cells in the handbook table are withdrawn. Do not use the 12th business day or the 7th business day. The early deadline is the 5th business day after today. The late deadline is the 3rd business day after today. The attempt counts in the table stay 1 early and 2 late.

Business-day counts use the holidays already in force, including the one in the 2 October note. From Wednesday 14 October 2026, the 3rd business day after today is Monday 19 October 2026. The 5th is Thursday 22 October 2026.

The floor column in that table is withdrawn. The floor is 40 percent of past_due, rounded half up to the penny. Do not use minimum_payment or instalment_amount as the floor. Offer that floor on the product's deadline when the full amount is too much. It does not use an attempt.

Do not use the superseded paragraph about a text message. After a successful promise, say "A confirmation email will be sent to the address on file."

Everything else in the 15 July handbook still applies.

Mira Shah
