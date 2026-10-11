# raw-5-single

Cedar Credit, one pasted file, up to three products. The customers are PUB-11, PUB-12, and PUB-13. Identity, products, amounts, and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file. The `brief` field is `B` so the runner can select the file. These are not the rules in `briefs/brief-b.md`.

`now` is Wednesday 14 October 2026, 11:00. Run `cases.json` and `cases-surface.json` separately. Do not pass `--style`. The ledgers use the kit values from the code table. The meeting's office words are arranged, handed_over, will_not_pay, and new_plan.

## Precedence

1. The chair's note of 1 October 2026 says the meeting is the procedure, and the code table only chooses the API value for an office word. The table does not change a date, a floor, or which product is transferred.
2. The meeting of 2 October 2026, 10:00, sets opening, identity, the two floors, the car transfer, the deadlines, and the refused note.
3. The code table maps those office words onto the kit. `handed_over` is sent as `transferred`. `arranged` is sent as `promise`. `will_not_pay` is sent as `refused`. `new_plan` is sent as `restructuring`.

## Where each rule lives

| Rule | Where it lives |
|---|---|
| Greeting "Am I speaking with {title} {last_name}?", "Do you confirm?", and the confirmation-email sentence | Meeting, Alex and Dana, as quoted sentences |
| Card floor, 40 percent. 300 → 120 | Meeting, Dana's floor turn |
| Personal-loan floor, 25 percent. 900 → 225. 1320 → 330. 528 is named as the wrong loan floor | Meeting, the same turn |
| Car loan is transferred, not promised, and gets no note | Meeting, Alex's car turn. Queue office word `new_plan` |
| Early deadline, the 3rd business day, Tuesday 20 October 2026. Late deadline, the 2nd business day, Monday 19 October 2026 | Meeting, Alex's deadline turn. Friday 16 October 2026 is a holiday. The next business day is Monday 19 October |
| A refused product still gets a note when the car is transferred | Meeting, Alex's note turn. Office word `will_not_pay` |
| Close `handed_over` with reason restructuring when any transfer happened. Otherwise `arranged` with no reason | Meeting, Dana's close turn |
| API spelling of those words | Code table |

## Which case tests which rule

| Case | Rule | Ledger |
|---|---|---|
| PUB-11 | Friday 16 October moves to Monday 19 October for the card and the loan, both inside the early deadline. The car is transferred and not promised | transferred / restructuring. Promises 220 and 640 on 2026-10-19. No notes. Queue restructuring |
| PUB-12 | Card tomorrow, Thursday 15 October, full 510, inside the late deadline. The loan is refused, so the note is written. The car is transferred | transferred / restructuring. Promise 510 on 2026-10-15. Note `refused` on p2. Queue restructuring |
| PUB-13 | No car, so no transfer. The card uses 40 percent, 120, on Tuesday 20 October. The loan uses 25 percent, 225, on Monday 19 October | promise. 120 on 2026-10-20 and 225 on 2026-10-19. No notes |

## Surface siblings

| Case | Style | Same ledger |
|---|---|---|
| PUB-11 | Friday in words | the two promises on 2026-10-19, car transferred |
| PUB-12 | 510 split across two turns | 510 on 2026-10-15, loan refused, car transferred |
| PUB-13 | says 90, then corrects to 120. The loan stays 225 | 120 on 2026-10-20 and 225 on 2026-10-19 |

None of the ledgers are debatable. The meeting states Tuesday 20 October, Monday 19 October, 120, 225, and 330, and it says the car is a transfer. The code table states the wire values. The chair's note says the table does not move a date or a floor.
