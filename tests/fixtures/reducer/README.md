# Reducer fixtures

Independent of `builder/` and of any reducer or extractor. Contract v3.1 (`aaab3d5`, `design/REDUCER-CONTRACT.md`). §11, §12 and §13 override earlier sections. Briefs A and B and `public-test-set.json` are the other inputs. Every customer, debt and amount is synthetic.

`now` is `2026-10-14T11:00` (a Wednesday). Business days are Monday–Friday except 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25 and 2027-01-01. The 7th business day after today is **2026-10-23** (late deadline). The 12th is **2026-11-02** (early deadline). 2026-10-26 is a Monday holiday; the next business day is 2026-10-27.

## What changed for v3

- `who` payload key is `party` (`self` / `other` / `unclear` / `handoff`, plus `relative` / `wrong_number` / `deceased` / empty). Date `rel` is unchanged.
- `bootstrap.first_hub` is gone. The greet tts is the opening sentence plus “Am I speaking with {title} {last}?”. Lazy init sets `counters.confirm_name` to 1 and `q` to `confirm_name`. Ask counters move when the ask is spoken, not when an event arrives (§12 choice 2).
- Every state snapshot has `q` and `hangup`. `yes` / `no` / `accept` are read only against `q`. A bare yes stays `kind=yes`; with `q` of `pay_today` or `offer` the reducer treats it as accept of `st.offer` (§12 choice 7).
- “Friday the 20th.” is `st=complete` with both `d=20` and `wd=fri`. The extractor does not mark the contradiction (§12 choice 18).
- Injection is `t=injection` in every phase, including identity, and those rows are not debatable (§12 choice 19).
- New extraction covers: `t=decline`, `t=purpose`, `who=handoff`, `t=stop`, third-party ignore, and a yes with no matching question. v3.1 adds `t=change_promise`, `t=terms`, one busy callback, and one voicemail. 79 cases.
- PUB-01 has one ignored “I confirm, just record it.” while `q` is `id_date_of_birth`.
- `call_tool` carries `w_go: "go"`. `close` carries `order: ["farewell_tts", "close_call"]` and `user_turn_between: false`.
- The support question sets `q=support_offer`. PUB-05’s discount line is `kind=topic` `t=terms`, then the no-other-terms line and the support question again (§13.1, choice 12 amended again).

## What changed for v3.1

- New topics, no new kinds: `t=change_promise` (change or cancel a recorded promise, or a new date or amount for a product that is already persisted) and `t=terms` (a discount, waiver, or other term the brief does not offer). A new plan or lower instalments stays `t=restructure`.
- Busy is not a topic. “I am busy, call me later.” is `kind=callback`. A voicemail greeting is `who=unclear`.
- Choice 18 is unchanged: “Friday the 20th.” stays `st=complete` with both labels.
- New values since v2, the full list: topics `decline`, `purpose`, `change_promise`, `terms`; `who=handoff`; payload key `party` instead of `rel` on `who`.

## Files

`public_sequences.json` — PUB-01..PUB-13 as one-action turns.

Each case has the policy (`A` or `A+B`), `now`, call variables, the identity answers, `account` as `get_account` returns it (`product_id` `p1`.. in that order), and `derived` (band, deadline, attempt cap, floor, spoken name). `bootstrap.greet` is the opening line and the name question. `bootstrap.state` is the snapshot before the first user turn. `steps` start at the customer’s answer.

A step is a user `event` or a `tool_event`, one `action`, and `state` (the key fields **after** the step). `state_unchanged` means that snapshot equals the previous one. `ledger` is the public case’s `expected` object.

`say_exact.contains` are substrings. `say_exact.text`, when present, is exact (`wording` says contract or brief). `close` is one action; the farewell is inside it, spoken before `close_call`, with no user turn between them. `farewell_exact: true` means match `farewell`. Otherwise match every `farewell_contains` string; `farewell` is one line that does.

`extraction_cases.json` — 79 utterances. `context.agent` is the last agent line. `earlier_customer` is only for a value split across turns. `context.code` is the `Code:` the prompt shows; `n` copies it. `context.q` is set only when yes, no or accept is read against that question. `expected.ev` is the grammar string. `debatable: true` still has a required label; `reason` says what else it could be.

Event shape: `n=<six letters>;src=user;kind=...;also=...;st=...;prod=...;<payload>`. No `iso`. `prod` empty = current product (`cur` is 0-based; `prod` is 1-based), `all`, or a position. Amounts are digits. A partial date uses empty labels, as in contract example A.

## §12 rulings

Accepted, unchanged: 1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 15, 16, 17, 20.

