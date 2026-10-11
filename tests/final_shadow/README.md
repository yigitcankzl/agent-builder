# Final shadow personas

Reusable Turkish customer-behaviour templates for testing a phone agent once the final case opens. They describe
**how** a customer talks, never final-case facts: no names, dates, amounts, identity fields, outcome codes, queues,
tool names or bank rules. There is no oracle and no expected ledger here yet.

Offline only. Nothing here calls Freya, a model, a chat API or the network.

## Files

| File | Purpose |
|---|---|
| `persona_templates.json` | The templates (schema below) |
| `render.py` | Fills templates from a bindings file into deterministic JSON |
| `test_templates.py` | Schema, coverage, placeholder and no-fact checks: `python3 tests/final_shadow/test_templates.py` |

## Template schema

Top level: `version`, `language` (`tr`), `placeholders` (every placeholder name the templates may use), `personas`.

Every persona has exactly these keys:

| Key | Type | Meaning |
|---|---|---|
| `id` | string | Unique, snake_case |
| `name` | string | Short Turkish name |
| `description` | string | What the customer does |
| `tags` | list | Behaviour tags. The five official speaking styles are `pieces`, `corrects`, `talkative`, `asks_back`, `in_words`; a template carries at most two of them |
| `requires` | list | Placeholders that must be bound. Every `{{x}}` used in the persona must be listed |
| `turns` | list of strings | Ordered customer turns. Text in parentheses is a stage direction for whoever plays the customer |
| `risk_focus` | string | The agent weakness the template targets |
| `conditional` | bool | `true` for business-policy behaviour (hardship, already paid, …) that only makes sense if the final documents define that branch |
| `branch` | string or null | The branch name a conditional persona needs; `null` otherwise |

Placeholders: `customer_name`, `identity_answer_1`, `identity_answer_2`, `amount`, `amount_words`, `other_amount`,
`valid_date`, `valid_date_words`, `invalid_date`, `corrected_date`, `account_label`, `relative_name`, and for the
statement-debt case `currency`, `other_currency`, `target_week`, `corrected_week`, `target_week_words`, `card_label`.
`amount_words`, `valid_date_words` and `target_week_words` exist only because the `in_words` style needs the value
spelled out in Turkish words.

Every template that needs an identity answer carries the `identity` tag.

## Bindings format (filled in after the final zip opens)

```json
{
  "values": {
    "customer_name": "‹müşteri adı›",
    "identity_answer_1": "‹ilk kimlik cevabı›",
    "identity_answer_2": "‹ikinci kimlik cevabı›",
    "amount": "‹tutar›",
    "amount_words": "‹tutarın yazıyla hali›",
    "valid_date": "‹geçerli tarih›",
    "valid_date_words": "‹geçerli tarihin yazıyla hali›",
    "invalid_date": "‹geçersiz tarih›",
    "corrected_date": "‹düzeltilmiş tarih›",
    "account_label": "‹hesap etiketi›",
    "relative_name": "‹yakının adı›"
  },
  "enable_branches": ["hardship"],
  "not_applicable_tags": []
}
```

The example above is entirely fictional. Rules:
- A persona is rendered only if every name in its `requires` has a non-empty value; otherwise it is listed under
  `skipped` with the missing names.
- A conditional persona is rendered only if its `branch` is in `enable_branches`.
- A persona carrying a tag in `not_applicable_tags` is skipped with the reason `not applicable: <tag>`.
- Any `{{…}}` left after filling raises `RenderError`.

Run: `python3 tests/final_shadow/render.py tests/final_shadow/persona_templates.json bindings.json -o rendered.json`
Output: `{"rendered": [{id, name, tags, risk_focus, turns}], "skipped": [{id, reason}]}`, with UTF-8 kept as is.

## Decisions for the final zip (statement-debt line, opened 11 October)

The case is a Turkish credit-card statement-debt line. The phone menu has already verified the caller, and the
workflow receives `customerNumber` and `now`. The agent reads the statement debt in TRY / USD / EUR / GBP and the due
date, can move the statement week, can e-mail the statement to the address on file, and hands over to a human for a
payment or on request.

- Identity: none in the call. Set `"not_applicable_tags": ["identity"]` and leave every `identity_answer_*` unbound.
  The seven identity templates are kept but skipped (`not applicable: identity`).
- Statement templates (tag `statement`, `handover` or `privacy`):

  | id | styles | covers |
  |---|---|---|
  | `debt_currency_switch` | asks_back | debt in one currency, then a switch to another |
  | `due_date_talkative` | talkative | due date asked amid chatter |
  | `move_week_pieces` | pieces, in_words | new statement week, in words, over two turns |
  | `move_week_corrects` | corrects | ambiguous "haftaya", then a week, then a correction |
  | `email_address_asks_back` | asks_back | statement by e-mail; which address it goes to |
  | `pay_now_handover` | — | wants to pay now → handover, offers card details |
  | `asks_for_person` | — | asks for a person, insists |
  | `privacy_card_number` | asks_back | full card number; a spouse's card debt |
  | `debt_and_email_one_turn` | talkative | debt in a currency and the e-mail in one turn |
  | `multiple_cards_choice` | asks_back | conditional, branch `multiple_cards`: which card |

- Bind `currency` / `other_currency` to how a customer names two different currencies of the four (Turkish
  words). `target_week` / `corrected_week` / `target_week_words` must be weeks the documents allow, and the corrected
  week must differ from the first. `card_label` only if the test customers have more than one card; then enable
  `multiple_cards`.
- Payment-flow templates (`pieces_amount_date`, `in_words_amount_date`, `question_plus_payment`, `repeats_answer`,
  `topic_change_resume`, `accepts_offer`, `corrects_date`, `ambiguous_date`) assume the agent takes a promise. Here a
  payment is a handover, so bind their placeholders only to test that they hand over and record nothing.
- Still open: which weeks are allowed and how far ahead (the documents disagree, so read the latest), the e-mail
  address-reading rule (masked or not), and the expected outcome per persona. The oracle is still not built.

## Decisions that wait for the final zip

- How many identity questions there are and their format (one or two answers; whether `identity_answer_2` exists).
- Which business branches the documents define, and so which `enable_branches` to set.
- Real values for each placeholder, including the Turkish word forms for `in_words`, the date format and currency wording.
- Whether third-party contact has a policy (callback or not), which changes what `third_party_relative` tests.
- The expected outcome per persona: the oracle / expected ledger is deliberately not built yet.
