# Date engine — independent black-box test spec

This document and `date_cases.json` are an **implementation-independent oracle**.
They are derived only from the official briefs and docs listed below.
They must not be read against production date-engine code; if another agent’s fixtures disagree, keep the brief citation and do not auto-accept their expected values.

## Official sources

| ID | Path |
|---|---|
| A | `briefs/brief-a.md` (same text as `/home/kizil/Downloads/build-the-builder-v3/build-the-builder/briefs/brief-a.md`) |
| B | `briefs/brief-b.md` |
| PTS | `public-test-set.json` (corroboration of computed deadlines / holiday snap only) |
| WF | `docs/workflow-format.md` (extraction stickiness / relative-date extraction behaviour) |
| TC | `docs/tools-and-code.md` (variables persist; code may compute date facts) |

## Fixture contract

Each case in `date_cases.json` is one black-box evaluation of a date resolver.

| Field | Meaning |
|---|---|
| `id` | Stable case id |
| `description` | What the case checks |
| `source_refs` | Brief/doc citations (`file`, `rule`, `quote`) |
| `policy` | Holiday list and band→deadline offsets; **injected**, not hard-wired in the engine under test |
| `current_state` | Call `now`, products (`product_id`, `days_late`), prior per-product date state, flags |
| `extraction` | This turn’s date signal (not free-form NL parsing of the whole transcript) |
| `expected` | Oracle outcomes for deadlines and per-product resolve actions |
| `metamorphic` | Optional link to a base case and the policy/state mutation |

### `policy`

```json
{
  "holidays": ["YYYY-MM-DD", "..."],
  "bands": [
    {"id": "early", "days_late_min": 1, "days_late_max": 7, "deadline_business_days_after_today": 12},
    {"id": "late",  "days_late_min": 8, "days_late_max": 45, "deadline_business_days_after_today": 7}
  ]
}
```

Business day = Monday–Friday and not in `policy.holidays`.

### `current_state`

| Key | Meaning |
|---|---|
| `now` | Call clock (`YYYY-MM-DDTHH:MM`). **All** calendar rules use this date, never the wall clock (A §2). |
| `products` | Ordered list; Brief B walks this order (B §4). |
| `dates` | Prior accepted / last-handled ISO date per `product_id`, or `null`. |
| `vague_ask_used` | Whether the one exact-day ask of rule 21 already happened. |
| `turn` | Optional label for multi-turn sequences in the same scenario family. |

### `extraction`

The resolver does **not** invent speech. The fixture states what this turn supplied:

| Key | Meaning |
|---|---|
| `mentioned_this_turn` | `true` only if the customer uttered a date/period this turn. If `false`, prior `dates` must not be re-snapped. |
| `kind` | `absolute` \| `relative_weekday` \| `vague` \| `none` \| `confirm_repeat` |
| `date` | ISO date when `kind` is `absolute` or `confirm_repeat` |
| `relative` | `{ "which": "this"\|"next", "weekday": "monday"…"sunday" }` for rule 22 |
| `vague` | Token such as `next_week`, `end_of_month`, `salary` (rule 21) |
| `scope` | `all` (one date for every product) or `product` |
| `product_id` | Required when `scope` is `product` |

### `expected`

| Key | Meaning |
|---|---|
| `deadlines` | Map `product_id` → ISO deadline |
| `products` | Map `product_id` → resolve result |

Each product result:

| `action` | Meaning |
|---|---|
| `accept` | Named/resolved date is valid; record it |
| `offer_next_business_day` | Named day is weekend/holiday and not after deadline; offer `offered_date` |
| `offer_deadline` | Named/resolved day is after deadline; offer that product’s deadline (rule 23 / B §6) |
| `ask_exact` | Vague period and `vague_ask_used` is false |
| `propose_deadline` | Vague period and ask already used; propose deadline |
| `unchanged` | No date mentioned this turn; keep prior value; **do not** re-apply weekend/holiday/deadline logic |
| `keep` | Confirm-repeat of the same ISO date already held |

`date` / `offered_date` are ISO dates or `null` as required by the action.

---

## Rules (plain language + citation)

### R-NOW — Call clock only