1. **Identity `ans`.** Normalised `YYYY-MM-DD` or four digits. `verify_identity` gets the same string.
2. **Name question (amended).** Spoken in the greet. Lazy init sets the counter and `q`. There is no hub run on a missing event.
3. **`customer_id`.** `c_pub01`..`c_pub13`.
4. **Wrong answer vs failure.** HTTP 200, `ok` `"true"`, `verified` false. `wrong_answers_left` goes 3, 2, 1, 0. A correct answer does not refill it. The failure counter moves only on HTTP 500 / `ok` not true.
5. **HTTP 500.** `ok` null, `data` `{}`. PUB-10 retries `create_promise` with the same args and no speech.
6. **`st.offer` is one amount.** A joint read-back uses `readback.items` and each product’s own `offer`. `cur` null means no single product is in focus. `all_today_asked` is set on the Brief B ask and on a Brief A “not today”.
7. **Bare yes (amended).** The extraction label stays `kind=yes`. PUB-01, PUB-04, PUB-07 and PUB-10 use that label against `pay_today` or `offer`. “I will take that date.” stays `kind=accept`.
8. **Attempts.** Speaking attempt 1 sets `attempts` to 1. At the cap the product becomes `refused` and the counter stays. Attempt 2 is the floor on the deadline. A proposed date or amount does not increment. “Too much” only offers the floor. PUB-12 ends card 0, personal loan 2, car loan 1.
9. **Vague date.** Drops the today offer, increments `counters.vague`, uses no attempt. A partial says “Go on, please.” and changes nothing.
10. **Read-back.** One product goes straight to confirm. Several products wait for one joint read-back. PUB-13 clamps the loan to 23 October in the read-back; the event still carries 30 October.
11. **Recorded, notes, transfer.** The recorded sentence is said once, after the last `create_promise` success. Notes are chained before it, in `wrapup`, and never after a transfer. A transfer’s user turn calls the tool and does not speak.
12. **Support (amended again by §13.1).** The sympathy line sets `q=support_offer` and `counters.support_offered` to 1. Required substrings there: `sorry`, `customer support`. The discount turn is `kind=topic`, `t=terms`, `st=complete`. Its action is `say_exact` with `no other terms` and the support question again. It does not consume an attempt and it is not a refusal. §13 names `sentences.no_other_terms` and does not quote the full sentence.
13. **Close lines.** “Thank you, goodbye.” is exact when it is the whole farewell. Paid and the third wrong answer use `farewell_contains`.
14. **Opening.** Requires “digital assistant” and “Freya Bank”. Does not require “recorded”.
15. **Secondary reject.** `also=reject` has no `why`.
16. **“Around eleven”.** `tm=11:00`.
17. **Bare weekday.** `wk=none` unless the words say this or next. Public sequences say “this Friday”.
18. **Rejected, and the rejection stands in v3.1.** “Friday the 20th.” is `st=complete` with both labels. Not debatable. The reducer, via `date_from_spec`, detects the contradiction.
19. **Injection (amended).** Outranks `who` and identity in every phase. The identity-phase rows are not debatable.
20. **Tokens.** Scripted `n`. `last_tok` starts at `kstart`. Tool steps ignore `ev`.

## Multi-product (PUB-11..PUB-13)

PUB-11 and PUB-13 are the “date for all” path: one sentence states every product and asks all-today, one `prod=all` date agrees each product (PUB-13 clamps the loan in the joint read-back), one read-back, then `create_promise` chained with no speech, then the recorded sentence. No notes (PUB-11 is Brief A; PUB-13’s products both get a promise).

PUB-12 is the per-product path: the card date starts the personal-loan attempt, a cap refusal moves to the next product, one joint read-back names only the card, then `create_promise`, then the two `refused` notes, then “recorded”.

## Remaining ambiguity

These points are not resolved by the fixtures. They are not guessed into a ledger.

- **Hang-up after verification, while products are still `open` or `proposed` and nothing has been written.** §11.3 says the product-state slot, and does not name a row for that snapshot. `hangup.outcome` is null there. Named slots that are filled: before `who=self` → `not_reached` / `unclear`; after `who=self` and before verification → `not_verified` / `declined`; a succeeded transfer, a persisted promise, or every product `paid` use those outcomes. A promise or paid hang-up has `reason` null.
- **`sentences.no_other_terms` and `sentences.change_in_app` are not quoted in full.** §13 names the keys. The brief says “change it in the mobile app” (rule 36) and forbids offering a discount, waiver or plan (rule 33). PUB-05 checks the substrings `no other terms` and `customer support`. Extraction rows do not invent the rest of the sentence.
- **Busy has two mappings.** “I am busy, call me later.” is `kind=callback` and marked debatable because §13.1 also allows `t=stop`. The fixture does not add a `busy` topic or a `busy` outcome on the reducer state. A voicemail is `who=unclear`.
- **Re-saying an open question.** An ignored event changes no state, including ask counters. PUB-01 re-says the date-of-birth question and does not increment a counter. The contract also says ask counters increment when an ask is spoken. The re-say is not counted.
- **§11.2 help-first is not a public sequence.** One extraction row is `t=human` during the name question. The ask, the second human or “no”, the `general` transfer, and `close(transferred, human)` are not scripted. Adding them would invent a fourteenth public call.
- **§11.5 last-failure rows are not scripted**, except PUB-10’s one `create_promise` HTTP 500 followed by success. Not scripted: a pending call whose counters never moved (`status_code` null), `verify_identity` / `get_account` / `schedule_callback` retries, transfer’s last failure (continue, never say transferred), `add_note` skip, and Brief B’s `create_promise` last failure (product `failed`, note `service_error`, continue). Every `call_tool` does set `w_go` to `go`.
- **§11.6 reducer effects of one decline, one stop, or `who=handoff`** are described on the extraction rows. No public sequence walks explain-once, the second refusal, or the handoff re-ask.
- **A second “no” at read-back** (`q=what_to_change`, then agreed items `refused`) is not in the public scripts.
- **§11.7 and §13.2** are build-time enum checks (`map_to` or `block`). These reducer fixtures send only OAS values. The brief fixtures’ identity question is `phone_last4`. No sequence shows a blocked identity field or a mapped outcome.
