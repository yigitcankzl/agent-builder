# Reducer contract v2 (2026-10-10)

Changes from v1 (`948cfc7`):
1. `close` is one semantic action whose farewell is inside it (example E fixed).
2. The farewell is spoken by tts BEFORE `close_call`, with no user turn in between (`close_say` node).
3. That passthrough tts transition is added to the unverified list.
4. Dates come from the labels only. `iso` is removed from the event; Python computes the day; acceptance is
   `kind=accept` against `st.offer`.
5. Multi-meaning utterances: one primary `kind` chosen by a fixed precedence, plus an optional secondary act `also`
   (§1.5, example F).

Status: contract only. There is no implementation yet, and nothing in this document has been run on Freya or in a
simulation.

Base:
- the policy schema, quote checks, codegen and runner on `date-slice` (`builder/engine/{date_policy,dates,codegen}.py`);
- the M0 platform findings (`probe/M0-FINDINGS.md`).

**There is no second schema.** Every new policy section below is added to `date_policy.py`. It uses the same
validator, the same `source` quote rule, and the same codegen (engine source + policy literal + call, no `{{`/`}}`).

Division of labour at runtime:
- **Freya's extraction model** turns the customer's words into ONE atomic event string.
- **The reducer** (code node) decides.
- **The output** is exactly one external action: exact tts, stage-specific free LLM talk, a tool call, or close.

---

## 1. Atomic event schema

### 1.1 The user event: one extraction field, rewritten in full on every routed turn
- Variable: `ev`, type `string`, `min_confidence` 0.3, `max_retries` 2.
- `validation_pattern`: generated from the grammar below. Policy enums are inserted, so the pattern is per brief.

```
ev := n=<event_token>;src=user;kind=<kind>;also=<kind|none>;st=<status>;prod=<product_ref>[;<k>=<v>]*
```
`also` is the secondary act of a multi-meaning utterance (§1.5); `none` otherwise.
| Field | Values | Meaning |
|---|---|---|
| `n` | `[a-z]{6}` (copied) | The **event token**: a random 6-letter code that the reducer wrote into `ev_tok` on its previous run and the extraction prompt shows as `Code: {{ev_tok}}`. M0: a small integer is NOT copied (the model invents turn numbers); a letter code is copied reliably. |
| `src` | `user` | Fixed for extracted events. Tool events are not extracted (1.3). |
| `kind` | see 1.2 | The single most important thing the customer did in the LAST message |
| `st` | `complete`, `partial`, `ambiguous`, `none` | `partial` = cut off ("the twenty-"); `ambiguous` = several readings or facets that contradict each other; `none` = nothing relevant (small talk) |
| `prod` | a product ref (1-based position in the `get_account` order), `all`, or empty | Which product the event refers to; empty = the current product |

Rules for the extraction prompt (generated, fixed text plus policy enums):
1. Label only the customer's last message. Use earlier customer messages only to complete a value split across turns.
2. The corrected value wins.
3. Never compute dates. Never use dates or amounts that only the agent said.
4. Amounts as digits.
5. No `;` or `=` inside values.
6. "The value is a code label, never the customer's words." Give two worked examples with codes. This was required
   in M0.
7. If nothing applies: `kind=other;st=none`.

