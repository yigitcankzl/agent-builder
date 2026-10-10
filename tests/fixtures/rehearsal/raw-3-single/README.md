# raw-3-single

Lark Credit, one pasted file, up to three products. The customers are PUB-11, PUB-12 and PUB-13. Identity, products, amounts and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file.

`now` is Wednesday 14 October 2026, 11:00. Run `cases.json` and `cases-surface.json` separately. Do not pass `--style`.

## Precedence

1. The handbook of 15 July 2026 is the base for opening, identity, product order, notes, and the attempt shape.
2. Nia Okonkwo's chat line of 2 October 2026, 14:22, adds one holiday. It is one sentence in a note about the late queue and the kitchen.
3. The HR picnic mail of 5 October 2026 is not a collections rule. Friday 16 October stays a business day.
4. Mira Shah's email of 9 October 2026 wins over the handbook table. It does not cancel the 2 October holiday sentence.
5. The handbook paragraph marked "Superseded on 1 September 2026" is dead. The email repeats that it must not be used.

## Where each live rule is

| Rule | Where it lives |
|---|---|
| Opening, identity, one date for every product, notes, "Do you confirm?" | 15 July handbook |
| Holiday list of 25 December, 26 December and 1 January | 15 July handbook |
| Tuesday 20 October 2026 is a holiday | Nia Okonkwo, 2026-10-02T14:22:11, the sentence about the branch being shut. It is not in the holiday list |
| Early deadline, the 5th business day, Thursday 22 October 2026. Late deadline, the 3rd, Monday 19 October 2026. Attempts stay 1 and 2 | 9 October email. The table's 12th and 7th are withdrawn. The email uses the 2 October holiday without naming that Tuesday again |
| Floor, 40 percent of `past_due`, half up to the penny | 9 October email, in prose. The table's floor column is withdrawn. There is no worked penny example |
| Confirmation sentence | 9 October email. The superseded handbook paragraph's text-message sentence is dead |
| Picnic on Friday 16 October | HR mail. It says it changes nothing |

From that Wednesday, with Tuesday 20 October skipped, the business days after today are Thursday 15 October, Friday 16 October, Monday 19 October, Wednesday 21 October, Thursday 22 October. The 3rd is Monday 19 October 2026. The 5th is Thursday 22 October 2026. The next business day after Tuesday 20 October is Wednesday 21 October 2026. Forty percent of 1320 is 528.00.

## Which case tests which rule

| Case | Rule | Ledger |
|---|---|---|
| PUB-11 | One Tuesday for all three. That Tuesday is the holiday named only in Nia's sentence, so all three move to Wednesday 21 October. All are inside the early deadline | 220, 640 and 75 on 2026-10-21 |
| PUB-12 | The card date tomorrow stays 15 October. The loan floor is 40 percent, 528, on the late deadline 19 October. The car is refused. 440 is the instalment and is not the floor | 510 on 2026-10-15 and 528 on 2026-10-19. Note `refused` on p3 |
| PUB-13 | 30 October is past both deadlines from the email, not the old table. The card clamps to 22 October. The loan clamps to 19 October | 300 on 2026-10-22 and 900 on 2026-10-19 |

## Surface siblings

| Case | Style | Same ledger |
|---|---|---|
| PUB-11 | Tuesday in words | the three promises on 2026-10-21 |
| PUB-12 | the loan balance split across two turns | 510 on 2026-10-15 and 528 on 2026-10-19, car refused |
| PUB-13 | says the 23rd, then corrects to the 30th | 300 on 2026-10-22 and 900 on 2026-10-19 |

None of the ledgers are debatable. The holiday sentence is an instruction, the 9 October email states Monday 19 October and Thursday 22 October, and 40 percent of 1320 is 528 with no rounding left over. The picnic mail says it is not a holiday.
