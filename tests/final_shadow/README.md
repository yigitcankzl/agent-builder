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
`valid_date`, `valid_date_words`, `invalid_date`, `corrected_date`, `account_label`, `relative_name`.
`amount_words` and `valid_date_words` exist only because the `in_words` style needs the value spelled out in
Turkish words.

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
  "enable_branches": ["hardship"]
}
```

The example above is entirely fictional. Rules:
- A persona is rendered only if every name in its `requires` has a non-empty value; otherwise it is listed under
  `skipped` with the missing names.
- A conditional persona is rendered only if its `branch` is in `enable_branches`.
- Any `{{…}}` left after filling raises `RenderError`.

Run: `python3 tests/final_shadow/render.py tests/final_shadow/persona_templates.json bindings.json -o rendered.json`
Output: `{"rendered": [{id, name, tags, risk_focus, turns}], "skipped": [{id, reason}]}`, with UTF-8 kept as is.

## Decisions that wait for the final zip

- How many identity questions there are and their format (one or two answers; whether `identity_answer_2` exists).
- Which business branches the documents define, and so which `enable_branches` to set.
- Real values for each placeholder, including the Turkish word forms for `in_words`, the date format and currency wording.
- Whether third-party contact has a policy (callback or not), which changes what `third_party_relative` tests.
- The expected outcome per persona: the oracle / expected ledger is deliberately not built yet.
