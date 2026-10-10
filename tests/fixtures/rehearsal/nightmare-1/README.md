# nightmare-1

Frozen answer key. Ashworth Retail Bank, one product. Identity, products, amounts, `days_late` and the call variables are copied from `public-test-set.json`. `openapi.json` is the kit file.

The kit outcome enum has no `complaint` value. Rule 17 closes `no_promise` / `complaint`. `complaint` is the reason. The kit leaves `reason` as a string.

`now` is Wednesday 14 October 2026, 11:00. That time is inside the 08:00–18:00 call window, so every scored case proceeds. The brief still states the outside-window close. It is not scored, because the practice session does not move `now`.

Friday 16 October 2026 is a holiday. The 5th calendar day after today is Monday 19 October 2026. The 4th calendar day is Sunday 18 October 2026, and the latest business day on or before it is Thursday 15 October 2026. Fifty percent of 2125.10 is 1062.55.

`cases.json` and `cases-surface.json` are separate `--cases` files. Do not pass `--style`. The `brief` field is `A`. The spec is not Brief A.

## What changed from Brief A

| Rule | Brief A | Ashworth |
|---|---|---|
| Call window | none | no account talk before 08:00 or after 18:00 |
| Deadline | business days | calendar days. Early latest day 19 October. Late latest day 15 October |
| Partial payment | anything from the floor to the full amount | only the full amount, or exactly 50 percent |
| Before a no-promise close | close at once | ask "Can I note that you are not making a promise today?" |
| Customer callback | not a path | before security, book it, and do not verify |
| Callback hours | 10:00–19:00 | 09:00–17:00. 15:00 is inside. 19:00 is outside |
| After the debt | the debt only | "Interest continues to accrue while the payment is late." |
| Complaint | no such topic | `no_promise` / `complaint` |

## Which case tests which rule

| Case | Rule | Ledger |
|---|---|---|
| PUB-01 | He refuses the deadline, then names it when asked the note question. The early latest day is 19 October | 420 on 2026-10-19 |
| PUB-06 | 50 percent is 1062.55, not 637.50, on the late day 15 October. 11:00 is inside the call window, so the debt and the interest sentence are said | 1062.55 on 2026-10-15 |
| PUB-04 | The late latest day is 15 October, not 23 October | 1250 on 2026-10-15 |
| PUB-10 | Friday 16 October is a holiday. The next business day is the early deadline | 365 on 2026-10-19 |
| PUB-07 | "Tomorrow at 3 in the afternoon" is 15:00 on 15 October, before any security answer | `not_reached` / `callback`, 2026-10-15 15:00. No identity tool |
| PUB-09 | A complaint stops the call | `no_promise` / `complaint` |
| PUB-02 | 19:00 is after 17:00, and he has no second time | `not_reached` / `no_callback`. Nothing scheduled |

## Surface siblings

| Case | Style | Same ledger |
|---|---|---|
| PUB-01 | a wedding on the 30th | 420 on 2026-10-19 |
| PUB-06 | the balance split across two turns | 1062.55 on 2026-10-15 |
| PUB-04 | 6 November in words | 1250 on 2026-10-15 |

None of these ledgers are debatable. The brief states the two latest days, the penny amount, 15:00, 19:00, and the complaint reason.
