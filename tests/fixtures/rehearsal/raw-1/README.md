# raw-1

Frozen answer key. Pebble Mutual, up to three products. The memo of 8 October wins over the July extract. Identity, products, amounts and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file. `codes.csv` maps the surface form `arranged` to the kit outcome `promise`. The ledgers use `promise`.

`cases.json` holds PUB-11, PUB-12, PUB-13, and the one-product cases PUB-04, PUB-06 and PUB-07. `cases-surface.json` repeats three ids. Run the files separately. Do not pass `--style`.

`now` is Wednesday 14 October 2026, 11:00. The memo adds Friday 16 October 2026 as a holiday and shortens the late deadline from the 6th business day to the 4th. From that Wednesday, the 4th business day is Wednesday 21 October 2026 and the 8th is Tuesday 27 October 2026. The next business day after 16 October is Monday 19 October 2026. Monday 26 October stays a business day. Those dates are in the memo.

## What changed from Brief A

| Rule | Brief A | Pebble, after the memo |
|---|---|---|
| Products | one | up to three, in `get_account` order |
| Holidays | 26 Oct is a holiday | 16 Oct is a holiday. 26 Oct is a business day |
| Early | 1–7 days, 12th business day, 1 attempt | 1–10 days, 8th business day, 1 attempt |
| Late | 8–45 days, 7th business day, 2 attempts | 11–40 days, 4th business day, 2 attempts |
| Floor | the account field | 50 percent of `past_due`. 2125.10 → 1062.55. 1320 → 660 |
| Notes | never | one note for each product with no promise |
| Saved sentence | text message | "A confirmation email will be sent to the address on file." |
| Outcome word | `promise` | the extract says `arranged`; the code list sends `promise` |

The July extract's late deadline of the 6th business day, and its text-message sentence, are superseded. The memo names both.

None of the ledgers are debatable. The memo states the 4th, the 8th, and the Monday after the holiday.

## Which case tests which rule

| Case | Rule under test | Ledger |
|---|---|---|
| PUB-11 | One Friday for all three. 16 October is a holiday, so all three move to 19 October. All are inside the early deadline | 220, 640 and 75 on 2026-10-19. No notes |
| PUB-12 | Card date tomorrow stays 15 October. The loan floor is 660 on the late deadline 21 October. The car is refused | promises on p1 and p2. Note `refused` on p3 |
| PUB-13 | 30 October is past both deadlines. The card clamps to 27 October. The loan clamps to 21 October | 300 on 2026-10-27, 900 on 2026-10-21 |
| PUB-04 | One late product. The memo deadline is 21 October, not 23 October | 1250 on 2026-10-21 |
| PUB-06 | Floor is 1062.55, not 637.50, on 21 October | 1062.55 on 2026-10-21 |
| PUB-07 | 26 October is a business day and not after the early deadline, so it is recorded. Brief A moved it to the 27th | 540 on 2026-10-26 |

## Surface siblings

| File | Case | Style | Same ledger |
|---|---|---|---|
| `cases-surface.json` | PUB-11 | Friday in words | the three promises on 2026-10-19 |
| `cases-surface.json` | PUB-13 | says the 23rd, then corrects to the 30th | 300 on 2026-10-27 and 900 on 2026-10-21. The 30th is still past both deadlines |
| `cases-surface.json` | PUB-12 | the loan balance split across two turns | 510 on 2026-10-15, 660 on 2026-10-21, car refused |
