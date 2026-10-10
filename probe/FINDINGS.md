# Code → dialogue probe (2026-10-10, chat API, workflow "probe")

**Question:** can a code node make a decision and the agent speak it **in the same turn**, with state kept across turns?

**Answer: yes, with one caveat.** Script: `probe/code_dialogue_probe.py`. Each run creates or updates one workflow and
sends 5 chat turns. No simulation.

## What worked
- The extraction (`type: date`) wrote `2026-10-26`, the variable transition fired, the code node (passthrough) ran, and
  the next node's `on_enter: tts "{{say_next}}"` said the code's sentence, **all in the same user turn**.
  Engine overhead is about 1 s per turn.
- Code-owned variables (`attempts`, `handled_date`, `resolved_date`, `say_next`) persist and update across turns:
  `attempts` went 1 → 2 → 3.
- Routing out of a code node on a code-written **string** flag (`date_state == "same"`) works.

## Caveat
**Code cannot clear or overwrite an extraction-sourced variable.** Writing `''` or `'none'` to `requested_date` from
code was ignored; the value stayed `2026-10-26` with source `extraction`. So "a date is set" stays true on every later
turn, and without a guard the code node re-runs and repeats its sentence.

**Pattern that works:** keep a code-owned `handled_date`.
- If `requested_date == handled_date`, the code sets `date_state = "same"` and routes to an LLM node (`listen`), which
  answers normally.
- Otherwise `date_state = "new"`, and the code routes to the tts node with the new `say_next`.

## Other observations
- On the first chat turn, the initial node's `on_enter` tts was **not** spoken; the LLM greeted instead. This is a chat
  route quirk. It is noted in docs/api.md; check this in simulations.
- In the `listen` node the LLM said "Your payment date is set for October 28" although no tool was called. That is the
  honesty risk. The confirm → write path must be its own gated node with no free LLM claim, and prompts must forbid
  "set/recorded" wording.
