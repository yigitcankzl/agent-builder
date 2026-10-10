# Product-specific refusals of the bulk ask

Worktree `/tmp/codex-audit`, branch `codex-audit`, based on audit fix `5e89970` (original integration base `657ab18`). No merge or push.

## Counterexample and fix

The live PUB-12 `in_words` failure, call `1861545f-f467-47cc-a697-4bc0d370f8cb`, promised the card correctly but offered too many times on the other products. The initial explicit refusals of the loan and car at the bulk ask were not counted.

The optional extraction payload `refused=2,3` lists **1-based product positions in account order**, separately from the date/amount proposal's `prod`. Product names and “the others/the rest” resolve to this list only when clearly identifiable. An unqualified “no”, rejecting a date/amount, “not today”, affordability complaints, and incomplete speech leave it empty. No new event kind, second extraction field, or policy schema is needed.

On a complete reply to the verified customer's bulk `pay_today` question, explicit targets consume one attempt each. The next offer uses the existing per-product plan; exhausted products become refused, with notes written by the existing wrap-up queue only if enabled. Duplicate positions count once; malformed/out-of-range lists do not charge products. A proposed product cannot be charged as refused. The policy's explicit `flat_refusal_uses_attempt: false` disables the new consumption.

The original unqualified bulk refusal and all single-product behavior remain unchanged. The amount extraction instruction and amount-handling functions were not changed. AST comparisons against `657ab18` also confirm `date_event` and `reject_event` are unchanged.

## Regression and verification

`tests/test_bulk_refusal.py` first reproduced five failures before the fix. Its final ten tests cover the live shape and exact ledger, unqualified “no”, distinct targets and plan caps, duplicate/invalid references, partial events, the disabled policy flag, disabled notes, mixed question/proposal delegation, proposed-product protection, reordered accounts, the extraction grammar, and the actual packed code string. Replaying a stale event does not consume another attempt.

For the live shape: card promise `p1`, 510 on 15 October; personal loan gets one further offer (attempt 2, 440 on its deadline), then no more; car gets no offer. Successful writes are exactly one promise and one refused note for each other product, followed by the sourced promise close.

All 20 local suites passed with network/external-model audit guards: the previous 19 in `CODEX-AUDIT-FIXES.md` plus `test_bulk_refusal.py`. Kit sequences remain 13/13, rehearsal 33/33, `multi_date_rules` (in `test_reducer_rules.py`) remains green, packed hub builds cover all ten policies, and selftest_all remains 200/200. No tracked fixtures were regenerated. No dependency was added.

## Separate chat API check of the earlier audit fix

After the user explicitly allowed chat API calls, one fresh workflow was saved and published; no sweep workflow was edited and no simulation was launched.

- Workflow `54983467-34b1-47e9-bcee-1fc70f43c716`, agent `197d8f1f-4787-4653-b4c2-70663f148e48`, slot `codex-audit-live-5e89970`.
- PUB-08 practice chat, call `6a7c3e5a-fca3-47b0-bc9f-8a3032a23dad`. Identity passed before account retrieval.
- The last “already paid” chat request returned HTTP 504 after about 32 seconds. It was **not resent**; the owned chat was ended once and its trace/ledger inspected.
- The server nevertheless executed the graph `close_call` successfully with outcome `paid`, no empty reason field. The lifecycle close used the same body; its duplicate close was rejected as already closed. The ledger was correct (`paid`, reason null, no promises/notes) and the ledger scorer passed.
- This is evidence of correct live close bodies, **not** a completed conversation or judge/pass^3 result. Report and exported workflow remain in ignored `results/audit-chat/`.

## Not checked / next verification

The new `refused` extraction prompt and PUB-12 judge behavior have not been measured live. Rebuild the workflow so it contains both the new extraction prompt and reducer, then rerun PUB-12 `in_words` when the platform allows a reliable run. Previously saved agents do not acquire these code changes automatically. The main integration worktree remains untouched.
