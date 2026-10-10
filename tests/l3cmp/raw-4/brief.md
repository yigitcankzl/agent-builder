# Rowan Mutual — sources pasted into one file

Rowan Mutual is fictional. Each customer in this pack is late on one product. The practice customers keep the identity and the balance the mock already has.

## Source: email from dialler ops

From: dialler-ops@rowanmutual.example
To: builder@rowanmutual.example
Date: Thu, 1 Oct 2026 09:00:00 +0000
Subject: How the call starts

The greeting is fixed. Say "This is Rowan Mutual. This call is recorded." Then ask, in these words, "Am I speaking with {title} {last_name}?" Do not say collections, debt, payment, or a product before identity is verified. Only yes, that's me, speaking, or their own name counts as the customer.

Ask for the date of birth, then the last four digits of the phone number on file. The fields are date_of_birth, then phone_last4. One wrong answer does not end the check. Three wrong answers do. Close not_verified with reason failed, do not state the account, and tell them "Please use the app or visit a branch." A second refusal to answer those questions closes not_verified with reason declined.

Someone who is not the customer, including a husband, wife, or other relative, does not answer security questions and is not told the balance, the product, or the amount. Ask when the customer can be reached. A callback is today or the next business day, from 10:00 to 18:00, both included, and later than now. Schedule that time and close not_reached with reason callback. If they will not give a time inside that window, do not schedule, and close not_reached with reason no_callback. Do not call verify_identity when the customer is not on the line.

This mailbox does not set deadlines, holidays, or the floor.

## Source: email from credit policy

From: Credit policy <policy@rowanmutual.example>
To: collections@rowanmutual.example
Date: Sat, 3 Oct 2026 11:20:00 +0000
Subject: Deadlines and what you say when a promise is saved

Business days are Monday to Friday. Today does not count in either deadline below. The holidays are Friday 16 October 2026, 25 December 2026, 26 December 2026, and 1 January 2027. Monday 26 October 2026 is not a holiday.

A product that is 1 to 10 days past due is early. It has one attempt. Its latest promise date is the 4th business day after today. Count Monday to Friday and skip weekends and holidays.

A product that is 11 to 40 days past due is late. It has two attempts. Its latest promise date is the 2nd calendar day after today. Count every calendar day, including weekends and holidays. The promise itself still has to be a business day. When that calendar day is a weekend or a holiday, the latest promise date is the previous business day.

From Wednesday 14 October 2026, the 2nd calendar day is Friday 16 October 2026. That Friday is a holiday, so it falls on the late deadline, and the latest late promise date is the previous business day, Thursday 15 October 2026. The business days after today are Thursday 15 October, Monday 19 October, Tuesday 20 October, and Wednesday 21 October. The 4th business day is Wednesday 21 October 2026. The next business day after Friday 16 October 2026 is Monday 19 October 2026.

A promise is today or later, a business day, and not after that product's deadline. Ask for the full past_due. Never ask how much they can pay. Accept the full past_due, or the exact floor once they have said the full amount is too much. No other amount. If they say the full amount is too much, offer the floor once, on the deadline. That offer does not use an attempt. The number of the floor is not in this email. Use the latest floor instruction.

A date they name that is a business day on or before the deadline does not use an attempt. A weekend or a holiday that is not after the deadline moves to the next business day, and you say so. A date after the deadline is answered by offering the full past_due on the deadline. A flat no, with no date and no amount, uses an attempt. Early has no second attempt. On the late band the second attempt is the floor on the deadline. When the attempts are used up, close no_promise with reason refused.

If they say they cannot pay anything because of hardship, do not start those attempts and do not offer the floor. Say one sentence of sympathy. Offer the support queue once. If they decline, close no_promise with reason hardship. Do not offer a discount or a waiver.

If they want a new plan or lower instalments, transfer to the restructuring queue. Do not describe a plan. Do not record a promise. Close transferred with reason restructuring.

If they say the product is already paid, do not record a promise. Tell them "Payments can take one business day to appear." Close paid with no reason.

Read the promise back and ask, in these words, "Do you confirm?" After create_promise succeeds, say, in these words, "A confirmation email will be sent to the address on file." If create_promise fails, call it once more with the same amount and date. Close with one close_call, and make it the last tool. promise and paid have no reason. Do not call add_note.

Customers often get paid on the 5th, and a promise dated the 5th looks tidy on a report. This paragraph sets no rule. Do not offer the 5th, and do not prefer the 5th, because of payday. A date on the 5th is judged only by the deadline rules above.

## Source: chat, #collections-policy

**Sam Adeyemi** — 2026-10-06T09:02:14

Floor for every product: the floor is 50 percent of past_due, rounded half up to the penny. Use that instead of the minimum or the instalment.

## Source: email that replaces the floor

From: Head of credit <head.credit@rowanmutual.example>
To: collections@rowanmutual.example
Date: Fri, 9 Oct 2026 15:10:00 +0100
Subject: Authoritative floor

This email is authoritative. It replaces the floor in Sam Adeyemi's chat of 6 October 2026. The 50 percent figure is withdrawn. The floor is 30 percent of past_due, rounded half up to the penny. 2125.10 has a floor of 637.53. Do not use 50 percent. Do not use minimum_payment or instalment_amount as the floor. Everything else in the 1 October and 3 October emails still stands, including Thursday 15 October 2026 as the late deadline and Wednesday 21 October 2026 as the early deadline.
