# clean-1

Frozen answer key. Northline Bank, one product. The customers are PUB-01, PUB-02, PUB-04, PUB-06, PUB-07 and PUB-10. Identity, products, amounts and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file, unchanged, because the practice mock accepts those fields and enums.

`cases.json` is the changed-rule set. `cases-surface.json` repeats three ids with the same ledger and a different way of speaking. Run them as separate `--cases` files. Do not pass `--style`; the surface file sets it.

`now` is Wednesday 14 October 2026, 11:00. Friday 16 October 2026 is a holiday. The 3rd business day after today is Tuesday 20 October 2026. The 5th is Thursday 22 October 2026. The next business day after the holiday is Monday 19 October 2026. Those three dates are written in `brief.md`.

## What changed from Brief A

| Rule | Brief A | Northline |
|---|---|---|
| Holidays | 26 Oct is a holiday | 16 Oct is a holiday. 26 Oct is an ordinary Monday |
| Bands | 1–7 early, 12th business day; 8–45 late, 7th | 1–5 early, 5th business day; 6–40 late, 3rd |
| Attempt 1 | last business day of this week, full amount | the deadline, full amount |
| Floor | `minimum_payment` or `instalment_amount` | 40 percent of `past_due`, half up to the penny. 2125.10 → 850.04 |
| Callback | 10:00–19:00 | 12:00–17:00 |
| Saved sentence | a text message confirming the promise | "This arrangement is saved. A confirmation email will be sent." |
| Confirm | "Do you confirm?" | "Do you confirm this arrangement?" |
| Wire enums | kit | kit. The mock rejects other outcome names |

None of the ledgers are debatable. The brief states the counts and the 850.04 example.

PUB-10's practice session may fail the first `create_promise`, as it does for that public id. Rule 24 says retry once. The ledger is still 365 on 19 October.

## Which case tests which rule

| Case | Rule under test | Ledger |
|---|---|---|
| PUB-01 | Days late 6 is late. Refusing today starts attempt 1: full balance on the deadline | 420 on 2026-10-20 |
| PUB-02 | 11:00 is before 12:00, and he has no second time | `not_reached` / `no_callback`, nothing scheduled |
| PUB-04 | Late deadline is 20 October, not 23 October | 1250 on 2026-10-20 |
| PUB-06 | Floor is 850.04, not 637.50, offered on the deadline | 850.04 on 2026-10-20 |
| PUB-07 | 26 October is not a holiday, and it is after the early deadline. 27 October is not offered | 540 on 2026-10-22 |
| PUB-10 | 16 October cannot be recorded. The next business day is 19 October | 365 on 2026-10-19 |

## Surface siblings

Same ledgers. The reaction table is the same agreement, said differently.

| File | Case | Style | Same ledger |
|---|---|---|---|
| `cases-surface.json` | PUB-04 | in words | 1250 on 2026-10-20 |
| `cases-surface.json` | PUB-06 | split across two turns | 850.04 on 2026-10-20 |
| `cases-surface.json` | PUB-07 | a wedding on the 30th | 540 on 2026-10-22. The 30th is not a payment |