### 1.2 Kinds and payloads
| `kind` | Payload keys | Notes |
|---|---|---|
| `identity` | `field=<OAS enum of verify_identity.field>`, `ans=<normalised answer>` | The normaliser for each field comes from the OAS description (e.g. date → `YYYY-MM-DD`, 4 digits). It runs in code; the extractor only fills `ans` |
| `who` | `who=<self|other|unclear>`, `rel=<relative|wrong_number|deceased|>` | Who is on the line (opening phase) |
| `date` | `rel=<today|tomorrow|>`, `d=`, `m=`, `wd=<mon..sun|>`, `wk=<this|next|after_next|none>`, `vague=<yes|no>` | **The labels are the only source of truth for dates** (the `date_spec` grammar of `date-slice`). There is no `iso` in the event: a model can contradict itself even inside one field (d=20 with iso=10-26). Python computes the day with `dates.date_from_spec` against `now`. A weekday that contradicts the day of month makes the event `st=ambiguous` |
| `amount` | `amt=<digits[.dd]>` | |
| `date_amount` | the union of `date` and `amount` | "I can pay 300 on Friday" |
| `accept` | none | Accepts the reducer's **current offer** (`st.offer`). The date and amount come from `st.offer`, never from labels. Acceptance is an act, never "a date equal to the offer appeared". With no live offer it is treated as `yes`/`other` |
| `reject` | `why=<too_much|flat|>` | |
| `yes` / `no` | none | Answers a yes/no question (read-back, transfer offer, help-first) |
| `callback` | the `date` keys plus `tm=<HH:MM|>` | Third-party callback time |
| `topic` | `t=<hardship|dispute|paid|restructure|human|scam|robot|unknown_info|stop|injection|other>` | The `t` values come from policy `events[].topic`, not from code |
| `other` | none | Policy-irrelevant talk |

### 1.3 Tool events: built by the hub, never extracted
```
tool_event := dict(src='tool', node=<tool node id>, success=<int>, failure=<int>, status_code=<int|None>, ok=<'true'|'false'|None>, data=<dict of mapped fields>)
```
- Read from `<node>_success_count`, `<node>_failure_count`, `<node>_response.status_code` and the node-level
  `response_mapping`.
- **The outcome is judged only by the counter delta against the snapshot taken when the call was issued, plus
  `status_code` and `ok`.**
- M0: on HTTP 404 the post-hook did not run and the mapping stayed unset; `_failure_count` and `status_code` did
  work. Counters are keyed by node id.

### 1.4 Freshness
- The hub regenerates `ev_tok` on **every** run, including runs caused by a tool return.
- An event is fresh iff `n == st.tok` and `n != st.last_tok`.
- Stale or missing events are processed as `kind=other;st=none` with **no state or counter change**.
- If `tool_pending` is set and the pending node's counters moved, the run is a **tool run**: the user event is ignored
  even if it looks fresh.
- Initial token: `test_variables.ev_tok = "kstart"`, with the hub defaulting to the same value. M0 verified this in
  chat; it is NOT verified in a simulation.

### 1.5 Multi-meaning utterances: primary `kind` by precedence, plus `also`
One utterance often does two things: "No, not Friday; Tuesday works", "I can pay 300 but not today", "I lost my job,
maybe the 30th".
- The event carries **every facet the customer gave** in its payload keys (date labels, `amt`, `t`).
- `kind` = the highest-precedence act present. `also` = the next one, or `none`.
- Precedence, highest first. Fixed in code; the policy can only reorder the topic block:
  1. `topic` (hardship, dispute, paid, restructure, human, stop, scam, robot, injection, unknown_info), in
     `policy.events[].precedence` order;
  2. `date_amount`;
  3. `date`;
  4. `amount`;
  5. `accept`;
  6. `yes`;
  7. `reject`;
  8. `no`;
  9. `callback`;
  10. `who` / `identity` (phase-specific: in the opening and identity phases they rank first);
  11. `other`.

Rationale and the reducer rules:
- **A date or amount the customer proposes outranks a refusal.** Brief A rule 29: "A date or an amount the customer
  proposes is never a refusal." So `also=reject` next to a proposal never consumes a persuasion attempt. The proposal
  supersedes the live offer, and is then checked by the date and amount rules.
- **A topic outranks the rest because topic rules come first in the brief** (rule 32 "comes before rules 30 and 41").
  The date and amount keys stay in the payload: rule 32's "If the customer still names a date or an amount themselves,
  record the promise" is handled by the topic step reading those keys.
- **`amount` with `also=reject` aimed at the date** ("300 but not today"): record the amount as the customer's amount,
  then ask for the date (the next step). This is not a refusal.
- **`also` is advisory.** The reducer uses it only where a rule names it, e.g. a "not today" reject on the first-ask
  turn marks `all_today_asked`. It never runs two actions.

---

## 2. State

The state lives in one code-owned variable `st` (JSON). It is written with `'}}'` → `'} }'` so the value never
contains double braces. It is never referenced in a prompt. Prompts get flat, purpose-built variables only (§6).