All date arithmetic uses the call variable `now`, never the real clock.

- **Source:** A §2 table (`now`)
- **Quote:** “The current date and time. All date rules use this, never the real clock.”

### R-BD — Business days and holidays

Business days are Monday–Friday except the listed Freya Bank holidays. Holidays are **policy inputs** in fixtures (default list from the brief).

- **Source:** A §7 intro
- **Quote:** “Business days are Monday to Friday, except Freya Bank holidays: 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01.”

### R-DEADLINE — Band → Nth business day after today

| `days_late` | Band | Deadline |
|---|---|---|
| 1–7 | early | 12th business day after today |
| 8–45 | late | 7th business day after today |

**Counting convention used by this oracle:** start at the calendar day of `now`, then move forward counting only business days; **today itself is not counted**. So the 1st business day after Wednesday 2026-10-14 is Thursday 2026-10-15.

- **Source:** A rule 18
- **Quote:** “the 12th business day after today” / “the 7th business day after today”
- **Corroboration:** PTS `PUB-04` late-band deadline `2026-10-23`; PTS `PUB-13` late product deadline `2026-10-23`. Early-band absolute deadline is not printed as a field in PTS; `PUB-07` / `PUB-13` only require that 27 Oct / 30 Oct sit *inside* the early deadline (consistent with 2026-11-02 under this counting).

### R-VALID — Promise date window

A promise date must be today or later, a business day, and not after the deadline.

- **Source:** A rule 19
- **Quote:** “A promise date must be today or later, a business day, and not after the deadline.”

### R-SNAP — Weekend / holiday before or on the deadline side

If the customer names a weekend day or holiday that is **not after** the deadline, offer the next business day. If the named day **is after** the deadline, use R-LATE instead.

- **Source:** A rule 20
- **Quote:** “If the customer names a weekend day or a holiday that is not after the deadline, offer the next business day. If the named day is after the deadline, rule 23 applies.”

### R-VAGUE — Vague period

Vague period → ask once for the exact day; if still none, propose the deadline.

- **Source:** A rule 21
- **Quote:** “If the customer gives a vague period ("next week", "end of the month", "when my salary comes"), ask once for the exact day. If they still give none, propose the deadline.”

### R-REL — “This” / “next” weekday

“Next \<weekday\>” = that weekday in the **following** calendar week. “This \<weekday\>” = that weekday in the **current** week. “Next Friday” said on a Friday is next week’s Friday.

- **Source:** A rule 22
- **Quote:** “So "next Friday" said on a Friday is the Friday of the following week.”

Week boundaries for this oracle: calendar week Monday–Sunday containing `now`’s date. “This Friday” on Wednesday is the Friday of that same week.

### R-LATE — After the deadline

Ask/offer the latest recordable date = the deadline. Refusal of that offer is outside the date engine (flat refusal, rule 30).

- **Source:** A rule 23
- **Quote:** “If the customer asks for a date after the deadline, say the latest date you can record is the deadline and offer it.”

### R-CONFIRM-CHANGE — Correction at confirm

If the customer changes the date at confirmation, re-check the new value with §7.

- **Source:** A rule 35
- **Quote:** “If the customer changes the date or the amount at this step, check the new value against sections 7 and 8 and read it back again.”

### R-STICKY — No mention this turn

Workflow variables are never cleared on a transition; extraction can leave an old date sitting in state. If `mentioned_this_turn` is false, the resolver must leave prior dates **unchanged** and must not re-run snap/deadline logic as if newly spoken.

- **Source:** WF “Variables” (“A variable is never cleared on a transition”); TC / WF extraction notes; scenario required by this oracle brief
- **Quote (WF):** “A variable is never cleared on a transition. A later write with the same name overwrites it.”

### R-REPEAT — Same date said again

Repeating the same ISO date already held (confirmation read-back) is not a correction; keep the date.

- **Source:** A rules 34–35 (change triggers re-check; unchanged confirm does not)
- **Quote (34):** “Read the product, the amount and the date back and ask "Do you confirm?".”

### R-MULTI — Per-product deadlines (Brief B)

