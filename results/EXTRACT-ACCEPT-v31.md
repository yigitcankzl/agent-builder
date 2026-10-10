# Extraction acceptance run, contract v3.1 (2026-10-10)

- **Run:** one run, chat API only, generated v3.1 `ev` field (`builder/engine/event_field.py` at `c2f49ec`), no prompt
  changes during the run.
- **Cases:** Cursor's 79 cases (`fixtures-briefs` `ff2b94b`, `tests/fixtures/reducer/extraction_cases.json`). The
  fixture file was read only.
- **Raw output:** `results/extract_accept_v31.json`, log `runs/extract_accept_v31.log`.

## Measured
- 79/79 measured; 0 unmeasured, with no HTTP errors (no re-send rule in force).
- 12 debatable cases are reported separately: 5/12 exact.
- **Gate set: 67 non-debatable cases.**

| Gate | Result | |
|---|---|---|
| identity skip / wrong tool action = 0 | identity skip 0/5; **wrong-trigger 3** (EX-11, EX-17, EX-70: `accept` where `yes` was expected) | **FAIL** |
| date / amount fields 100% | 19/19 | PASS |
| state change on partial/none = 0 | 0 violations / 3 | PASS |
| kind ≥ 95% | **59/67 = 88%** | **FAIL** |
| unsure → clarify/talk | no `ambiguous` rows in the gate set (choice 18 is `st=complete`) | PASS (vacuous) |

Extracted (regex-valid) 67/67. `st` 61/67. All expected fields 57/67.

## Per family (exact match: kind, st and every expected field; debatable included)
| Result | Families |
|---|---|
| 100% | accept, date-ambiguous, date-correction (4), decline, handoff, hardship, human, identity-date (3), identity-phone (2), injection (3), multi (3), paid, partial (4), purpose, restructure, robot, scam, smalltalk, stop, third-party-ignore, who-deceased, who-relative, who-self, who-wrong-number |
| failing | amount 3/4, busy 0/1, callback 0/2, change-promise 2/4, dispute 1/2, no 0/2, reject 0/3, repeat 1/2, terms 2/3, unmatched-yes 0/2, voicemail 0/1, who-unclear 0/1, yes 0/3 |

## Failure classes (gate set)
1. **`accept` for a bare "yes"** (EX-11, EX-17, EX-70). Under §11.1, `yes` and `accept` act identically for q ∈
   {pay_today, offer, readback}. With any other q (EX-70 is `q=id_date_of_birth`) both are ignored. **No behavioural
   difference.**
2. **`st=none` on short yes/no/reject** (EX-14, EX-16, EX-19, EX-69; debatable EX-13, EX-18). This is dangerous if
   the reducer reads `st=none` as "nothing happened": a real "No." would be dropped.
3. **Callback as `date`** (EX-47: `kind=date`, `tm` missing; EX-48: correct, but an extra `also=date`). The
   third-party time was lost in EX-47.
4. **Topic vs amount/date** (EX-73, EX-74 change_promise; EX-77 terms). The model ranked the amount/date above the
   topic. EX-73/74 occur after a persisted promise, where §13.1 already turns any date/amount into the change_in_app
   line, so there is **no behavioural difference**. EX-77 ("200 as a discount") would be handled as a below-floor
   amount, not the terms line: a real difference, but brief-compatible (A27).
5. **who=unclear vs other** (EX-79; debatable EX-05). With `q=confirm_name` open, the reducer re-asks the name in
   both cases (counted when spoken), so there is **no behavioural difference**.
6. **EX-55:** extra `also=reject`. `also` is advisory, so no difference.

## Offline behavioural rescoring (the same raw outputs, no new run)
Proposed reducer-side normalisation, applied to both the expected and the actual event:
- (a) `accept` ≡ `yes` when q ∈ {pay_today, offer, readback};
- (b) `st=none` with `kind != other` → `complete`;
- (c) `date` in the third_party phase → `callback`;
- (d) `other` while `q=confirm_name` → `who` (unclear).

Result: kind **63/67**. The remaining 4 are EX-70 (ignored either way under §11.1), EX-73/74 (change_in_app by
§13.1) and EX-77 (real), so behaviourally **66/67 = 98.5%**.

## What I would change (not applied; the prompt was not tuned)
1. **Contract v3.2 reducer normalisation** (a)–(d) above, plus "an event with `kind ∈ {yes, no, accept, reject}`
   never has a meaningful `st=none`".
2. **Prompt:**
   - "st=none only together with kind=other";
   - one callback example with a time (`tm=11:00`) in the third-party phase;
   - one example where a topic outranks an amount ("could you take 200 as a discount" →
     `kind=topic;t=terms;also=amount;amt=200`).
3. **Gate definition:** score `kind` after the normalisation, because the reducer acts on the normalised event. The
   raw label accuracy stays reported.
4. **Re-run once on the same 79 cases** after 1–2, as a new acceptance run.
