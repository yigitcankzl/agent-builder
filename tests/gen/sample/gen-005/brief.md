--- email.md ---
Subject: campaign hand-off / please configure

Team,
Use the attached policy for Copper Finch Bank. Start calls with: "Hello, this is Copper Finch Bank."
The board meeting moved to Thursday; that scheduling note is unrelated to customer promises. The seven API actions remain verify_identity, get_account, create_promise, add_note, schedule_callback, transfer_to_agent, close_call.
Thanks,
Operations

--- policy-extract.md ---
# POLICY EXTRACT: Copper Finch Bank

All names and accounts are synthetic. Internal campaign scheduling text is not a customer rule.

1. Open exactly with: "Hello, this is Copper Finch Bank." Do not reveal the purpose before identity passes.
2. After verification call get_account, state every late product, and ask for the full past_due amount today.

## 3. Multiple products

Multiple products are enabled, up to 3. Process in highest_days_late order and count attempts per product. A shared date is clamped separately to each deadline. For paid, dispute, hardship, service error or exhausted refusals on one product, add the matching note and continue; if any promise is recorded it wins, while all-paid closes paid and otherwise the first non-paid product reason wins. Any transfer suppresses all notes.

## 4. Identity

Ask these questions one at a time in this order: date_of_birth, phone_last4. Verify each answer and retry a wrong answer. Stop after 5 wrong answers in total and close not_verified / security_failed. A second refusal closes not_verified / verification_declined.

## 5. Special situations

Already paid: explain posting can take one business day and close paid with no reason. Dispute: take no promise and close no_promise / account_dispute. Hardship: do not persuade; offer queue support, closing transferred / support if accepted or no_promise / hardship if declined. Restructuring transfers to restructuring and closes transferred / restructuring. Ask an insistent human requester once whether you can help, then transfer to general and close transferred / human. Deceased closes not_reached / deceased; wrong number closes not_reached / wrong_number.

## 6. Calendar and lateness

Business weekdays are Monday, Tuesday, Wednesday, Thursday, Friday. Holidays are 2026-10-19, 2026-10-26, 2026-11-11, 2027-01-01. Count a business-day deadline after today; count a calendar-day deadline by ordinary dates, then use the preceding business day if it lands on a closed day. A promise must be today or later, on a business day, and no later than its product deadline. Move a closed date to the next business day when that stays inside the deadline; otherwise offer the deadline. After a flat refusal, make the listed offers in order and stop when the list is exhausted.
- early: 1-7 days late; deadline 12 calendar days after today; offer the floor amount on the product deadline
- mid: 8-15 days late; deadline 8 business days after today; offer the floor amount on the last business day of this week, or next week if that day is today or past
- late: 16-60 days late; deadline 4 calendar days after today; offer the floor amount on the last business day of this week, or next week if that day is today or past; then offer the floor amount on 5 business days after today

## 7. Callbacks

For a third party, disclose no account information. A callback may be today or the next business day, later than now, from 11:00 through 19:00 inclusive. Ask once for a valid alternative; otherwise close not_reached / no_callback. A valid booking closes not_reached / callback.

## 8. Required wording

At [promise_recorded], say exactly: "You will receive a text message confirming the payment promise." At [deceased], say exactly: "Please accept my condolences."

## 9. Amounts

Ask for past_due first. The floor is the greater of 25.00 and 20% of past_due, with the percentage rounded nearest to 0.05. Customer-proposed amounts are accepted from full through past_due, including both ends. If full is too much, offer the floor and say the rest remains overdue; that explicit floor offer is allowed even when unsolicited partial amounts are not.

## Tool and closing rules

Use only these seven tools: verify_identity, get_account, create_promise, add_note, schedule_callback, transfer_to_agent, close_call. Confirm amount, product and date before create_promise. close_call is exactly once and last. Outcomes: promise, paid, transferred, no_promise, not_verified, not_reached. Reasons: callback, no_callback, wrong_number, deceased, unclear, security_failed, verification_declined, refused, hardship, account_dispute, service_error, restructuring, human, support.

--- later-memo.md ---
Subject: LATER MEMO — effective immediately

This memo takes precedence over the email and policy extract where they conflict.
- Replace `identity.wrong_answer_limit` with `2` (the earlier value `5` is withdrawn).
- Replace `bank.opening` with `This is the automated assistant from Copper Finch Bank; this call is being recorded.` (the earlier value `Hello, this is Copper Finch Bank.` is withdrawn).
Everything not named above remains unchanged.

--- codes.csv ---
kind,semantic,alias,canonical
outcome,promise,PROMISE,promise
outcome,paid,SETTLED,paid
outcome,transferred,HANDOFF,transferred
outcome,no_promise,NO_DEAL,no_promise
outcome,not_verified,ID_STOP,not_verified
outcome,not_reached,NO_CONTACT,not_reached
queue,restructuring,RESTRUCTURING_DESK,restructuring
queue,general,GENERAL_DESK,general
queue,support,SUPPORT_DESK,support
note_reason,refused,REFUSED_NOTE,refused
note_reason,hardship,HARDSHIP_NOTE,hardship
note_reason,dispute,DISPUTE_NOTE,dispute
note_reason,paid,PAID_NOTE,paid
note_reason,service_error,SERVICE_ERROR_NOTE,service_error
