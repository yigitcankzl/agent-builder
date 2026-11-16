# raw-2

Frozen answer key. Sable Mutual, up to three products. Identity, products, amounts and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file.

Four sources, in date order:

| File | What it is |
|---|---|
| `meeting-2026-10-01.txt` | Speaker turns. The base pack, including the 9th and 6th business days, the account-field floor, and the text-message sentence |
| `slack-export.json` | Slack messages of 6 October. Adds Monday 19 October 2026 as a holiday, and sets a 3rd-business-day late deadline and a 40 percent floor |
| `email-thread.eml` | A reply of 9 October. It quotes those two Slack sentences and withdraws them |
| `codes.csv` | `arranged` maps to the kit outcome `promise` |

The 9 October email wins. The holiday from Slack still stands. The late deadline is the 2nd business day, Friday 16 October 2026. The early deadline is the 4th, Wednesday 21 October 2026. The floor is 30 percent of `past_due`. 2125.10 becomes 637.53, not 637.50. 1320 becomes 396.00. The saved sentence is "A confirmation email will be sent to the address on file."

`cases.json` holds PUB-11, PUB-12, PUB-13, PUB-04, PUB-06 and PUB-07. `cases-surface.json` repeats three ids. Run the files separately. Do not pass `--style`. The `brief` field is `B` on every row, including the one-product customers.

## What changed from Brief A

| Rule | Brief A | Sable, after the email |
|---|---|---|
| Products | one | up to three, in `get_account` order |
| Holidays | 26 October | 19 October. 26 October is a business day |
| Early | 12th business day | 4th business day, Wednesday 21 October |
| Late | 7th business day | 2nd business day, Friday 16 October |
| Floor | the account field | 30 percent. 2125.10 → 637.53 |
| Notes | never | one note for each product with no promise |
| Saved sentence | text message | the email sentence. The meeting's text-message sentence is withdrawn |
| Outcome word | `promise` | the meeting says `arranged`; the code list sends `promise` |

The Slack late deadline of the 3rd business day, and its 40 percent floor, are the quoted text in the email. They are not the rule.

## Which case tests which rule

| Case | Rule | Ledger |
|---|---|---|
| PUB-11 | One Monday for all three. 19 October is a holiday, so all three move to 20 October. All are inside the early deadline | 220, 640 and 75 on 2026-10-20. No notes |
| PUB-12 | The card date tomorrow stays 15 October. The loan floor is 396 on the late deadline 16 October. The car is refused | promises on p1 and p2. Note `refused` on p3 |
| PUB-13 | 30 October is past both deadlines. The card clamps to 21 October. The loan clamps to 16 October | 300 on 2026-10-21, 900 on 2026-10-16 |
| PUB-04 | One late product. The email deadline is 16 October, not 23 October | 1250 on 2026-10-16 |
| PUB-06 | The floor is 637.53, not 637.50, on 16 October | 637.53 on 2026-10-16 |
| PUB-07 | 26 October is a business day and is after the early deadline, so the recorded day is 21 October. Brief A recorded the 27th because 26 October was a holiday | 540 on 2026-10-21 |

## Surface siblings

| Case | Style | Same ledger |
|---|---|---|
| PUB-11 | Monday in words | the three promises on 2026-10-20 |
| PUB-13 | says the 23rd, then corrects to the 30th | 300 on 2026-10-21 and 900 on 2026-10-16 |
| PUB-06 | the balance split across two turns | 637.53 on 2026-10-16 |

None of the ledgers are debatable. The email states the 2nd, the 4th, the Tuesday after the holiday, and the two penny amounts.
