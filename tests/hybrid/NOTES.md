# Hybrid L3 + gates: findings (2026-10-11)

Status: development stopped; the main path was recommended as the final candidate. Last saved versions:
hybrid-raw-4 v7, hybrid-raw-5 v5, hybrid-brief-a v5 (agents c74f858e, 22e44b91, c7084097). Branch hybrid; offline
fixes after those saves (11a6a82) are NOT saved.

## Design
L3 workflow (the LLM converses with the whole brief) + Fork 3's gates (builder/engine/gates.py) as model-called
code_exec tools (check_terms, next_offer, confirm, say_once), create_promise gated by its pre_process_code.
build.py: BUILDER_HYBRID=1 (off by default). Wiring < 1 s; build = max(extraction, L3) ~ 2-4 min.

## Platform facts (live probes)
- A model-called code_exec tool gets the CURRENT args in the global `params`; vars['<tool>_args.*'] holds the previous
  call's (written after the run). The model sees only "Code executed successfully".
- Routing is evaluated after a tool call only if no transition was taken earlier in the turn. A gate sentence is
  spoken by routing to a full copy of the host node whose on_enter tts is {{gate_say}} (two alternating copies).
- A {{var}} written by code resolves in task_message after the tool call (same turn).
- pre_process_code runs on a model-called api_call: it can rewrite the body and block via a .invalid url. A blocked
  write is a transport error: post_process_code does NOT run; the model sees the raw error text.
- The model issues tool calls in PARALLEL (confirm yes + next): two gate runs race on gate_st.
- Extraction min_confidence: a clear "Yes, I confirm." came back at 0.593 once a second field shared the node.
- PAYLOAD LIMIT: every code_exec / hook prints __CODE_EXEC_RESULT__ + the whole var table (+ result/config) and the
  platform cuts it near 10,000 chars; a cut result is unparseable ("Sandbox did not return a parseable result",
  returncode=0) and from then on EVERY hook in the call fails (close_call too). Measured (json.dumps of the var table):
  8c4f0608 (v6 PUB-06) 5.9k -> 7.1k at the write -> hooks broke (the bank had recorded pr1, the model said it could
  not be saved); d8f32d92 (v6 PUB-07) 6.5k at the write -> hooks ran. The main path's answer is reducer.enforce_budget
  (RETURN_BUDGET 9,000). The hybrid has no budget: v8 would need one in every gate and hook.

## Results (Fork 2)
raw-4 v5 10/10 single; brief-a v3 talkative 7/10, pieces 6/10; raw-5 v3 2/3; raw-4 v6 reps-3 pass^3 6/10;
main path: raw-4 8/10, A talkative 9/10 pass^3.

## Fails and causes
- PUB-01 47b66117: a change voided the read-back, the model's confirm(yes) hit it silently -> service_error.
- brief-a talkative: PUB-05 sympathy/support repeated + an offer after hardship; PUB-06 offer re-asked in the model's
  own words 30x; PUB-09 chatter taken as refusing identity; PUB-10 "this call is recorded" (honesty word).
- pieces PUB-04/07/10: parallel confirm(yes)+confirm(next) race.
- raw-4 v6 PUB-07/04: the yes discarded at 0.593 -> blocked -> raw DNS error -> "could not be saved".
- raw-4 v6 PUB-06: payload limit (above).
Lesson: each LLM-drift or platform effect needed its own guard; the main path's engine already owns these.