```
st = dict(
  v=1, phase=<opening|third_party|identity|account|negotiation|readback|wrapup|closed>,
  tok=<expected token>, last_tok=<last processed token>, runs=<int>,
  verified=<'no'|'yes'>, who=<'unknown'|'self'|'other'>,
  identity=dict(order=[fields], idx=int, wrong=int, refusals=int, retry_hint=int),
  products=[dict(id, type, past_due, floor, days_late, band, deadline, attempts_cap,
                 attempts=int, floor_offered=bool, status=<open|proposed|agreed|confirmed|persisted|refused|noted|failed|paid|disputed>,
                 offer=dict(amount, date) or None, write_failures=int, note=None)],
  cur=<index of the product under discussion>, all_today_asked=bool,
  offer=dict(product_ids, amount, date, kind=<full|floor|deadline|attempt_n|customer>) or None,   # the live offer that accept refers to
  readback=dict(items=[(pid, amount, date)], asked=int) or None,
  counters=dict(confirm_name=int, clarify=int, vague=int, stop_talking=int, human_asks=int, decline_explain=int, ...),  # caps in policy
  said=dict(amounts=[...], sentences={id: times}),          # for the "never repeat an offer" and max_times lints
  pending=dict(op, node, product_id, snap_success, snap_failure, attempt) or None,
  tool_counts=dict(node -> (success, failure)),            # last seen, for deltas
  transfers=[queue], callbacks=[(date, time)], notes=[(pid, reason)],
  outcome=None, reason=None, close_requested=False, closed=False)
```

**Lifecycle of a commitment, per product:**
`open → proposed` (the reducer offered) `→ agreed` (an `accept` event) `→ confirmed` (`yes` to the one read-back of
all agreed items) `→ persisted` (only after a tool success delta and `ok == 'true'`).
- A `failed` product holds `write_failures >= policy.writes.promise.retries + 1`.
- Read-back changes (`date`/`amount` events during readback) re-run the checks and set `agreed` again.

---

## 3. Reducer interface

```
step(policy, st, event, tool_event, now) -> (st2, action)          # pure, total, deterministic, stdlib only (json, re, datetime)
hub(vars):                                                          # the code-node wrapper (codegen appends policy + call)
    st = load(vars['st']) or init(policy, vars)                     # lazy init: the chat route can skip a first code node
    event = parse_fresh(vars['ev'], st) ; tool_event = read_tool(vars, st.pending)
    st2, action = step(...)        # exceptions -> st unchanged, action = say_exact(policy.sentences.safe_repeat)
    write_action_vars(vars, action) ; vars['st'] = dump(st2) ; vars['ev_tok'] = new_token()
```

- **Date decisions** call the existing date core: `dates.date_from_spec` for the labels → day (labels only, no iso
  cross-check in v2), and `dates.decide` for the policy decision, which needs the date policy sections unchanged.
  `decide`'s reasons map onto offers and sentences. `interpret`'s iso cross-check and its accepted-offer rule stay only
  for the two-field date slice; the reducer uses `kind=accept` + `st.offer` instead.
- `run`/`run_safe` in `dates.py` (the standalone code node) stay for the date-only slice. The reducer imports the pure
  functions.

**Variables written for routing and speech** (all strings):
- `route`, plus `route_ok` = `verified` (the structural gate, §6);
- `say_next`;
- `talk_hint` (a one-line fact for the free-talk node);
- `w_<tool>_<arg>` (baked tool arguments);
- `close_outcome`, `close_reason`, `farewell`;
- display facts after verification only: `acct_*`.

---

## 4. Action types (exactly one per call)

| Action | Fields | Route | Node |
|---|---|---|---|
| `say_exact` | `text` (non-empty after strip) | `say` | `exact_say`: tts `{{say_next}}` |
| `speak_free` | `node` ∈ policy.free_talk_nodes for the phase, `hint` | `talk_pre` / `talk_post` | stage-specific LLM node |
| `call_tool` | `tool` (one of the 7 OAS names), `args` (dict, all keys from the OAS) | `t_<tool>` | api_request node with baked args |
| `close` | `outcome`, `reason` (omitted where the policy table has none), `farewell` text (non-empty: thanks + goodbye, plus any required closing line) | `close` | `close_say` (tts `{{farewell}}`, passthrough, no user turn) → `t_close_call` → `end` (silent) |

