# Sable Mutual — sources pasted into one file

## Source: meeting notes, 1 October 2026, 10:00

Speakers: Alex (policy), Dana (dialler)

Alex: This is the July pack for Sable Mutual. Up to three products. The practice customers keep the identity and the balances the mock already has.

Dana: What do we say at the start?

Alex: Say you are calling from Sable Mutual and that the call is recorded. Do not say collections, debt, payment or a product before identity is verified. Ask "Am I speaking with {title} {last_name}?"

Dana: Identity?

Alex: Date of birth first, then the last four digits of the phone number. Three wrong answers end it as not verified, failed, and we do not state the account. A second refusal to answer is not verified, declined.

Dana: After that?

Alex: State every late product, one sentence each, then ask whether they can pay all of them today. If not, go through the products in the order get_account returned them. Do not ask about today again for each product. Each product starts at attempt 1.

Dana: Deadlines. Count business days after today. Today does not count. Monday to Friday. Holidays are only 25 December 2026, 26 December 2026 and 1 January 2027.

Alex: One to ten days late is the early band. The deadline is the 9th business day after today. One attempt. Eleven to forty days late is the late band. The deadline is the 6th business day after today. Two attempts.

Dana: A promise has to be today or later, a business day, and not after that product's deadline. If they name a weekend or a holiday that is not after the deadline, offer the next business day. If the named day is after the deadline, say the latest date is the deadline and offer the full balance on it.

Alex: Amounts. Ask for the full past-due amount. Never ask how much they can pay. The floor is minimum_payment on a card and instalment_amount on a loan. If the full amount is too much, offer the floor once, on that product's deadline. That offer does not use an attempt.

Dana: Attempt 1 is the full balance on the deadline. Attempt 2, late band only, is the floor on the deadline. A flat no with no date and no amount uses an attempt. A date they name that is a business day on or before the deadline does not use an attempt.

Alex: One date for every product. If it is not a business day, move it to the next business day when that day is on or before the product's deadline, and say so. If it is past a product's deadline, that product is recorded on its own deadline.

Dana: Read every promise back together. Ask "Do you confirm?" once. Then create_promise once per product. For each product with no promise, add a note: refused, hardship, dispute, paid or service_error. A dispute or an already-paid claim on one product does not end the call. No notes at all if the call is transferred.

Alex: After a successful create_promise, say "You will receive a text message confirming this promise." The word we use in the office for a recorded promise is arranged. The code list says what to send the API.

Dana: Close with one close_call, last. promise has no reason. no_promise uses refused when the attempts are used up.

## Source: Slack export, #collections-policy

**Dana** — 2026-10-06T09:14:00

Update on the 1 October meeting. Monday 19 October 2026 is now a Sable Mutual holiday. Please add it to the holiday list.

**Alex** — 2026-10-06T09:16:22

Also change two rules from that meeting. The late deadline is the 3rd business day after today, not the 6th. The floor is 40 percent of past_due, half up to the penny, not the minimum or the instalment. Early band stays the 9th business day. The text-message sentence stays.

**Dana** — 2026-10-06T09:18:01

Noted. I will mail legal so they can confirm.

## Source: email thread, reply of 9 October 2026

From: Legal <legal@sable-mutual.example>
To: Dana <dana@sable-mutual.example>
Subject: Re: Slack update of 6 October
Date: Fri, 9 Oct 2026 16:40:00 +0100
Message-ID: <sable-2026-10-09@sable-mutual.example>
In-Reply-To: <dana-2026-10-06@sable-mutual.example>

Dana,

This reply replaces the two Slack rules you quoted. Where this note conflicts with the 6 October Slack messages or the 1 October meeting, this note wins. The holiday is the one part of the Slack note that still stands.

You wrote:

> The late deadline is the 3rd business day after today, not the 6th. The floor is 40 percent of past_due, half up to the penny, not the minimum or the instalment.

Both of those sentences are withdrawn. Do not use them.

The late deadline is the 2nd business day after today, not the 3rd and not the 6th. The early deadline is the 4th business day after today, not the 9th. Attempt counts stay 1 early and 2 late.

The floor is 30 percent of past_due, rounded half up to the penny. 2125.10 has a floor of 637.53. 1320 has a floor of 396.00. Offer that floor on the product's deadline when the full amount is too much. It does not use an attempt. The minimum and the instalment are not the floor.

Monday 19 October 2026 remains a holiday, as the Slack note said. The other holidays stay 25 December 2026, 26 December 2026 and 1 January 2027.

From Wednesday 14 October 2026 the business days after today run Thursday 15 October, Friday 16 October, Tuesday 20 October, Wednesday 21 October. The 2nd business day after today is Friday 16 October 2026. The 4th is Wednesday 21 October 2026. The next business day after Monday 19 October 2026 is Tuesday 20 October 2026.

Replace the text-message sentence. After a successful promise, say "A confirmation email will be sent to the address on file."

Everything else in the 1 October meeting still applies, including one date for every product, notes on products with no promise, and no notes after a transfer.

Legal

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
dispute,add_note.reason,dispute,exact
paid,add_note.reason,paid,exact
callback,close_call.reason,callback,exact
no_callback,close_call.reason,no_callback,exact
```
