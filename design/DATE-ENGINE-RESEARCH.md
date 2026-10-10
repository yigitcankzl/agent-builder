# Date engine: research before the first milestone (2026-10-10)

## Why
- PUB-07 failed in 4 of 6 baseline runs. The calendar facts were right, but the dialogue model picked the wrong line.
  Every failure was in the model's decision, never in the ledger or the routing
  (`ext/kickoff/BASELINE-ANALYSIS.md`).
- The final scores pass^3, the τ-bench metric: an agent that succeeds only intermittently scores low, and agents fail
  "complex reasoning … and following ad-hoc policies"
  ([τ-bench, arXiv 2406.12045](https://arxiv.org/pdf/2406.12045)).
- LLM date arithmetic is weak:
  - its typical error is off by exactly one day ([Test of Time, arXiv 2406.09170](https://arxiv.org/pdf/2406.09170));
  - accuracy mixes understanding, parsing, arithmetic and format
    ([PRIMETIME, arXiv 2504.16155](https://arxiv.org/pdf/2504.16155)).
- The practitioner pattern is: the model only labels the expression (absolute or relative, with an explicit reference
  date), and code does the calendar math
  ([BoundaryML, dates and times](https://boundaryml.com/podcast/2025-11-11-dates-and-times)).

## What we measured on Freya (`probe/date_extraction_probe.py`)
Setup: chat API, model `experimental-5`, `now = 2026-10-14` (a Wednesday) while the real clock was 2026-10-10,
13 utterances.

| Extraction field | Correct | Notes |
|---|---|---|
| `type: date` (built-in) | 8/13 | Anchored to the **real clock**: "Today" → 10-10, "Tomorrow" → 10-11. "Next Friday" → 10-16, not the brief's 10-23. It turns vague phrases into dates ("end of the month" → 10-31). Unusable for us |
| `type: string`, `{{now}}` in `description` | 0/13 | `{{now}}` is **not** substituted in descriptions, so the year is random (2024, 2025) |
| `type: string` with a custom `extraction_prompt` containing `Today is {{now}}` and the weekday rules | **13/13** | `{{now}}` **is** substituted in `extraction_prompt`. Handled corrections, words, "next/this", today and tomorrow, vague → empty |
| Component fields (day, month, weekday, week_ref, relative_day, vague) | **13/13** | Pure labelling, no arithmetic |

## Constraints found on the engine (`probe/code_dialogue_probe.py`, `probe/FINDINGS.md`)
- **Same-turn decisions work.** A code node decides and a tts `on_enter` speaks `{{say_next}}` in the same turn.
- **Code-owned variables persist across turns.**
- **Extraction variables cannot be cleared or overwritten from code.** They keep their last value. So separate
  component fields go stale: "the 26th", then "next Friday", leaves `day_of_month = 26` alongside `weekday = fri`.
  - Use **one** field per facet that is rewritten whenever a new date is named.
  - Dedupe in code with a code-owned `handled` signature.

## Design decision for the first milestone
1. The **extraction** produces two single-value fields, both via custom `extraction_prompt`s anchored to `{{now}}`:
   - `date_iso`: the exact date, or empty;
   - `date_spec`: a compact normalized label `rel=<today|tomorrow|none>;d=<1-31|>;m=<1-12|>;wd=<mon..sun|>;wk=<this|next|after_next|none>;vague=<yes|no>;corr=<yes|no>`.

   Natural language is never parsed in Python.
2. A **runtime resolver** (pure Python, stdlib only, policy as input):
   - recomputes the date from `date_spec` and `now`, and cross-checks it against `date_iso`; a disagreement means ask
     once;
   - applies the policy: earliest date, business days, holidays, per-band deadline, the action on a non-business day,
     the action after the deadline, the action on a vague answer;
   - returns `status`, `record_date` and `say_next`.

   `now`, holidays and deadlines are inputs. **No public A/B dates in production code**; they are only in test fixtures.
3. An **emitter** produces the code-node source: the resolver source plus the policy as a literal, linted for `{{`/`}}`.
4. **Graph wiring:**
   - the host conversation node gets the two extraction fields and a transition to `date_resolve` (code);
   - `date_resolve` routes to `<host>_date_say` (tts `{{say_next}}`) on a new date, and to `<host>_cont` (LLM) on the
     same date.
5. **Tests:**
   - local property tests of the resolver against an independent brute-force oracle, over many `now` values and random
     policies;
   - then PUB-07 with `--reps 3` plus the `pieces` and `corrects` styles.