`close` is ONE semantic action: the farewell is spoken first, then `close_call` runs, then the call ends. Brief A rule
47: thank and say goodbye **before** `close_call`; `close_call` is the last tool call.

Selection order inside `step` (first that applies):
1. tool run;
2. close conditions;
3. policy event precedence (e.g. hardship before persuasion);
4. phase logic;
5. free talk.

`speak_free` is chosen only when the event is `kind=other` or `st=none`, or is a policy-irrelevant question, AND no
counted step is due.

---

## 5. Mandatory invariants (each is a test in the local runner)

1. **Exactly one action** per call. `route` is always one of {say, talk_pre, talk_post, t_*, close}.
2. **No empty tts.** `say_exact.text.strip()` is non-empty. If a decision yields no sentence, the reducer emits
   `say_exact(policy.sentences.safe_repeat)`, never an empty `say_next` (the M0 item-9 risk).
3. **Partial event.**
   - `st=partial` → no state or counter change, no re-ask.
   - Action: `say_exact(policy.sentences.continue_line)`, e.g. "Go on, please." (a fixed short line).
   - The `pieces` style failure on `date-slice` (the engine asked again on a half-said date) is exactly this.
4. **Ambiguous event.** One clarification per facet, counted in `counters.clarify` (cap from policy, default 1).
   After the cap, take the more specific facet (day of month over weekday) and read it back. A stale cross-field
   mismatch never triggers a clarification.
5. **Free LLM speech only for policy-irrelevant talk.**
   - Free-talk nodes have no tools and get only `talk_hint` and phase-safe facts.
   - The pre-verification node gets no account facts at all.
6. **Honesty.** No persisted or success wording (policy list `honesty_words`, e.g. "recorded", "scheduled",
   "transferred") in any `say_exact` text or `talk_hint` before the matching tool success delta. The opening's
   "this call is recorded" is rewritten by a lint to a non-colliding form, e.g. "we record this call", where the brief
   allows it; otherwise it is kept and logged as a risk.
7. **Tool failure** = the `_failure_count` delta > 0, or `status_code` ≥ 400, or `ok != 'true'`. Hooks and mappings
   are never required.
8. **A token is processed at most once** (`last_tok`). Tool runs never consume a user event.
9. **The reducer runs exactly once per user turn and once per tool return.** Graph rule: every speaking node's only
   transition is `always → hub`; tool nodes `always → hub`; tts and LLM nodes do not route anywhere else.
10. **Writes.**
    - `create_promise` only for `confirmed` items.
    - At most one success per product.
    - Retries ≤ the policy cap.
    - Args come only from `st` (never from the model).
11. **Notes.** Only in `wrapup`, and none if a transfer succeeded (`policy.writes.notes.none_if_transfer`).
12. **Close.** Exactly one `close` action per call. It is the last tool call. The outcome and reason come from
    `closing.precedence(st)`.
13. **Gating.** No account fact appears in any output before `verified == 'yes'`; `get_account` and write tools are
    unreachable before it.
14. **Caps.** Every counter ≤ its cap. The floor is offered at most once per product. No amount is restated in a later
    offer line once offered.

---

## 6. Smallest workflow graph

