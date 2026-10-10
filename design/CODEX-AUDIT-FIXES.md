# Audit packages 1–3 + 5

Initial audit verification recorded at `5e89970`; the later authorized chat check and reducer follow-up are documented in `BULK-REFUSAL-FIX.md`.

Base: `657ab184fb5252db27766d9ee7a7245c7099329e`. Worktree: `/tmp/codex-audit`, branch: `codex-audit`.
Only this worktree was edited. No merge, push, Freya, chat API, or real model calls.

## Fixes

1. Close requests use the OAS role/field mapping in both the graph and lifecycle `end_of_call` tool. Optional empty/unresolved fields are removed by their actual field name; required fields and nonempty values are retained. Bridge enum checks and static request-value checks use that same mapping. Paid and promise keep their sourced outcome/reason pairs, including required reasons. A transport-error retry preserves the pair; the existing explicit server-reason recovery remains.
2. Resolved extraction controls notes, note reasons, transfer queues, identity gates and disclosure settings. Raw-text fallbacks only fill missing fields. Tests cover old ban/new permit, old permit/new ban, both file orders, and explicit false values.
3. Callback day restrictions (`today_or_next_business_day`, `next_business_day_only`, `today_only`) and inclusive/exclusive window boundaries are enforced. Unknown day rules, invalid hours/boolean flags, `customer_named` and `same_as_previous` are reported as unsupported ASSUMPTIONs and fail static validation, routing builds to L3 rather than substituting another rule.
4. Mandatory notes, callbacks, transfers and sourced speech cannot be stripped by L2. A full L3 candidate is preferred over an optional-feature partial build. A partial build is only used if no usable full candidate remains, with `partial_agent`, stripped features, and the L3 failure explicitly traced.

Multi-product amount clarification was deliberately not changed. `event_field.py` is byte-identical to the base; AST comparisons also confirm `_floor`, `amount_fits`, `amount_scale`, `api_amount`, `plan_amount`, `amount_event`, and `no_restated_amount` are unchanged. Brief A/B sequences and rehearsal ledgers remain green.

## Local verification

All 19 suites passed with Python audit hooks denying socket connections and external Claude/curl/wget subprocesses:

- `tests/test_reducer_sequences.py`: kit 13/13 exact sequences.
- `tests/test_rehearsal.py`: 33/33 ledgers.
- `tests/test_reducer_rules.py`
- `tests/test_reducer_gen.py`
- `tests/test_bridge_v2.py`
- `tests/test_packed_hub.py`: all 10 policy builds.
- `tests/selftest_all.py`: 200/200 scenarios across 10 policies.
- `tests/test_graph_walk.py`: sequences, lifecycle closes, retries and failure injection.
- `tests/test_oas_mutations.py`: 10/10 API variants match their expectations.
- `tests/test_audit_regressions.py`: 13 test methods, including strict enum/required/type checks on actual generated close bodies in both close paths and all 16 source closing-table rows.
- `tests/test_degrade.py`
- `tests/test_build.py`
- `tests/test_reducer_literals.py`
- `tests/test_reducer_props.py`: 3,000 random calls; 13/13 plain and packed hub replays.
- `tests/test_generator.py`
- `tests/test_selftest.py`
- `tests/test_walk_smoke.py`
- `tests/test_bridge_keys.py`
- `tests/test_oas_loader.py`

`git diff --check` is clean. No new dependencies.

The generator test used to overwrite tracked reference fixtures with a different saved extraction. It now validates its generated objects in memory without replacing those fixtures. Its incidental outputs were backed up and the reference fixtures restored from the base commit; no fixture changes are included.

## Not checked / limits

- Live Freya behavior and final benchmark scores are not established by these local tests. “Open call” voice-vs-chat clarification was requested; no live call has been started.
- `customer_named` and `same_as_previous` intentionally require L3; if L3 is unavailable, the builder fails explicitly rather than silently compiling a different rule.
- `test_generator.py` still reports existing `Ortiz` / `date_of_birth` literals in `event_field.py`. That file is unchanged; this warning predates these fixes.
