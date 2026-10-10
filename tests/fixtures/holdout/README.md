# Extraction holdout

Frozen. `extraction_holdout.json` is contract v3.1 (`aaab3d5`), same shape as `tests/fixtures/reducer/extraction_cases.json`. 30 cases, ids HO-01..HO-30. Customer wording is not taken from the reducer extraction file. Do not edit the JSON after the freeze commit. A later mistake should be reported, not patched.

`debatable: true` is excluded from the gates. One case: HO-09, "Can't."

| Family | Count | Ids |
|---|---|---|
| yes, pay today | 1 | HO-01 |
| yes, offer | 1 | HO-02 |
| yes, read-back | 1 | HO-03 |
| yes, help-first | 1 | HO-04 |
| yes, support offer | 1 | HO-05 |
| accept, offer | 1 | HO-06 |
| no, read-back | 1 | HO-07 |
| no, help-first | 1 | HO-08 |
| short refusal | 1 | HO-09 |
| callback with a time | 1 | HO-10 |
| busy, as a callback | 1 | HO-11 |
| change_promise, with a date or an amount | 2 | HO-12, HO-13 |
| terms, with a date or an amount | 2 | HO-14, HO-15 |
| dispute | 1 | HO-16 |
| unclear speaker | 1 | HO-17 |
| voicemail | 1 | HO-18 |
| date | 2 | HO-19, HO-20 |
| amount | 2 | HO-21, HO-22 |
| identity | 2 | HO-23, HO-24 |
| injection | 2 | HO-25, HO-26 |
| partial | 2 | HO-27, HO-28 |
| multi-product | 2 | HO-29, HO-30 |

A bare yes stays `kind=yes`. `Nope` at help-first is `kind=no`. Busy and voicemail are not topics.