```
test_variables: {ev_tok: "kstart"}            # see the unverified list
greet        conversation, initial, on_enter tts <opening sentence>, extraction [ev], transitions [always -> hub]
hub          code, passthrough, the reducer; transitions IN THIS ORDER (one per target, the engine merges duplicates):
               close_say      if route == close
               t_get_account  if route == t_get_account AND route_ok == yes        # structural gate
               t_create_promise / t_add_note / t_transfer_to_agent   if route == t_x AND route_ok == yes
               t_verify_identity / t_schedule_callback               if route == t_x
               talk_post      if route == talk_post AND route_ok == yes
               talk_pre       if route == talk_pre
               exact_say      always (last)       # the reducer guarantees say_next is non-empty whenever route == say;
                                                  # any other unmatched route (a gate refused it) lands here with the safe line
exact_say    conversation, on_enter tts {{say_next}}, no tools, extraction [ev], always -> hub
talk_pre     conversation, on_enter llm, no tools, prompt: identity of the agent and pre-verification soft rules only,
             {{talk_hint}}, extraction [ev], always -> hub
talk_post    conversation, on_enter llm, no tools, prompt: post-verification soft rules + acct_* facts + {{talk_hint}},
             extraction [ev], always -> hub
t_<tool>     api_request, passthrough, args baked from w_<tool>_* (each body leaf default "{{w_..}}"),
             node-level response_mapping data.*, maxRetries 0, always -> hub
close_say    conversation, on_enter tts {{farewell}}, passthrough, passthrough_default_transition t_close_call,
             transitions [always -> t_close_call], no extraction    # speaks, then moves on without a user turn (UNVERIFIED, §10.13)
t_close_call api_request close_call with baked close_outcome / close_reason, always -> end
end          end_call, on_enter silent, message_mode none, disable_inactivity_monitor   # the farewell was already spoken
             fallback if passthrough tts is not supported: no close_say; end's spoken_message {{farewell}} speaks
             AFTER close_call (order violates rule 47 in the transcript, but the ledger is right). Choose by probe 13
tools[]      close_call alwaysRunsAt end_of_call with {{close_outcome}} / {{close_reason}}: the safety net if the customer
             hangs up first. M0 7c: after an explicit close the mock rejects it ("already closed") and the ledger keeps
             the first outcome
```

Notes:
- The hub's last edge is `exact_say`, not the LLM: a refused gate or an unknown route says the safe line.
- **The phase gate is structural.**
  - `route_ok` is a separate code variable, set only by the identity step on a verified tool result.
  - The transitions themselves refuse tool and `talk_post` routes without it.
  - The pre-verification nodes never receive debt facts.
- **Stage-specific LLM nodes:** only `talk_pre` and `talk_post` by default. A brief can add one more only through
  policy (`free_talk_nodes`), e.g. a third-party node that must not say why the bank calls. That one can reuse
  `talk_pre`'s prompt with the extra soft rules.

---

## 7. Policy sections to add (same file, same validator, same `source` rule)

| Section | Content |
|---|---|
| `meta` | `bank_name`, `agent_self_description`, `language`, `call_vars` (role → name), `address_template` |
| `sentences` | `{id: {text, verbatim, max_times}}`, including `opening`, `continue_line`, `safe_repeat`, `farewell_*`, `text_message`, `sympathy`, `scam_answer`, `robot_answer`, the fail lines |
| `identity` | `questions[{field (OAS enum), ask, normaliser}]`, `max_wrong`, `on_fail`, `on_decline`, `decline_explain_max`, `hint_rules` |
| `products` | field names (`id`, `type`, `past_due`, `days_late`), `floor_field_by_type`, `naming_by_type`, order |
| `attempts` | per band: `{n, date_rule, amount_rule}`. This extends `deadline.bands` with `attempts`, so bands are not duplicated |
| `amounts` | `first_ask`, `too_much → floor once`, `accept_range`, `below_floor` |
| `multi_product` | `state_all_first`, `ask_all_today_once`, `one_date_clamp`, `one_readback` |
| `events` | `[{topic, precedence, say, effect, note_reason, outcome}]` |
| `writes` | `promise{retries, fail_say}`, `notes{when, none_if_transfer}`, `callback{window}`, `transfer{queue_map}` |
| `closing` | `table[{outcome, reason, when}]`, `precedence`, `reason_omitted_for` |
| `honesty_words` | Words that are banned before the matching success |
| `free_talk_nodes` | Default `[talk_pre, talk_post]` |
| `unmapped` | See §8 |

---

## 8. `unmapped_rules`: degrade, never fail the build

The policy extractor records every brief rule it could not map onto a section:
`unmapped: [{rule_id, quote, phase_guess, kind_guess}]`.

