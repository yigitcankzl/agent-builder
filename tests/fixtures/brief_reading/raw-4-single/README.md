# raw-4-single

Rowan Mutual, one pasted file, one product. The customers are PUB-01 through PUB-10. Identity, products, amounts, and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file. The `brief` field is `A` so the runner can select the file. These are not the rules in `briefs/brief-a.md`.

`now` is Wednesday 14 October 2026, 11:00. Run `cases.json` and `cases-surface.json` separately. Do not pass `--style`.

## Precedence

1. The dialler email of 1 October 2026 sets the greeting, identity, relatives, and the callback window. It does not set deadlines or the floor.
2. The policy email of 3 October 2026 sets both deadlines, the holiday list, attempts, hardship, restructuring, the already-paid close, and the quoted read-back and saved line. Its last paragraph, about payday on the 5th, sets no rule.
3. Sam Adeyemi's chat on 6 October 2026 states a floor of 50 percent of `past_due`.
4. The email of 9 October 2026 says it is authoritative and replaces that floor. The floor is 30 percent. The 3 October deadlines stay.

## Where each rule lives

| Rule | Where it lives |
|---|---|
| Greeting "This is Rowan Mutual. This call is recorded." and "Am I speaking with {title} {last_name}?" | 1 October email, quoted in the paragraph |
| Identity, three wrong answers, relatives, callback 10:00–18:00 | 1 October email |
| Early deadline, the 4th business day, Wednesday 21 October 2026. One attempt | 3 October email |
| Late deadline, the 2nd calendar day. That day is Friday 16 October 2026, a holiday, so the promise date is the previous business day, Thursday 15 October 2026. Two attempts | 3 October email. The 9 October email repeats those two dates and does not change them |
| Holiday Friday 16 October 2026, and Monday 26 October 2026 not a holiday | 3 October email |
| Next business day after that Friday is Monday 19 October 2026 | 3 October email |
| Floor 50 percent | 6 October chat. Withdrawn |
| Floor 30 percent. 2125.10 → 637.53 | 9 October email, the message that says it is authoritative |
| "Do you confirm?" and "A confirmation email will be sent to the address on file." | 3 October email, quoted in the paragraph |
| Payday on the 5th | 3 October email, the paragraph that says it sets no rule |
| No `add_note` | 3 October email |

## Which case tests which rule

| Case | Rule | Ledger |
|---|---|---|
| PUB-01 | Names the holiday Friday. The next business day, Monday 19 October, is inside the early deadline | 420 on 2026-10-19 |
| PUB-02 | Husband. No security. Tomorrow at 11:00 is inside the callback window. Thursday 15 October is a business day | not_reached / callback at 2026-10-15 11:00. No identity tool |
| PUB-03 | Three wrong dates of birth. The real date is never given | not_verified / failed |
| PUB-04 | 6 November is past the late deadline. The holiday sits on that deadline, so the full 1250 is Thursday 15 October | 1250 on 2026-10-15 |
| PUB-05 | Hardship path, support declined. The floor is not offered | no_promise / hardship |
| PUB-06 | Full amount too much. 50 percent and the minimum are refused. The authoritative floor is 637.53 on Thursday 15 October | 637.53 on 2026-10-15 |
| PUB-07 | Monday 26 October and the 5th of November are both after the early deadline. The 5th is the payday sentence and is not a rule | 540 on 2026-10-21 |
| PUB-08 | Already paid this morning | paid |
| PUB-09 | Lower instalments | transferred / restructuring |
| PUB-10 | Full 365 on the early deadline. The practice service may fail the first `create_promise` for this id. The same promise is sent again. The ledger is still one promise | 365 on 2026-10-21 |

## Surface siblings

| Case | Style | Same ledger |
|---|---|---|
| PUB-04 | the amount and the day in words | 1250 on 2026-10-15 |
| PUB-06 | 637.53 split across two turns | 637.53 on 2026-10-15 |
| PUB-07 | says the 5th of November, then corrects to Monday 26 October. Both are still too late | 540 on 2026-10-21 |

None of the ledgers are debatable. The 9 October email names itself as the authority and gives 637.53. The 3 October email gives Thursday 15 October, Wednesday 21 October, and Monday 19 October. The payday paragraph says it sets no rule.
