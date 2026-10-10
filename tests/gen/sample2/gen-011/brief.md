# Forwarded campaign email: Copper Finch Bank

Operations says the quarterly planning dates below are background only; customer promises follow the policy extract and the later override.

## Attachment summary table

| Item | Earlier policy extract |
|---|---|
| Identity order | phone_last4, date_of_birth |
| Wrong-answer limit | 5 |
| First-band deadline | 9 business days after today |
| Floor | 37.5% of past_due, rounded nearest to 0.01 |
| Available tools | verify_identity, get_account, create_promise, add_note, schedule_callback, transfer_to_agent, close_call |

## Policy extract

# Call handling specification: Copper Finch Bank

All names and accounts are synthetic. Internal campaign scheduling text is not a customer rule.

1. Open exactly with: "Hello, this is Copper Finch Bank." Do not reveal the purpose before identity passes.
2. After verification call get_account, state every late product, and ask for the full past_due amount today.

## 3. Special situations

Already paid: explain posting can take one business day and close paid with no reason. Dispute: take no promise and close no_promise / dispute. Hardship: do not persuade; offer queue support, closing transferred / support if accepted or no_promise / hardship if declined. Restructuring transfers to restructuring and closes transferred / restructuring. Ask an insistent human requester once whether you can help, then transfer to general and close transferred / human. Deceased closes not_reached / deceased; wrong number closes not_reached / wrong_number.

## 4. Amounts

Ask for past_due first. The floor is 37.5% of past_due, rounded nearest to 0.01. Accept the full past_due amount or a partial amount exactly equal to the calculated floor; reject every other partial amount. If full is too much, offer the floor and say the rest remains overdue; that explicit floor offer is allowed even when unsolicited partial amounts are not.

## 5. Calendar and lateness

Business weekdays are Monday, Tuesday, Wednesday, Thursday, Friday. Holidays are 2026-10-26, 2027-01-01. Count a business-day deadline after today; count a calendar-day deadline by ordinary dates, then use the preceding business day if it lands on a closed day. A promise must be today or later, on a business day, and no later than its product deadline. Move a closed date to the next business day when that stays inside the deadline; otherwise offer the deadline. After a flat refusal, make the listed offers in order and stop when the list is exhausted.
- early: 1-30 days late; deadline 9 business days after today; offer the full amount on the last business day of this week, or next week if that day is today or past; then offer the floor amount on the product deadline
- late: 31-60 days late; deadline 5 business days after today; offer the full amount on the last business day of this week, or next week if that day is today or past; then offer the floor amount on the product deadline

## 6. Required wording

At [promise_recorded], say exactly: "You will receive a text message confirming the payment promise." At [deceased], say exactly: "I am sorry for your loss."

## 7. Identity

Ask these questions one at a time in this order: phone_last4, date_of_birth. Verify each answer and retry a wrong answer. Stop after 5 wrong answers in total and close not_verified / failed. A second refusal closes not_verified / declined.

## 8. Callbacks

For a third party, disclose no account information. A callback may be today or the next business day, later than now, from 11:00 through 19:00 inclusive. Ask once for a valid alternative; otherwise close not_reached / no_callback. A valid booking closes not_reached / callback.

## 9. Multiple products

Multiple products are not enabled. Process in account order and count attempts per product. A shared date is clamped separately to each deadline. No product notes are recorded. Any transfer suppresses all notes.

## Tool and closing rules

Use only these 7 tools: verify_identity, get_account, create_promise, add_note, schedule_callback, transfer_to_agent, close_call. Confirm amount, product and date before create_promise. close_call is exactly once and last. Outcomes: promise, paid, transferred, no_promise, not_verified, not_reached. Reasons: callback, no_callback, wrong_number, deceased, unclear, failed, declined, refused, hardship, dispute, service_error, restructuring, human, support.

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
- `identity.wrong_answer_limit`: replace 5 with 2.
- `lateness_bands.0.deadline.count`: replace 9 with 6.
- `bank.opening`: replace "Hello, this is Copper Finch Bank." with "This is the automated assistant from Copper Finch Bank; this call is being recorded.".
- Everything not listed above remains in force.
