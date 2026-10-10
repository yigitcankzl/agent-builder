# M0 platform probes (2026-10-10, chat API only, no simulation)

- Branch `m0-probes` (off `date-slice`).
- Scripts: `probe/m0_probe.py` (items 1–6, 7b), `probe/m0_extra.py` (7a, 7c), `probe/m0_partial.py` (8, 9).
- Evidence: full `get_call` dumps in `probe/m0_evidence/`.
- Slots `m0-hub`, `m0-big`, `m0-partial`, with state file `probe/.m0-agents.json`. No dateslice, baseline or brief slot
  was touched.

## Verdict
| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | turn freshness via a code-issued token echoed by the extractor | **PASS, with the right token** | `bd36d839-83cc-409b-96cd-156c92405c52` |
| 2 | the same utterance on two turns counts twice | **PASS** ("No." ×3 → refusals 1, 2, 3) | `bd36d839…` |
| 3 | a stale value is skipped | **PASS** (stale on tool re-entry, hub runs 5 and 7; small talk → explicit `act=other`, no counter change) | `bd36d839…` |
| 4 | reducer → exact_say (tts) → reply → reducer loop, 4+ turns, state kept | **PASS** (8 routed turns) | `bd36d839…` |
| 5 | tool success and failure reach the reducer | **PASS** (see the table below; the post-hook does NOT run on an HTTP error) | `bd36d839…` |
| 6 | the reducer runs at most once per user turn | **PASS** (once per user turn, plus once per tool return, which the token marks stale; no re-run after tts) | `bd36d839…` |
| 7a | ~60 KB code node | **PASS** (67,142 chars saved byte-identical; runs in about 50 ms) | `a018453e-9c63-4acd-9fa5-866849d757d3` |
| 7b | `}}` / `{{` inside a variable value | **PASS for tts** (spoken verbatim: "a }} b {{ c"). In a prompt: not measured (platform outage) | `bd36d839…` |
| 7c | a second `close_call` | mock answers `{"ok": false, "error": "the call is already closed"}`; the ledger keeps the FIRST outcome, but both calls are logged | `probe/m0_evidence/m0_close_twice.json` |
| 8 | partial utterance with one composite field | **NOT MEASURED** (chat API returned 503 on every turn from 13:50) | script ready: `probe/m0_partial.py` |
| 9 | silence after a transition | **root cause of 1327758a = platform stall, not the graph**; the live test of an empty tts was not measured (outage) | `1327758a-145e-423c-9b29-825ccc952d96` |

## Details and workarounds

### 1. Freshness token: what failed first, and what works
1. **A plain field description: FAIL.** The extractor copied the customer's words into the field ("No.") and the
   regex rejected it (`a4edb675-78f4-4270-babf-9829f953d1d9`, every turn `extraction_failed regex_failed`).
   - **Fix:** describe the field as a code label, give 2 worked examples, say "never the customer's words", and set
     `max_retries: 2`.
2. **A small integer nonce ("Turn id: 0"): FAIL.** The extractor invented its own turn numbers (n=3, 5, 7, 9, 10, 10)
   instead of copying the id (`8f0e12af-5343-40c6-b477-9fb158951cdb`).
3. **A random 6-letter token ("Code: kbbxnd … copy the code letter by letter"): PASS.** The token was copied
   correctly on every routed turn.
   - The token is regenerated on **every** hub run, including tool returns, so a second run in the same user turn sees
     the old token and the turn is stale.
   - Token alphabet: lowercase letters without i/l/o. Pattern: `n=[a-z0-9]{1,8}`.
4. **Initial token.** Before the first hub run the placeholder is unresolved; the extractor then wrote `n=ev_tok`
   (`132f2c10-90f1-4cea-9871-baeffa993c0e`).
   - **Fix:** `test_variables: {"ev_tok": "kstart"}`, and the hub defaults to `kstart`. Code can overwrite a
     test-variable value (verified: `kstart` → `karzjc`).
   - **Not verified:** that `test_variables` apply in a *simulation* (docs: merged on web calls). Keep the
     `or 'kstart'` default in the hub either way.
5. **Chat-only caveat.** On the first chat turn routing is suppressed ("Missing prior assistant message"), so turn 1 is
   never processed. Its extraction then carries the initial token and can be read as fresh on turn 2 if turn 2's
   extraction fails (`a018453e…`, hub run 1 read the turn-1 value).
   - In a simulation the agent speaks first, so turn 1 is routed.
   - Optional hardening: the hub also stores the last processed raw `ev` and treats an identical raw string with the
     initial token as stale.

