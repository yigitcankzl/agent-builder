# Forwarded campaign email: Mosaic Bank

Operations says the quarterly planning dates below are background only; customer promises follow the policy extract and the later override.

## Attachment summary table

| Item | Earlier policy extract |
|---|---|
| Identity order | phone_last4, date_of_birth |
| Wrong-answer limit | 4 |
| First-band deadline | 7 business days after today |
| Floor | a fixed 20.00 |
| Available tools | verify_identity, get_account, create_promise, add_note, schedule_callback, close_call |

## Policy extract

# Call handling specification: Mosaic Bank

All names and accounts are synthetic. Internal campaign scheduling text is not a customer rule.

1. Open exactly with: "I am the virtual assistant for Mosaic Bank, calling on a recorded line." Do not reveal the purpose before identity passes.
2. After verification call get_account, state every late product, and ask for the full past_due amount today.

## 3. Special situations

Already paid closes paid with no reason. Dispute closes no_promise / dispute. The API has no transfer operation: hardship, restructuring, and a human request close no_promise with reasons hardship, restructuring, and human respectively; never invent a transfer. Deceased closes not_reached / deceased; wrong number closes not_reached / wrong_number.

## 4. Identity

Ask these questions one at a time in this order: phone_last4, date_of_birth. Verify each answer and retry a wrong answer. Stop after 4 wrong answers in total and close not_verified / failed. A second refusal closes not_verified / declined.

## 5. Required wording

At [promise_recorded], say exactly: "A confirmation of this promise will be sent to you by text message." At [deceased], say exactly: "Please accept my condolences."

## 6. Calendar and lateness

Business weekdays are Monday, Tuesday, Wednesday, Thursday, Friday, Saturday. Holidays are 2026-10-26, 2026-11-11, 2026-11-27. Count a business-day deadline after today; count a calendar-day deadline by ordinary dates, then use the preceding business day if it lands on a closed day. A promise must be today or later, on a business day, and no later than its product deadline. Move a closed date to the next business day when that stays inside the deadline; otherwise offer the deadline. After a flat refusal, make the listed offers in order and stop when the list is exhausted.
- early: 1-5 days late; deadline 7 business days after today; offer the full amount on 6 business days after today
- mid: 6-15 days late; deadline 5 business days after today; offer the floor amount on the product deadline; then offer the floor amount on 4 business days after today
- late: 16-60 days late; deadline 6 business days after today; offer the floor amount on 2 business days after today

## 7. Amounts

Ask for past_due first. The floor is a fixed 20.00. Customer-proposed amounts are accepted from floor through past_due, including both ends. If full is too much, offer the floor and say the rest remains overdue; that explicit floor offer is allowed even when unsolicited partial amounts are not.

## 8. Multiple products

Multiple products are not enabled. Process in account order and count attempts per product. A shared date is clamped separately to each deadline. No product notes are recorded. Any transfer suppresses all notes.

## 9. Callbacks

For a third party, disclose no account information. A callback may be today or the next business day, later than now, from 11:00 through 19:00 inclusive. Ask once for a valid alternative; otherwise close not_reached / no_callback. A valid booking closes not_reached / callback.

## Tool and closing rules

Use only these 6 tools: verify_identity, get_account, create_promise, add_note, schedule_callback, close_call. Tool field names are create_promise: amount→pledged_amount, date→due_on; close_call: outcome→disposition, reason→reason_code. Confirm amount, product and date before create_promise. close_call is exactly once and last. Outcomes: promise, paid, transferred, no_promise, not_verified, not_reached. Reasons: callback, no_callback, wrong_number, deceased, unclear, failed, declined, refused, hardship, dispute, service_error, restructuring, human, support.

## codes.csv (authoritative literal values)

```csv
group,semantic,literal
outcomes,promise,promise
outcomes,paid,paid
outcomes,transferred,transferred
outcomes,no_promise,no_promise
outcomes,not_verified,not_verified
outcomes,not_reached,not_reached
reasons,callback,callback
reasons,no_callback,no_callback
reasons,wrong_number,wrong_number
reasons,deceased,deceased
reasons,unclear,unclear
reasons,failed,failed
reasons,declined,declined
reasons,refused,refused
reasons,hardship,hardship
reasons,dispute,dispute
reasons,service_error,service_error
reasons,restructuring,restructuring
reasons,human,human
reasons,support,support
note_reasons,refused,refused
note_reasons,hardship,hardship
note_reasons,dispute,dispute
note_reasons,paid,paid
note_reasons,service_error,service_error
queues,restructuring,restructuring
queues,general,general
queues,support,support
```

## LATER OVERRIDE MESSAGE — effective immediately

This message wins over every earlier email, table, and policy sentence where they conflict.
- `lateness_bands.0.deadline.count`: replace 7 with 4.
- Everything not listed above remains in force.
