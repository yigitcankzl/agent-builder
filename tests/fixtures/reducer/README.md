# Reducer fixtures

Independent of `builder/` and of any reducer or extractor. Contract v2 (`fbac10f`, `design/REDUCER-CONTRACT.md`). Briefs A and B and `public-test-set.json` are the other inputs. Every customer, debt and amount is synthetic.

`now` is `2026-10-14T11:00` (a Wednesday). Business days are Monday–Friday except 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25 and 2027-01-01. The 7th business day after today is **2026-10-23** (late deadline). The 12th is **2026-11-02** (early deadline). 2026-10-26 is a Monday holiday; the next business day is 2026-10-27.

## Files

`public_sequences.json` — PUB-01..PUB-13 as one-action turns.

Each case has the policy (`A` or `A+B`), `now`, call variables, the identity answers, `account` as `get_account` returns it (`product_id` `p1`.. in that order), and `derived` (band, deadline, attempt cap, floor, spoken name). `bootstrap.greet` is the opening line. `bootstrap.first_hub` asks “Am I speaking with {title} {last_name}?” with no user event. `steps` start at the customer’s answer.

A step is a user `event` or a `tool_event`, one `action`, and `state` (the key fields **after** the step). `state_unchanged` means that snapshot equals the previous one. `ledger` is the public case’s `expected` object.

`say_exact.contains` are substrings. `say_exact.text`, when present, is exact (`wording` says contract or brief). `close` is one action; the farewell is inside it. `farewell_exact: true` means match `farewell`. Otherwise match every `farewell_contains` string; `farewell` is one line that does.

`extraction_cases.json` — 60 utterances. `context.agent` is the last agent line. `earlier_customer` is only for a value split across turns. `context.code` is the `Code:` the prompt shows; `n` copies it. `expected.ev` is the grammar string. `debatable: true` still has a required label; `reason` says what else it could be.

Event shape: `n=<six letters>;src=user;kind=...;also=...;st=...;prod=...;<payload>`. No `iso`. `prod` empty = current product (`cur` is 0-based; `prod` is 1-based), `all`, or a position. Amounts are digits. A partial date uses empty labels, as in contract example A.

## Choices where the contract is thin

1. **Identity `ans`.** §1.2 says the normaliser runs in code and the extractor only fills `ans`, and gives `YYYY-MM-DD` / four digits as the example. These files put that normalised value in `ans`, and `verify_identity` is called with the same string. If `ans` is supposed to be the raw speech, the identity rows will not match.

2. **Who asks the name.** Greet speaks the opening. The name question is `bootstrap.first_hub`, which sets `counters.confirm_name` to 1 with no user event. §1.4 says a missing event changes nothing. The fixture still counts that ask, because rule 3’s second ask cannot be counted otherwise.

3. **`customer_id`.** The public file has none. Call variables add `c_pub01`..`c_pub13`.

4. **Wrong answer vs failure.** A wrong security answer is HTTP 200, `ok` `"true"`, `verified` false. `wrong_answers_left` goes 3, 2, 1, 0. A correct answer does not refill it. The failure counter moves only on HTTP 500 / `ok` not true. An unreadable date (`ok` false, not a wrong answer) is not in these sequences.

5. **HTTP 500.** `ok` is null and `data` is `{}` (mapping unset). `status_code` and the failure delta still move. PUB-10’s first `create_promise` is that case; the retry uses the same args and does not speak.

6. **`st.offer` is one amount.** The all-today question is not stored there. A joint read-back uses `readback.items` and each product’s own `offer`, with the top-level offer null. `all_today_asked` is set when Brief B asks the question, and on Brief A when the customer refuses today (§1.5’s “not today” example). `cur` null means no single product is in focus.

7. **First ask.** “Can you make this payment today?” sets `offer` to the full past-due amount today and `status` `proposed`, so the agreement is `kind=accept` (PUB-01). A customer who names a day is `kind=date` (or `date_amount`), which outranks `accept`. A bare “Yes” to an offer is marked debatable in the extraction file.

