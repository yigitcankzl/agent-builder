# Brief-reading fixtures (independent)

Synthetic fixtures that test whether a builder **extracts policy correctly** from bank briefs. Written without consulting `builder/` or any policy extractor — answers are grounded only in these files and `briefs/brief-a.md`.

Diff extractor output against each `*.expected.json`. Use `*.cases.json` for a few behavioural spot-checks that follow from the extracted rules.

## Layout

| Path | Role |
|---|---|
| `mut-01.md` … `mut-05.md` | Brief A with a few realistic rule changes; everything else kept verbatim |
| `mut-0N.expected.json` | Canonical extracted policy for that mutation |
| `mut-0N.cases.json` | 2–3 spot-check scenarios (`now`, `days_late`, request → expected action) |
| `raw-a/` | Unseen-style “raw bank material” rewrite of Brief A |
| `raw-a.expected.json` | Merged policy after applying memo precedence |
| `raw-a.cases.json` | Spot-checks for superseded rules |
| `README.md` | This file |

## Mutations (catch single-field misreads)

| Fixture | What changed | Designed to catch |
|---|---|---|
| **mut-01** | Holiday list replaced; business days **Monday–Saturday** | Hard-coded Mon–Fri calendars; stale holiday lists; treating Saturday as non-working |
| **mut-02** | Deadline bands: 1–10 → 15th BD, 11–60 → 5th BD; scope to 60 days late | Assuming Brief A’s 1–7 / 8–45 cutovers; wrong `business_days_after_today` |
| **mut-03** | Persuasion early=**0**, late=**3**; floor = **30% of past due, round up** for all products | Ignoring zero-attempt early band; still reading `minimum_payment` / `instalment_amount` |
| **mut-04** | Identity: **postcode** then **year of birth**; **2** wrong answers | Keeping DOB / phone-last-four; failing only after three wrongs |
| **mut-05** | `not_reached` → **`no_contact`**; `unclear` → **`ambiguous`**; new reason **`busy`** | Emitting legacy outcome/reason strings; dropping new reasons |

## Raw material (`raw-a/`)

Mirrors the final’s “messy pack”: rules are scattered and phrased differently from Brief A.

| File | Contents |
|---|---|
| `email-from-head-of-collections.eml` | Operational guidance: opening, identity, callback window, many close reasons, required asks |
| `policy-extract.md` | Older July 2026 policy (calendar, bands with **7th** BD late deadline, floor fields, old SMS sentence) |
| `memo-2026-10-01.md` | **Supersedes** the extract on: new holiday `2026-10-19`, late deadline → **5th** BD, new confirmation sentence |
| `codes.csv` | Internal outcome/reason codes → API `outcome` / `reason` strings |

**Precedence:** where memo and policy extract conflict, the memo wins. Unmentioned extract rules (and the email’s operational detail) remain in force. A correct reader must not keep the extract’s late deadline, holiday list, or confirmation sentence.

## Expected JSON shape

Each `*.expected.json` exposes (with `value` + `source.file` + `source.quote` per field):

- `holidays` — ISO dates  
- `business_weekdays` — `0` = Monday … `6` = Sunday  
- `deadline_bands` — `{band, min_days_late, max_days_late, business_days_after_today}`  
- `persuasion_attempts` — per band  
- `floor_rule` — per product type  
- `identity` / `identity_wrong_answer_limit`  
- `outcome_table` — `{outcome, reason, when}` (raw-a also notes internal codes)  
- `required_exact_sentences`  
- `callback_window`  
- `raw-a` only: `superseded_rules` (what changed, old/new, which file won)

## Spot-check cases

Each case includes `now`, `days_late`, a `customer_request`, and `expected` (action + ISO dates / outcomes as applicable). Deadlines count **business days after** the calendar date of `now`, skipping weekends (or Sunday only in mut-01) and listed holidays.

Example (Brief A / late band): `now=2026-10-14`, `days_late=9`, customer asks `2026-10-30` → offer deadline `2026-10-23`. Under **raw-a** (memo), the same inputs offer `2026-10-22`.

## Synthetic data

All customers, debts, holidays named for narrative colour, and email addresses are fictional.