Band and deadline are per product from that product’s `days_late`. One shared named date that exceeds one product’s deadline records that product on its own deadline; other products keep the named date.

- **Source:** B §§3, 6
- **Quote (B6):** “If the customer names one date for everything and it is after one product's deadline, record that product on its own deadline… The other products keep the date the customer named.”

### R-PERSUADE-DATE — Persuasion proposed dates (context only)

Attempt 1 proposes the last business day of this week; if today is that day, the last business day of next week. Attempt 2 (late band) proposes the deadline. These are agent proposals, not customer extractions; fixtures mark them with `kind: "absolute"` and `source: "persuasion"` in description only where covered.

- **Source:** A rule 30
- **Quote:** “Attempt 1: propose the last business day of this week. If today is that day, propose the last business day of next week.”

### R-CB — Callback window (related, not promise)

Callback is today or the next business day, 10:00–19:00 inclusive, later than `now`. Included only where a fixture tags `domain: "callback"`; promise fixtures ignore it.

- **Source:** A rule 6
- **Quote:** “A callback is for today or the next business day, from 10:00 to 19:00, both included, and later than `now`.”

---

## Ambiguities / unresolved points

Do **not** invent answers for these. Fixtures either avoid them or mark `expected.ambiguous: true` with `notes`.

1. **Exact prose of “Nth business day after today”**  
   Brief does not define whether today is skipped. This oracle uses “exclude today” because PTS late deadline 2026-10-23 matches that definition. Early absolute deadline 2026-11-02 is **inferred**, not printed as PTS expected deadline text.

2. **Next business day vs deadline (theoretical wording gap)**  
   Rule 20 does not explicitly say what to do if the offered next business day were after the deadline. Under the natural reading that “next business day” is the soonest business day on/after the named day, and that deadlines are themselves business days, any named weekend/holiday that is not after the deadline has a next business day ≤ deadline — so no concrete fixture asserts a conflict. If an implementation defines “next” differently, re-check against rule 20’s quote.

3. **`now` on a weekend or holiday**  
   Brief examples use mid-week `now`. Whether “today” can be a promise date when `now` itself is a non-business day is unspecified.

4. **Ownership of relative-phrase parsing**  
   WF says built-in `type: "date"` extraction can turn “next week” into a concrete date, while A rule 21 requires vague periods to be rejected once and then replaced by proposing the deadline. Fixtures therefore pass an explicit `kind` (`vague` vs `relative_weekday` vs `absolute`) so the date engine is judged on policy, not on NL parsing. Which layer must emit `vague` vs a concrete date is a builder concern, not settled here.

5. **“Last business day of this week”** when Friday is a holiday  
   Rule 30 does not spell out walking backward inside the week. Persuasion fixtures use a Friday that is a business day, or mark ambiguity.

6. **Timezone of `now`**  
   `now` is given without offset (e.g. `2026-10-14T11:00`). Oracle uses the date portion as the call’s local calendar date.

7. **Past dates before today**  
   Rule 19 forbids them; the brief does not say whether to offer today, offer the deadline, or only reject. Fixtures that need a past date expect `offer_deadline` only when the named date is also after the deadline; otherwise they mark `action` as rejecting toward the valid window without inventing a single mandated offer — see case notes.

---

## Metamorphic properties

These are checked by paired cases in `date_cases.json` (`metamorphic.base_id` + mutation):

| Property | Mutation | Required effect |
|---|---|---|
| M-HOLIDAY | Add/remove a holiday on the named day | Snap vs accept flips with the holiday set |
| M-DEADLINE | Shorten a product’s deadline offset (or raise `days_late` into late band) | A previously accepted date becomes `offer_deadline` (or the accepted date moves to the new deadline) |
| M-SWAP | Swap two products’ `days_late` (hence deadlines) under the same shared named date | Per-product outcomes swap with the deadlines |
| M-POLICY | Expected values must be computed from the case’s `policy` + brief rules, never from a hidden production holiday table |

Public calendar dates (2026-10-14, Freya holidays, PTS answers) may appear as **example** `now` / holidays inside `policy`, but every expected field must remain correct if those lists are replaced in a metamorphic twin.
