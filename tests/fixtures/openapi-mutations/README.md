# OpenAPI mutations

Ten local variants of `tools/openapi.json`. The seven tool names stay. Nothing here is called: the files are schemas and the bindings a correct bridge must produce.

Role names are the contract's at `72b59a4` (`design/REDUCER-CONTRACT.md`, §14.3).

Policy for every variant is `briefs/brief-a.md`. `sourced-alias` and `no-alias` also have `sources/codes.csv`. `customer_id` is a call variable. It stays a required body field and is not a canonical role.

`tool_args` maps a canonical role to the OAS body field. `tool_results` maps a fact to a response path. An enum binding is present only when the brief value is an exact OAS member, or the sourced alias names an OAS member. Anything else is an `api_mismatch` with `resolution: block`.

The kit leaves `close_call.reason` a free string. Those variants list it in `free_string_fields` and still record the brief words as the values to send. `close-enum` is the one that adds a reason enum.

A tool is `blocked` when the brief cannot call it: a required identity field is missing, a required write role has no property, or no brief queue or outcome binds. One blocked value does not by itself block a tool that can still send its other values.

## Variants

| Variant | What changed | Expected behaviour |
|---|---|---|
| amount-premium | `create_promise` `amount` is `premium` | Role `amount` binds to `premium`. The tool stays enabled. No mismatch. |
| product-id-policy | `product_id` is `policy_id` on `create_promise`, `add_note`, and each `get_account` product | Role `product_id` binds to `policy_id` on the request and the response path `products[].policy_id`. |
| identity-enum | `verify_identity.field` is `postcode`, `birth_year`, `policy_number_last4`, `company_number` | `date_of_birth` and `phone_last4` are blocks. `birth_year` and `policy_number_last4` are not substitutes. `identity.blocked` is true, `skip_missing_question` is false, and `get_account` must not be called. `verify_identity` is blocked. |
| queue-enum | Queues are `care`, `collector`, `switchboard` | `restructuring`, `general`, and `support` are blocks. `care` (the first member) is not a fallback. `transfer_to_agent` is blocked. |
| close-enum | Outcomes and reasons use other names. `service_error`, `callback`, `no_callback`, `deceased`, and `unclear` still match. | Near names (`arrangement`, `settled`, `failed_id`, `wrong_line`, and the rest in `api_mismatch`) are not conversions. No brief outcome binds, so `close_call` is blocked. The five exact reasons still bind. |
| paths-and-required | `verified` is `check.passed`. Attempts left are `check.attempts_remaining`. Products are `account.covers`. `ok` is `success`. `create_promise` has no `date`. | Result paths follow those keys. Role `date` is null. `create_promise` is blocked. No other property fills the date. |
| sourced-alias | Outcome enum contains `arrangement` and `arranged`, not `promise`. `sources/codes.csv` maps `promise` to `arranged`. | The alias is accepted. `promise` binds to `arranged`. `arrangement` is rejected. `close_call` stays enabled. |
| no-alias | `not_reached` is absent and `unreached` is present. The code list maps `not_reached` to `missing_value`, which is not in the enum. | The alias is not valid. `unreached` is not a substitute. That one outcome is a block. The other outcomes still bind, so `close_call` stays enabled. |
| wire-shapes | `verified` is the string `status` (`verified` or `failed`). Products have no `type`. Amounts are integer pence. `schedule_callback` has one `when` datetime. Every body and result schema is a `$ref` into `#/components/schemas`. | `status` binds to the verified fact. `type` is a missing fact and is not invented. 540.00 is sent as 54000. Roles `date` and `time` both bind to `when`. All seven tools stay enabled. |
| queue-untyped | `transfer_to_agent.queue` is a string with no enum. | `restructuring`, `general`, and `support` are sent as those words. The tool stays enabled. A missing enum is not a mismatch. |

## Negative cases

| Proof | Where |
|---|---|
| No nearest-enum mapping | `identity-enum`, `queue-enum`, `close-enum`, `no-alias`, and the rejected `arrangement` on `sourced-alias` |
| A required identity field is not skipped | `identity-enum`: `skip_missing_question` is false and `may_call_get_account` is false |
| A missing required write parameter blocks the write | `paths-and-required`: `create_promise` is blocked because `date` is absent |
| An unknown outcome is not converted | `close-enum` (every brief outcome) and `no-alias` (`not_reached`) |
| A sourced alias is accepted | `sourced-alias`: `promise` → `arranged` |
| A string status is not a boolean | `wire-shapes`: verified fact path is `status`, values `verified` and `failed` |
| No product type is not inferred | `wire-shapes`: `missing_facts` for `type` |
| Minor units | `wire-shapes`: `amount_encoding.factor` is 100 |
| One datetime keeps both roles | `wire-shapes`: `date` and `time` bind to `when` |
| No queue enum is not a block | `queue-untyped` |
