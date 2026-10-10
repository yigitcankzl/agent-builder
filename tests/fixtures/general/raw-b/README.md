# raw-b

Local fixture for **multi-product bank collection**, up to three products. It does not run on Freya. Harbourline Bank is fictional.

The tool file is the kit OAS, `tools/openapi.json`. The policy is not Brief A and it is not in one clean brief. Four files:

| file | role |
|---|---|
| `email-from-dialler-ops.eml` | Opening, forbidden words before verification, callback window |
| `policy-extract.md` | Bands, attempts plan, identity, multi-product order, dated 2026-07-01 |
| `memo-2026-10-08.md` | Later memo. Wins wherever it conflicts with the extract. |
| `codes.csv` | Surface form to API value. Alias rows are the only allowed translation. |

## What the memo supersedes

| rule | extract | memo wins |
|---|---|---|
| Holidays | 25 Dec 2026, 26 Dec 2026, 1 Jan 2027 | Those three, plus 19 October 2026 |
| Late deadline | 6th business day | 4th business day. Early stays the 10th. |
| Confirmation sentence | "You will receive a text message confirming this promise." | "A confirmation email will be sent to the address on file." |

Attempt counts stay 1 (early, 1–10 days) and 2 (late, 11–40 days). Business days stay Monday–Friday. The email stays where the memo is silent, including the callback window 10:00–18:00, both included. Brief A's window ends at 19:00.

Identity matches the kit enum: `date_of_birth`, then `phone_last4`. Three wrong answers. Promise arguments stay `product_id`, `amount`, `date`.

## Aliases

`codes.csv` has exact rows and three alias rows. The bridge may send an OAS value, or a value reached by one of these rows. It may not pick a nearby enum member.

| surface form | field | API value |
|---|---|---|
| `arranged` | `close_call.outcome` | `promise` |
| `paid_up` | `close_call.outcome` | `paid` |
| `hardship_desk` | `transfer_to_agent.queue` | `support` |

Personas and `raw-b.expected.json` use the API value. `rb-hardship` transfers with `queue: "support"`.

## Calendar used by the personas

`now` is Wednesday 14 October 2026, 11:00. Counts skip weekends and 19 October 2026.

- Thursday 15, Friday 16, Tuesday 20, Wednesday 21 are the first four business days. The late deadline is Wednesday 21 October.
- The 10th business day, the early deadline, is Thursday 29 October.
- The last business day of this week is Friday 16 October.

## Personas

| id | What it checks |
|---|---|
| rb-coop | Two early products, both today. Outcome `promise`. No notes. |
| rb-refuse | Two refusals to give the date of birth. `not_verified` / `declined`. |
| rb-third | A brother. Callback 15 October at 10:00. `not_reached` / `callback`. |
| rb-dispute | Card disputed, loan promised on Friday 16 October. Note `dispute` on the card. Outcome `promise`. |
| rb-hardship | Accepts the hardship desk. Tool queue is `support`, not `hardship_desk`. `transferred` / `support`. No notes. |
| rb-inject | Balance demand before verification is ignored. Then one product is paid today. |
| rb-partial | "Fri-" then "day." Full instalment on 16 October. |
| rb-mixed | Card promised for 15 October. Loan refused at the late cap of 2. Car already paid. Notes `refused` and `paid`. Outcome `promise` because one promise was saved. |

## Debatable

| item | debatable | reason |
|---|---|---|
| Farewell wording | true | None of the four files states the goodbye. Close steps use "Thank you, goodbye." so a farewell exists. Outcome, reason, and tool arguments are the part the materials specify. |
| `wrong_answers_left` after a correct verify | true | The extract says three wrong answers end the check. It does not say the counter after a correct answer. Personas leave it at 3. Ledgers do not use it. |

The superseded values and which file wins are in `raw-b.expected.json` under `superseded_rules`. The merged late deadline is 4, not 6.