8. **Attempts.** Speaking attempt 1 sets `attempts` to 1 (last business day of this week: Friday 16 October; full amount, or the floor if they already said the full amount is too much). A flat refusal under the cap speaks the next attempt and increments. At the cap, the product becomes `refused` and the counter stays. Attempt 2 is the floor on the deadline (`kind` `attempt_n`, `floor_offered` true). A proposed date or amount does not increment. “Too much” only offers the floor. PUB-12: card attempts 0, personal loan 2, car loan 1.

9. **Vague date.** “The week after next” is `vague=yes`, `wk=after_next`. It drops the today-offer (`status` back to `open`) and increments `counters.vague`. It does not use an attempt. PUB-07 then splits “Monday the twenty-” / “sixth”. The partial step changes nothing and says “Go on, please.” The next event is already assembled (`d=26`, `wd=mon`). The public script says this in one breath; the split is only there so a partial turn exists. The ledger is still 540 on 2026-10-27.

10. **Read-back.** One product: a valid customer date, or `accept` of a live offer, goes straight to “Do you confirm?”. Several products: agreed items wait for one joint read-back (Brief B rule 7), including PUB-12, where the card is agreed and only read back after the other two are refused. A date after one product’s deadline is clamped in that read-back (PUB-13: card 30 October, loan 23 October). The event still carries 30 October, not the clamped day.

11. **Recorded, notes, transfer.** “Your promise is recorded. …” is said only on a step whose tool event already has a `create_promise` success and `ok` `"true"`. With several products the intermediate success’s one action is the next `create_promise`, so the sentence is said once, after the last success. PUB-12 still owes notes: those `add_note` calls run before that sentence, in `wrapup`, because a `say_exact` would wait for the user and “thanks” would close first. `add_note`’s optional `text` is omitted. A transfer’s user turn calls `transfer_to_agent` and does not speak; the success step closes. No notes on that path.

12. **Topics with no code.** A discount has no topic value, so PUB-05 uses `kind=other`, `st=none`, and `speak_free` on `talk_post`. `counters.support_offered` is the contract’s open-ended counter list: without it, the later `kind=no` cannot mean hardship. The sympathy line is not fixed by the brief; the fixture requires the substrings `sorry` and `customer support`. PUB-06’s “you tell me” is not a step: the agent must not ask how much, and the floor line forbids “how much can you”.

13. **Close lines.** “Thank you, goodbye.” is exact where it is the whole farewell. Paid and the third wrong answer need a fact the brief does not word: the canonical farewells are in the file, and `farewell_exact` is false so the required check is `farewell_contains` (“one business day”; “mobile app” and “branch”).

14. **Opening and “recorded”.** Rule 1 says the call is recorded. `recorded` is also an honesty word, and the contract’s lint may rewrite it. The greet requires “digital assistant” and “Freya Bank” and does not require either wording.

15. **Secondary reject.** Example F has `also=reject` and no `why`. These files do the same. A primary reject still has `why=flat` or `why=too_much`.

16. **“Around eleven”.** PUB-02’s script says around eleven. The public ledger is 11:00, so `tm=11:00`.

17. **Bare weekday.** Without “this” or “next”, `wk=none`. Some of those extraction rows are `debatable`. Public sequences say “this Friday”, so `wk=this` (16 October).

18. **Ambiguous Friday the 20th.** §1.2 says a weekday that contradicts the day of month is `st=ambiguous`, which needs the calendar the extraction rules say not to compute. The row is debatable and still expects `st=ambiguous`, with both labels and no `iso`. 20 October 2026 is a Tuesday. “Tuesday the 20th” agrees, so the repeat pair is `st=complete`.

19. **Injection during identity.** §1.5 ranks who/identity first in that phase. EX-54 and EX-55 are debatable and still expect `t=injection`, not an identity success and not `who=self`.

20. **Tokens.** User-event `n` values are scripted. The harness sets `st.tok` to that `n` before the step. Before the first user step, `last_tok` is `kstart`. Tool steps ignore `ev`. The reducer’s own random token is not asserted.