The build **never fails** because of `unmapped`. Fallback per rule:
1. The quote is appended verbatim, as a soft rule, to the prompt of the free-talk node of `phase_guess` (both nodes if
   unknown). It is never appended to `exact_say` (tts has no prompt) and never to tool args.
2. If `kind_guess` is a sentence ("say X when Y"), the sentence is also added to `sentences` with `trigger: unmapped`
   so the trace shows it. The reducer never speaks it automatically.
3. The builder trace lists every unmapped rule. The self-test generator writes one persona per unmapped rule, so a
   failure is visible before submission.

**Core sections** are `identity`, `products`, `deadline`/`bands`, `closing.table`, and the tool OAS mapping.
- A core section is filled from defaults only if the brief truly says nothing; such a default is marked
  `source: default` and is never invented business policy.
- If a core section cannot be filled at all (e.g. no outcome table can be read), the builder switches that brief to
  the **whole-builder fallback**: a baseline-style generator plus the date engine. The build still produces an agent.

---

## 9. Worked examples

Policy: the Brief A fixture. `now` = 2026-10-14. One product `p1`, a personal loan, 540.00, `days_late` 5 → early
band, deadline 2026-11-02, 1 attempt.

**A. Partial date (the `pieces` style)**
```
state  : phase=negotiation, tok=kqmrta, last_tok=kpbvnc, p1.status=open, p1.attempts=1, offer=None
event  : n=kqmrta;src=user;kind=date;also=none;st=partial;prod=;rel=;d=;m=;wd=;wk=none;vague=no      ("on the twenty-")
action : say_exact("Go on, please.")                      # sentences.continue_line
next   : last_tok=kqmrta, tok=<new>, everything else unchanged (no clarify++, no vague++, no attempt)
```
The next turn: "seventh" → `kind=date;st=complete;d=27` → decided as in B.

**B. Holiday date → offer the next business day**
```
state  : phase=negotiation, tok=kzwfha, p1.status=open, offer=None
event  : n=kzwfha;src=user;kind=date;also=none;st=complete;prod=;rel=;d=26;m=;wd=mon;wk=none;vague=no
step   : dates.date_from_spec(labels) -> 2026-10-26 (computed in Python); dates.decide -> non_business_day, accepted 2026-10-27
action : say_exact("Monday 26 October is not a business day. The next business day is Tuesday 27 October. Could you pay on Tuesday 27 October?")
next   : p1.status=proposed, offer=dict(product_ids=[p1], amount=540.0, date=2026-10-27, kind=customer)
```

**C. Accept → one read-back → confirm → write → success**
```
1 event: kind=accept                         -> p1.status=agreed;  action say_exact("Personal loan, 540 on Tuesday 27 October. Do you confirm?"); readback.asked=1
2 event: kind=yes                            -> p1.status=confirmed; pending=dict(op=promise, node=t_create_promise, product_id=p1, snap_success=0, snap_failure=0)
                                                action call_tool(create_promise, dict(customer_id=..., product_id=p1, amount=540.0, date=2026-10-27))
3 tool : t_create_promise success 0->1, ok=true -> p1.status=persisted; pending=None
                                                action say_exact("Your promise is recorded. You will receive a text message confirming this promise.")
4 event: kind=other (thanks)                 -> close_requested; action close(outcome=promise, reason=None, farewell="Thank you, goodbye.")
```
"Recorded" appears only at step 3, after the success delta (invariant 6).

