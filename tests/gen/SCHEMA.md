# Generated policy schema

`expected_policy.json` is the neutral, effective policy consumed by `oracle.py`. It is not a workflow and does not mirror builder output. Raw-source memos have already been applied to it.

## Output layout

Each generated directory contains:

- `brief.md`: the single input text for a builder.
- `expected_policy.json`: final ground truth in the schema below.
- `cases.json`: 10 cases accepted by `tools/run_cases.py --cases`.
- Raw style only: `email.md`, `policy-extract.md`, `later-memo.md`, and `codes.csv`. `brief.md` concatenates those four sources in that order. The later memo wins on every path listed in `generation.memo_overrides`.

The generator is deterministic for a seed:

```bash
python tests/gen/brief_gen.py -n 6 --seed 20261010 --style mixed --out /tmp/generated
```

The output directory must be empty. The generator and oracle use only the Python standard library and make no network calls.

## Top-level fields

| Field | Meaning |
|---|---|
| `schema_version` | Integer schema version, currently `1`. |
| `policy_id` | Stable id used in each case's `brief` field. |
| `bank` | `name` and the exact recorded-line `opening`. |
| `identity` | Ordered `questions` and total `wrong_answer_limit`. Supported question semantics are `date_of_birth`, `phone_last4`, `postcode`, and `birth_year`. |
| `calendar` | `business_weekdays` as Python weekday numbers (`0` Monday through `6` Sunday), plus ISO-date `holidays`. |
| `lateness_bands` | Ordered, non-overlapping inclusive days-late ranges. |
| `floor_rule` | How to compute the minimum acceptable amount. |
| `accepted_amount_range` | Bounds for an amount volunteered by the customer. |
| `callback_window` | Permitted dates and inclusive `HH:MM` bounds. |
| `codes` | Semantic-to-ledger mappings for outcomes, close reasons, note reasons, and transfer queues. |
| `required_sentences` | Exact text keyed by the event when it must be spoken. |
| `special_situations` | Actions for dispute, paid, hardship, restructure, human request, deceased, and wrong number. |
| `multi_product` | Product ordering, per-product date/notes, transfer, and final-outcome rules. |
| `tools` | The unchanged seven tool names. |
| `generation` | Seed/style metadata. For raw briefs, `memo_overrides` contains `path`, superseded `before`, and effective `after`. |

## Lateness bands and persuasion

Each band has `name`, inclusive `min_days_late` / `max_days_late`, a `deadline`, and an ordered `persuasion_attempts` array.

```json
{
  "deadline": {"count": 7, "unit": "business"},
  "persuasion_attempts": [
    {"amount": "full", "date": {"type": "last_business_day_this_or_next_week"}},
    {"amount": "floor", "date": {"type": "deadline"}},
    {"amount": "floor", "date": {"type": "offset", "count": 4, "unit": "calendar"}}
  ]
}
```

Counts start after `variables.now`. A calendar deadline on a closed day means the preceding business day. A persuasion date after the deadline is clamped to the deadline. `refuse ×n` means the customer refuses `n` persuasion offers and accepts the next one if one remains.

## Floor and accepted range

`floor_rule.type` is one of:

- `account_field`: `fields` maps each product type to `minimum_payment` or `instalment_amount`.
- `percent`: percentage of `past_due`, then `rounding`.
- `fixed`: literal `amount`.
- `max_fixed_percent`: greater of `fixed` and the rounded percentage.

`rounding` has `mode` (`nearest`, `up`, or `down`) and a positive decimal `increment`. Money is finally represented to two decimal places.

`accepted_amount_range.minimum` is `floor` or `full`; `maximum` is `past_due`. The two boolean inclusive flags specify the endpoints. A floor explicitly offered after “too much” or by a persuasion rule remains valid even when unsolicited partial amounts are disallowed.

## Codes and special situations

Code keys are semantic; values are the literal arguments expected in the ledger. This lets the oracle reason about `hardship` while a generated brief may require the close reason `financial_difficulty`. Note reasons stay within the supplied OpenAPI's enum. Queue values stay within its three queue names, but their semantic assignment can vary.

Each special situation states semantic `outcome` and `reason` keys. Transfer situations also state a semantic `queue`; hardship additionally uses `transfer_reason` when support is accepted.

## Multiple products

`enabled` selects single- or multi-product behavior. When enabled:

- products are processed in `account` order or by `highest_days_late`;
- `shared_date_rule: clamp_each_to_its_deadline` applies one named date independently;
- `note_unresolved_products` records a note for each product without a promise;
- `suppress_notes_on_transfer` removes all notes on any transfer;
- `promise_wins` makes at least one recorded promise win unless the call transfers.

## Oracle intents

`expected_ledger(policy, customer, intent)` accepts a dictionary or these short strings: `pay today`, `name date:YYYY-MM-DD`, `too much`, `refuse ×N`, `dispute`, `paid`, `hardship`, `restructure`, `human`, `third party`, `wrong number`, and `deceased`.

Dictionary intents add details such as `date`, `amount`, `accept_adjustment`, `accept_transfer`, `callback_date`, and `callback_time`. A multi-product intent uses `by_product`, keyed by `p1`, `p2`, and so on. `identity_fail` and `identity_decline` are also supported for identity-only test paths.

The returned object is exactly the ledger subset scored by `tools/score.py`: `outcome`, `reason`, `promises`, `notes`, `callbacks`, and `transfers`.

## Live public-case compatibility

The requested neutral space includes four identity fields. The supplied OpenAPI and public mock expose only `date_of_birth` and `phone_last4`, and public cases contain no postcode. Therefore `write_set()` freezes runnable cases with those two questions (in randomized order). `generate_policy()` itself accepts the full identity pool for offline policy/oracle tests. Supporting live postcode verification requires an extended mock/OpenAPI and customer fixtures; the generator does not pretend the current service can do it.
