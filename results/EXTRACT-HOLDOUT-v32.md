# Extraction holdout run, contract v3.2 (2026-10-10)

- **Run:** one run, chat only, `ev_field(policy)` of the bridged A+B policy (runner `88be179`), no prompt tuning, no
  re-send rule.
- **Cases:** frozen holdout `fixtures-briefs` `e3fbf0e`, `tests/fixtures/holdout/extraction_holdout.json` (30 cases).
  The cases were read only after the run.
- **Raw output:** `results/extract_holdout_v32.json`, log `runs/extract_holdout_v32.log`.

## Measured
- 30/30 measured; 0 unmeasured, with no HTTP errors.
- HO-09 is debatable and outside the gates; it got `kind=no` instead of `reject/flat`.
- **Gate set: 29 cases.**

| Gate (as defined) | Result | |
|---|---|---|
| identity skip / wrong action = 0 (normalised) | identity skip 0/2; **wrong action 1** (HO-05) | **FAIL** |
| date / amount fields 100% | **11/13** (HO-20, HO-29) | **FAIL** |
| partial / none state change = 0 | 0 / 1 | PASS |
| kind ≥ 95% after normalisation | **25/29 = 86%** (raw 22/29 = 76%) | **FAIL** |
| unsure → clarify/talk | no ambiguous rows | PASS (vacuous) |

Extracted (regex-valid) 29/29. `st` 28/29. All expected fields 17/29.

## Per family (exact match)
| Result | Families |
|---|---|
| 100% | accept-offer, amount (2), busy, callback, change-promise (2), dispute, identity-date, identity-phone, injection (2), no-help-first, partial (2) |
| failing | date 0/1, date-correction 0/1, multi-product 1/2, no-readback 0/1, short-refusal 0/1, terms 1/2, voicemail 0/1, who-unclear 0/1, yes-help-first 0/1, yes-offer 0/1, yes-pay-today 0/1, yes-readback 0/1, yes-support 0/1 |

## Every gate-set failure, and whether the reducer would act differently
| Case | Raw ev vs expected | Behaviour | Call |
|---|---|---|---|
| HO-01 yes-pay-today | `accept` vs `yes` | **Same.** Normalisation (a) | 7dfb0b2a |
| HO-02 yes-offer | `accept` vs `yes` | **Same.** (a) | 876d7fa8 |
| HO-03 yes-readback | `accept` vs `yes` | **Same.** (a) | 979d311e |
| HO-05 yes-support (q=support_offer) | `accept` vs `yes` | **Same.** §11.1 maps yes and accept to transfer(support). Counted as "wrong action" only because (a) is limited to pay_today/offer/readback | cf9e10bf |
| HO-04 yes-help-first | `other;st=none` vs `yes` | **Same.** With q=help_first, yes → free talk and other → free talk | f6f66cd5 |
| HO-07 no-readback ("That's not what I agreed.") | `topic;t=dispute` vs `no` | **DIFFERENT.** A dispute at read-back closes no_promise/dispute instead of asking what to change. **Real error** | 7905794b |
| HO-17 who-unclear ("Sorry, who is this?") | `topic;t=purpose` vs `who=unclear` | **Slightly different.** Both re-ask the name, but the purpose path does not count the ask (A3 counts it) | 2abd5c4f |
| HO-18 voicemail | `who=other;party=wrong_number` vs `who=unclear` | **DIFFERENT.** Closes `not_reached/wrong_number` instead of re-asking, then `unclear`. **Real error** | 4ed6596e |
| HO-20 date-correction ("the Monday after") | `wk=next` vs `wk=none` | **Same date** (both 2026-10-19 by `date_from_spec`) | b34c93cb |
| HO-29 multi-product ("on the 30th") | `m=` vs `m=10` | **Same date** (2026-10-30) | e06e01d3 |
| HO-14 terms | `also=date` vs `also=date_amount` | **Same.** `also` is advisory; t, d and amt correct | a52c243f |
| HO-19 date | extra `also=accept` | **Same.** Advisory | c8782b53 |

**Behavioural summary: 26/29 act the same.**
- 2 real errors: HO-07 (dispute vs no at read-back) and HO-18 (voicemail read as wrong number).
- 1 small difference: HO-17 (an ask counter).

## What I would change (not applied; the holdout is spent)
1. **Normaliser (contract):** extend (a) to every open `q`, since §11.1 maps `yes` and `accept` identically in all of
   them; and treat `other;st=none` under `q=help_first` as `yes`. Score the date gate on the computed day, not the raw
   labels.
2. **Reducer (safer, no prompt):**
   - a `t=dispute` while `q=readback` is treated as `no` (what to change) unless the product was already disputed;
   - in the opening, `party=wrong_number` closes only on an explicit wrong-number statement. The extractor still has
     to tell that apart, so this one needs a prompt example: "an answering machine or voicemail is who=unclear".
   - `t=purpose` in the opening counts as an ask (A3).
3. **Prompt:**
   - one voicemail example → `who=unclear`;
   - one "That's not what I agreed" at read-back → `kind=no`.
   A new frozen holdout is needed to measure these; this one must not be reused for tuning.