### 5. Tool results (api_request node with code-baked args, `pre_actions`)
| | success (verify_identity, real practice session) | failure (HTTP 404, unknown route) |
|---|---|---|
| `<node>_success_count` / `_failure_count` | `w_ok_success_count = 1` | `w_bad_failure_count = 1` |
| `<node>_response.status_code` | 200 | 404 |
| `<node>_response.data.ok` | `true` (string) | unset |
| node-level `response_mapping` `data.ok` | `'true'` | unset |
| `post_process_code` | ran | **did not run** |

The counters are keyed by the **node id**, not by the function name. For a write, the reducer should use
`_failure_count` and `status_code` as the source of truth for failure; it must not rely on the hook or the mapping.

### 6. Exactly-once reducer
- Hub runs: 10 = 8 user turns that were routed + 2 tool returns.
- The tool returns were correctly stale: the token had rotated, so there was no double count.
- `exact_say` (tts) followed by the customer's reply gives one routing → one hub run. No extra run after tts.

### 7c. Second close_call
- The second call does not change the outcome: the ledger keeps the first one.
- It is logged in `ledger.calls`, so `score.py`'s "close_call must be the last call" still holds.
- The judge may still read a contradictory second outcome in the transcript. The reducer must emit exactly one
  close: guard on `close_call_success_count`, or route to the close node only once.

### 8. Partial utterances (design recommendation; live test pending)
- **Design:** one composite field `n=<tok>;act=..;d=..;m=..;part=<yes|no>`, written in full by one extraction call,
  so its facets cannot diverge the way `date_iso` vs `date_spec` did in `bbe0fdd2`.
- **Reducer rule:**
  - `part=yes`, or an incomplete number: not actionable. Do not decide or clarify; use talk mode or a short neutral
    tts such as "Go on." No counter changes.
  - `part=no` with a day: decide.
  - Contradicting facets inside one event (e.g. a weekday that contradicts the day): one clarification, counted under
    its own `clarify` counter (cap 1). After the cap, pick the more specific facet (the day of month) and read it
    back, which forces the confirm step.
  - Never send a clarifying tts the first time a stale cross-field mismatch appears; that is exactly the `bbe0fdd2`
    failure.
- **Live test:** `probe/m0_partial.py` sends "I can pay on the twenty-" then "seventh". Rerun it when the chat API is
  back.

### 9. Silence
- **1327758a is a platform stall, not a graph bug.** After "Yes, this is Samuel Ortiz" at t=2.9 s there is no event
  at all: no extraction, no routing, no node entry, until the customer hung up at t=63 s.
- In the same minutes (13:41–13:47) the chat API returned repeated 503/504, and turns took minutes. These chat probes
  were running then, so they may have added load.
- **Graph rules that guarantee speech on every turn:**
  1. Every routed turn ends in a node whose `on_enter` produces text.
  2. Route to `exact_say` only when `say_next` is non-empty; the reducer sets `route='say'` only if `say_next.strip()`.
  3. Otherwise route to `talk_llm` (`on_enter: llm`), with a prompt that requires one sentence and never "nothing".
  4. The hub's last transition is `always` → `talk_llm`, so no deadlock.
  5. On `run_safe` exception, route to `talk_llm` too.
- Not measured live (outage): whether `on_enter: tts` with an empty string is silent, and how often `on_enter: llm`
  returns nothing. `probe/m0_partial.py` covers both (act `empty_say`, act `llm_say` ×2).

### Platform noise to plan for
- The chat API gave 502/503/504 under load. A retried message can be recorded twice: "Please run the bad tool."
  appears twice in `bd36d839…`.
- Make the scorer harness tolerate this, and do not judge the graph on outage-window runs.

## Smallest graph that satisfies 1–6
```
test_variables: {ev_tok: "kstart"}
<phase conversation nodes>  extraction [ev], transitions [always -> hub]
hub (code, passthrough)      reads ev, checks n == ev_tok, runs the reducer, rotates ev_tok every run,
                             sets route in {say, talk, w_<k>, close}
    -> exact_say  (conversation, on_enter tts "{{say_next}}", extraction [ev], always -> hub)   if route == 'say'
    -> w_<k>      (api_request, code-baked args, response_mapping data.ok, always -> hub)        if route == 'w_<k>'
    -> close node (api_request close_call, then end_call)                                        if route == 'close'
    -> talk_llm   (conversation, on_enter llm, extraction [ev], always -> hub)                   always (last)
ev: string, min_confidence 0.3, max_retries 2,
    validation_pattern ^n=[a-z0-9]{1,8};act=(...)...$,
    extraction_prompt: "Code: {{ev_tok}} ... copy the code letter by letter ..." + 2 examples + extractor placeholders
```
Phase separation stays in the graph (pre-verification nodes lack debt facts and write tools). Each phase can reuse
the same hub because the phase is a code-owned variable.