**D. Write failure, retry, then failure (PUB-10 style, `retries: 1`)**
```
tool : t_create_promise failure 0->1 (status 500)  -> p1.write_failures=1; action call_tool(create_promise, same args)   # no speech in between: one action
tool : failure 1->2                               -> p1.status=failed;  action close(no_promise, service_error,
                                                     farewell=writes.promise.fail_say + " " + sentences.farewell)   # "I could not record the promise. Thank you, goodbye."
```
One action: the fail line is part of the close farewell, spoken before `close_call` (rule 37 says to tell the
customer, then close).
If the retry succeeds instead: one persisted promise, and exactly one success in the ledger (PUB-10's "exactly one
promise").

**E. The same "No." twice (counting needs freshness)**
```
event 1: n=kaaaaa;kind=reject;also=none;why=flat -> p1.attempts 0->1, action say_exact(<attempt 1 offer>)
event 2: n=kbbbbb;kind=reject;also=none;why=flat -> attempts used up (cap 1)
                                                -> action close(no_promise, refused, farewell=sentences.farewell)    # ONE action
stale  : n=kaaaaa again                         -> ignored (last_tok), no counter change
```

**F. Multi-meaning: "No, not Friday, but Tuesday works" (precedence)**
```
state  : phase=negotiation, offer=dict(product_ids=[p1], amount=540.0, date=2026-10-16, kind=attempt_1), p1.attempts=1
event  : n=kmrsta;src=user;kind=date;also=reject;st=complete;prod=;rel=;d=;m=;wd=tue;wk=none;vague=no
step   : date (rank 3) beats reject (rank 7); the reject only drops the old offer, and NO attempt is consumed (rule 29);
         date_from_spec -> Tue 2026-10-20 -> decide -> ok
action : say_exact("Personal loan, 540 on Tuesday 20 October. Do you confirm?")      # read-back of the customer's own date
next   : offer=dict(..., date=2026-10-20, kind=customer), p1.status=agreed, p1.attempts still 1
```
"I can pay 300 but not today":
`kind=amount;also=reject;amt=300`. The amount is checked against the floor; if it is accepted, the next step asks for
the date. No attempt is consumed and `all_today_asked=true`.

---

## 10. Platform points still unverified (verify before or during M1 build)

1. **M0 item 8:** one composite `ev` field on a partial utterance ("the twenty-" then "seventh"): does the extractor
   write `st=partial` and then the full day? Blocked by the chat outage; `probe/m0_partial.py` is ready.
2. **M0 item 9:**
   - Is `on_enter: tts` with an empty string silent? The contract forbids empty strings anyway.
   - How often does `on_enter: llm` produce an empty turn after a transition?
   - Blocked by the outage.
3. **Simulation behaviour:**
   - Do `test_variables` (`ev_tok: kstart`) apply in a simulation? (Docs: merged on web calls.)
   - Is the first customer turn routed when the agent speaks first? (Chat suppresses routing on turn 1.)
4. **`}}` in a value substituted into a prompt.** It is harmless in tts (M0 7b). The prompt case was not measured;
   the contract avoids it (`st` is never in a prompt, and facts are flat).
5. **Re-baking on re-entry.** Does an api_request node use the CURRENT `w_*` values each time it is entered (e.g. a
   retry with the same args, and a second product)? M0 used only stable args.
6. **`create_promise` 500 fault** (the PUB-10 `fail_first_n`): the failure counter path was verified only with an
   HTTP 404 on an unknown route. Expected to behave the same; not seen.
7. **`end_call` with `spoken_message: {{farewell}}`.** Variable substitution in the terminal is documented, but has not
   been seen with our variables.
8. **Lifecycle `close_call` safety net after an explicit close.** Does the rejected duplicate appear in the transcript
   the judge reads?
9. **Extraction accuracy of the full event vocabulary** (kinds, topics, identity normalisation, injection attempts)
   at scale. Only `act` with 6 values was measured (M0), plus the date labels (13/13, 10/10).
10. **Latency.** hub + tts per turn in a simulation under load. During the outage window chat turns took minutes and
    one PUB-07 call stalled with no events (`1327758a`).
11. **Sandbox Python version and module list.** Only `json`, `re` and `datetime` are verified. The reducer must stay
    3.8-safe and stdlib-only.
12. **Node count limit.** There is no documented cap; the graph above has about 13 nodes.
13. **Passthrough tts → `close_call` without a user turn.** Does a conversation node with `on_enter: tts {{farewell}}`
    and `passthrough: true` speak the line and then route immediately (always → `t_close_call` → `end`)? Also: is the
    tts text in the transcript BEFORE the `close_call` tool event? Probe: `close_say` in `tests/extract_eval.py`'s
    sibling probe (`probe/m0_close_say.py`). Fallback in §6.
