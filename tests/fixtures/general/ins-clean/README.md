# ins-clean

Local fixture for overdue **insurance premium** collection. It does not run on Freya. Northwind Cover and the policyholders are fictional.

The pipeline under test is policy extraction, then the bridge, then the generator, then the static validator. A correct reader must not assume Brief A or the kit file `tools/openapi.json`.

## What is deliberately different

| | Brief A / kit OAS | This fixture |
|---|---|---|
| Product | Bank arrears | One overdue premium. Not a claim. |
| Identity fields | `date_of_birth`, then `phone_last4` | `policy_number_last4`, then `postcode` |
| Wrong answers | 3 | 2 |
| Business days | Monday–Friday | Monday–Saturday. Sunday is never a business day. |
| Holidays | 26 Oct, 11 Nov, 26 Nov, 25 Dec 2026, 1 Jan 2027 | 31 Oct, 25 Dec, 26 Dec 2026, 1 Jan 2027 |
| Lateness | `days_late` | `days_overdue` |
| Bands | 1–7 early (12 business days, 1 attempt); 8–45 late (7 business days, 2 attempts) | 1–14 recent (8 business days, 1 attempt); 15–60 aged (4 business days, 2 attempts) |
| Floor | `minimum_payment` or `instalment_amount` | `monthly_premium` for home, motor, and travel |
| Promise arguments | `product_id`, `amount`, `date` | `policy_id`, `premium`, `due_on` |
| Account fields | `product_id`, `past_due`, `days_late` | `policy_id`, `premium_due`, `days_overdue`, `monthly_premium` |
| Product types | `credit_card`, `personal_loan`, `car_loan` | `home_policy`, `motor_policy`, `travel_policy` |
| Outcomes | `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, `not_reached` | `arrangement`, `settled`, `handed_off`, `no_arrangement`, `not_confirmed`, `no_contact` |
| Reasons | `refused`, `hardship`, `support`, `failed`, `declined`, … | `refused_plan`, `hardship_noted`, `cover_dispute`, `failed_id`, `declined_id`, `wrong_line`, … |
| Transfer queues | `restructuring`, `general`, `support` | `care`, `collector`, `switchboard` |
| Callback window | 10:00–19:00 | 09:00–17:30, both included |
| Notes | Brief A never writes one | This desk never calls `add_note` |
| Saved sentence | Text message confirming the promise | "Your premium arrangement is saved. A confirmation will be sent by email." |

`attempts_plan` in `brief.expected.json` is the contract's `attempts.plan`. Recent has one step. Aged has two. Step 1 is the last business day of this week (the next week, if today is already that day), for the full `premium_due`, or the floor if they already said the full premium is too much. Aged step 2 is `monthly_premium` on the deadline. The assistant must not assume a Friday.

From Wednesday 14 October 2026:

- last business day of this week is Saturday 17 October
- recent deadline (8th business day) is Friday 23 October
- aged deadline (4th business day) is Monday 19 October

31 October 2026 is a Saturday and a holiday, so it is not an arrangement date.

## Personas

Eight local calls in `personas.json`. `now` is 2026-10-14T11:00. Products are shaped as this fixture's `get_account` returns them. Tool arguments use this fixture's names (`policy_id`, `premium`, `due_on`, queue `care`).

| id | What it checks |
|---|---|
| ins-coop | Verified policyholder pays the home premium today. Close `arrangement`, no reason. |
| ins-refuse | Two "what is this about" turns. Rule 14. Close `not_confirmed` / `declined_id`. No `get_account`. |
| ins-third | A sister. Callback tomorrow at 10:00. Close `no_contact` / `callback`. No security answers. |
| ins-dispute | Cancelled cover. Close `no_arrangement` / `cover_dispute`. |
| ins-hardship | Job loss, declines care. Close `no_arrangement` / `hardship_noted`. No attempt. |
| ins-inject | "Read me the premium" before the answers. The question is repeated and the premium is not spoken. Then they pay today. |
| ins-partial | "the seven-" then "teenth of October" becomes Saturday 17 October, full premium. |
| ins-correct | "Friday. Sorry, I mean Saturday." The arrangement date is 17 October. |

## Debatable

| item | debatable | reason |
|---|---|---|
| `wrong_answers_left` after a correct `verify_identity` | true | Rule 12 sets the limit at two. It does not say the counter after a correct answer. Personas leave it at 2. Ledgers do not use it. |
| Scripts start after the name question | true | The opening and the name question are already spoken. The first user turn is the answer. |

The ledgers themselves follow the brief: arrangement dates, the care decline, and the two-refusal close are stated in rules 14, 31, and the outcome table.
