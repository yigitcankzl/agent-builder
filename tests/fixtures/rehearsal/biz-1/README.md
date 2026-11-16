# biz-1

Frozen answer key. Meridian Trade Credit, one product. Identity, products, amounts and `days_late` are copied from `public-test-set.json`. `openapi.json` is the kit file.

The kit `verify_identity` field list is `date_of_birth` then `phone_last4`. A company number cannot be checked on the practice mock, so the brief does not ask for one. The authorised-person question is spoken. It is not a tool field.

`first_name`, `last_name` and `now` match the public case. `title` is omitted. `company_name` and `contact_name` are added. The practice session still returns `title` and does not return `company_name`. The brief says never to speak a title, and the company names are the table in `brief.md`.

`now` is Wednesday 14 October 2026, 11:00. Friday 16 October 2026 is a holiday. The 2nd business day after today is Monday 19 October 2026. The 3rd is Tuesday 20 October 2026. The floor is 25 percent of the past-due amount. 2125.10 becomes 531.28.

`cases.json` is the changed-rule set. `cases-surface.json` repeats three ids. Run them as separate `--cases` files. Do not pass `--style`. The `brief` field is `A` so a brief filter can select the file. The spec is not Brief A.

## What changed from Brief A

| Rule | Brief A | Meridian |
|---|---|---|
| Who is on the line | title plus last name | the named person, then "Are you authorised to discuss this account?" |
| Someone else | a relative | a colleague, a receptionist, or the named person saying they are not authorised |
| Title | spoken | never spoken |
| Holidays | 26 Oct is a holiday | 16 Oct is a holiday. 26 Oct is an ordinary Monday |
| Early | 1–7 days, 12th business day | 1–7 days, 3rd business day, Tuesday 20 October |
| Late | 8–45 days, 7th business day | 8–45 days, 2nd business day, Monday 19 October |
| Floor | the account field | 25 percent of `past_due`. 2125.10 → 531.28 |
| Callback | 10:00–19:00 | 09:00–16:00 |
| Saved sentence | a text message | "The company will receive an email confirming this promise." |

## Which case tests which rule

| Case | Rule | Ledger |
|---|---|---|
| PUB-01 | Authorised contact. Early deadline is 20 October, not this Friday | 420 on 2026-10-20 |
| PUB-02 | A receptionist is not verified. Tomorrow at 10:00 is inside 09:00–16:00 | `not_reached` / `callback`, 2026-10-15 10:00 |
| PUB-03 | The named contact says he is not authorised | `not_reached` / `callback`, 2026-10-15 09:00. Debatable |
| PUB-04 | Late deadline is 19 October, not 23 October | 1250 on 2026-10-19 |
| PUB-06 | Floor is 531.28, not 637.50, on 19 October | 531.28 on 2026-10-19 |
| PUB-07 | 26 October is after the early deadline. 27 October is not the holiday move | 540 on 2026-10-20 |
| PUB-10 | Days late 8 is the late band, so the deadline is 19 October. Friday 16 October cannot be recorded | 365 on 2026-10-19 |

## Surface siblings

| Case | Style | Same ledger |
|---|---|---|
| PUB-04 | in words | 1250 on 2026-10-19 |
| PUB-06 | split across two turns | 531.28 on 2026-10-19 |
| PUB-10 | a wedding on the 30th | 365 on 2026-10-19 |

## Debatable

PUB-03 only. He is Owen Park and he says he is not authorised, so rule 4 sends him down the callback path. A reader could instead close `not_verified` / `declined` because the named person refused the security questions. The expected ledger follows rule 4.
