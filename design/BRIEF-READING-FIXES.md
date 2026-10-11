# Brief-reading regressions: raw-4 and raw-5

Local-only fixes on `codex-audit`, following `a8a30df`. No Freya, chat API, model calls,
integration changes, or pushes. Multi-product amount handling is unchanged.

## Fixes

1. **Bridge evidence.** Empty event speech stays empty; a customer trigger is not rewritten
   into an agent sentence. Unsourced rows, speech, aliases, floor/naming mappings and transfer
   mappings are dropped and reported as `ASSUMPTION`. A prohibition alone cannot authorize a
   close; discount questions preserve the pending support question. Product types are not
   accepted as conversational queue-map keys. `source_gaps` reports all remaining unquoted
   policy leaves (including contract defaults); the build's assumptions trace includes them.
   An unsupported or unsourced mandatory floor/route rejects the deterministic path rather
   than silently substituting a business rule. OAS bindings and internal protocol plumbing
   remain OAS/contract-derived, not fabricated brief policy.
2. **Per-band dates.** Optional `deadline.bands[].rule`, `roll`, and `source` travel through
   extraction, bridge, validation, trace and runtime. Old bands inherit the global rule.
   Frozen old extractions can recover a rule from an unambiguous quoted day count. Ambiguous
   counts, unsupported overrides or quotes missing from the supplied brief reject the main
   path. Raw-4's early deadline is **21 October**, late deadline **15 October** for its runtime
   `now`; these values exist only in fixtures, not builder code.
3. **Product routing.** Optional `products.route_by_type` binds an exact OAS queue and a
   sourced closing-table pair. The raw-5 legacy product event is recovered from its quoted
   exception. Routed products keep their original indices but are excluded from debt lines,
   offers, read-back, promises and notes. Transfers run after other product writes. Failed
   transfers are not recorded as successful. L2 cannot strip the mandatory transfer tool.
   Promise-slot detection no longer mistakes a transfer-precedence row that mentions
   other products' promises for the promise outcome.

## Regression inputs

`tests/fixtures/brief_reading/raw-{4,5}-single/` preserves the supplied brief, README and
expected cases from `fixtures-briefs`, plus the frozen `657ab18` extractions. Tests re-bridge
them without an LLM. No generated submission artifact is modified by this change.

`tests/test_brief_reading.py`: 10/10 tests, covering hardship accepted/declined, discount
continuation, unsourced content/mappings, negated close instructions, per-band dates,
calendar roll direction, legacy inheritance, ambiguous counts, unquoted routes, raw-5's
three expected ledgers, route-only/first-product routing, packed code, and a freshly
generated workflow walked with strict OAS request checks and transfer-failure injection.
The existing wildcard-floor bridge fixture now supplies its own test quote; its expected
floor remains unchanged.

## Verification

21 of 22 local suites pass; the synthetic suite retains its three pre-existing failures.
The broad run used a Python audit hook to forbid network connection/DNS and external
model/network CLI invocations. Build/save messages in unit tests are mocks.

- `test_brief_reading.py`: 10/10.
- `test_bulk_refusal.py`: 10/10.
- `test_reducer_sequences.py`: kit 13/13 exact.
- `test_rehearsal.py`: 33/33.
- `test_reducer_rules.py`, including multi-date rules: pass.
- `test_reducer_gen.py`: pass.
- `test_bridge_v2.py`: pass.
- `test_packed_hub.py`: pass.
- `selftest_all.py`: 200/200.
- `test_graph_walk.py`: pass, including injected graph defects.
- `test_oas_mutations.py`: 10/10 variants.
- `test_audit_regressions.py`: 13/13.
- `test_degrade.py`, `test_build.py`: pass (offline mocks).
- `test_reducer_literals.py`: no brief literals; renamed replay clean.
- `test_reducer_props.py`: packed public-sequence replay 13/13.
- `test_generator.py`, `test_selftest.py`, `test_walk_smoke.py`,
  `test_bridge_keys.py`, `test_oas_loader.py`: pass.
- `test_synthetic.py`: **117/120**, exactly the same on the pre-change `a8a30df` date
  and reducer modules: gen-006 PUB-09/PUB-10 queue swaps, gen-009 PUB-04 floor rounding.
  This script exits zero despite failures; its result text, not exit status, was checked.

## Remaining limits

- No live Freya score or fresh model extraction was measured. Local event replays do not
  prove natural-language extraction accuracy. Quote presence is not proof of semantic
  entailment; other policy leaves are reported, not globally converted into hard errors.
- Frozen raw-4 has `attempts.plan.*[0].date_rule=customer_named`, already unsupported on
  this branch. It still explicitly rejects the main path and requires L3. The scoped
  date/hardship regressions pass, but the whole frozen raw-4 build is **not** certified green.
- Synthesized business speech is not stored in the bridged policy. Existing generic
  reducer protocol fallbacks (clarification, farewell, acknowledgements) remain intact.
- No new multi-product amount clarification or unrelated synthetic-fixture repair was
  added. Existing unrelated generator warnings were left untouched.
