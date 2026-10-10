--- email.md ---
Subject: campaign hand-off / please configure

Team,
Use the attached policy for Mosaic Bank. Start calls with: "Hello, this is Mosaic Bank."
The board meeting moved to Thursday; that scheduling note is unrelated to customer promises. The seven API actions remain verify_identity, get_account, create_promise, add_note, schedule_callback, transfer_to_agent, close_call.
Thanks,
Operations

--- policy-extract.md ---
# POLICY EXTRACT: Mosaic Bank

All names and accounts are synthetic. Internal campaign scheduling text is not a customer rule.

1. Open exactly with: "Hello, this is Mosaic Bank." Do not reveal the purpose before identity passes.
2. After verification call get_account, state every late product, and ask for the full past_due amount today.

## 3. Special situations

Already paid: explain posting can take one business day and close paid with no reason. Dispute: take no promise and close no_promise / account_dispute. Hardship: do not persuade; offer queue general, closing transferred / support if accepted or no_promise / financial_difficulty if declined. Restructuring transfers to support and closes transferred / restructuring. Ask an insistent human requester once whether you can help, then transfer to restructuring and close transferred / human. Deceased closes not_reached / deceased; wrong number closes not_reached / wrong_number.

## 4. Callbacks

For a third party, disclose no account information. A callback may be today or the next business day, later than now, from 08:00 through 17:00 inclusive. Ask once for a valid alternative; otherwise close not_reached / no_callback. A valid booking closes not_reached / callback.

## 5. Required wording

At [promise_recorded], say exactly: "A confirmation of this promise will be sent to you by text message." At [deceased], say exactly: "I am sorry for your loss."

## 6. Identity

Ask these questions one at a time in this order: date_of_birth, phone_last4. Verify each answer and retry a wrong answer. Stop after 4 wrong answers in total and close not_verified / failed. A second refusal closes not_verified / declined.

## 7. Multiple products

Multiple products are enabled, up to 3. Process in account order and count attempts per product. A shared date is clamped separately to each deadline. For paid, dispute, hardship, service error or exhausted refusals on one product, add the matching note and continue; if any promise is recorded it wins, while all-paid closes paid and otherwise the first non-paid product reason wins. Any transfer suppresses all notes.

## 8. Calendar and lateness

Business weekdays are Monday, Tuesday, Wednesday, Thursday, Friday. Holidays are 2026-10-19, 2026-11-27, 2026-12-25. Count a business-day deadline after today; count a calendar-day deadline by ordinary dates, then use the preceding business day if it lands on a closed day. A promise must be today or later, on a business day, and no later than its product deadline. Move a closed date to the next business day when that stays inside the deadline; otherwise offer the deadline. After a flat refusal, make the listed offers in order and stop when the list is exhausted.
- early: 1-20 days late; deadline 9 calendar days after today; offer the full amount on 4 calendar days after today; then offer the floor amount on the last business day of this week, or next week if that day is today or past
- late: 21-60 days late; deadline 4 calendar days after today; offer the floor amount on 5 business days after today; then offer the floor amount on 6 calendar days after today

## 9. Amounts

Ask for past_due first. The floor is the account's minimum_payment for cards and instalment_amount for loans. Customer-proposed amounts are accepted from full through past_due, including both ends. If full is too much, offer the floor and say the rest remains overdue; that explicit floor offer is allowed even when unsolicited partial amounts are not.

## Tool and closing rules

Use only these seven tools: verify_identity, get_account, create_promise, add_note, schedule_callback, transfer_to_agent, close_call. Confirm amount, product and date before create_promise. close_call is exactly once and last. Outcomes: promise, paid, transferred, no_promise, not_verified, not_reached. Reasons: callback, no_callback, wrong_number, deceased, unclear, failed, declined, no_commitment, financial_difficulty, account_dispute, service_error, restructuring, human, support.

--- later-memo.md ---
Subject: LATER MEMO — effective immediately

This memo takes precedence over the email and policy extract where they conflict.
- Replace `bank.opening` with `I am the virtual assistant for Mosaic Bank, calling on a recorded line.` (the earlier value `Hello, this is Mosaic Bank.` is withdrawn).
- Replace `callback_window.start` with `11:00` (the earlier value `08:00` is withdrawn).
- Replace `lateness_bands.0.deadline.count` with `6` (the earlier value `9` is withdrawn).
Everything not named above remains unchanged.

--- codes.csv ---
kind,semantic,alias,canonical
outcome,promise,PROMISE,promise
outcome,paid,SETTLED,paid
outcome,transferred,HANDOFF,transferred
outcome,no_promise,NO_DEAL,no_promise
outcome,not_verified,ID_STOP,not_verified
outcome,not_reached,NO_CONTACT,not_reached
queue,restructuring,RESTRUCTURING_DESK,support
queue,general,GENERAL_DESK,restructuring
queue,support,SUPPORT_DESK,general
note_reason,refused,REFUSED_NOTE,refused
note_reason,hardship,HARDSHIP_NOTE,hardship
note_reason,dispute,DISPUTE_NOTE,dispute
note_reason,paid,PAID_NOTE,paid
note_reason,service_error,SERVICE_ERROR_NOTE,service_error
