# FINAL-PLAN: adjudication of Plan A (coordinator) vs Plan B (critic), and the plan for Sat 22:00 to Sun 23:00

Intended location: /home/kizil/Desktop/hackathon/ext/kickoff/FINAL-PLAN.md. Worktree isolation blocked that write, so this file was written here.
Written Sat 2026-10-10 ~22:00 Istanbul. Read-only review of `bridge-v2/builder/*`, `integration.py`, the kit README, `page.txt`,
`.claude/skills/build-phone-agent/SKILL.md`, `examples/agent_builder.py` and 20 recent builder traces. All times are Istanbul (UTC+3).
Final: briefs open **Sun 20:00** (17:00 UTC). The form must be sent **before Sun 23:00** (20:00 UTC).

---

## 0. The facts that change the plan (verified in code and on the page)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| F1 | On failure, build.py keeps "the previous export" | **TRUE, and for a hidden brief it means 0/30.** | `build.py` `finish(reason)` saves nothing (exit 2). No fallback exists. |
| F2 | Ingestion reads only .md .txt .eml .csv .json .yaml/.yml; the rest of a folder is skipped without a warning; .zip is unsupported | **TRUE** | `policy_extract.TEXT_EXT`, `read_files()`. Also missing: .tsv .xml .html .htm .rtf, and files with no extension. |
| F3 | A single non-text file passed explicitly | **Worse than skipped.** | `open(p, errors="replace").read()`: a PDF/DOCX is read as replacement-char garbage and goes to Claude without a warning. |
| F4 | 2-run disagreement handling | **Logged only.** Run 1 is used. Run 2 is used only if run 1 fails the validator. | `build.py` lines 122-135. In 20/20 recent traces (A, AB, raw-a, raw-b, ins-clean, mut-01..05) `agree: true`. |
| F5 | `core_missing` | **Computed, then ignored.** | `extract()` returns `fallback_required: bool(missing)`; build.py only logs `core_missing` and goes on. |
| F6 | A missing response binding means the tool is BLOCKED and the cases fail | **Partly. For core facts it is worse:** validator rule 13 (`verify_identity.verified_all`, `get_account.products/id/past_due/days_late`) fails both attempts, so **nothing is saved = 0/30**. For non-core facts (`ok` of other tools) it is only `api_mismatch`. | `oas_bindings.tool_results`, `validate_workflow.py` lines 259-266 |
| F7 | `$ref` is resolved | **FALSE, nowhere.** The same applies to responses under 2XX/other codes, other content types and a wrapper object (`{ok, data:{...}}`). | grep finds no `$ref` in builder/. `_resp_schema` reads 200/201/default + application/json only. |
| F8 | Binding uses field NAMES heuristically | **TRUE: this is the real OAS risk, more than `$ref`.** `verified_all` needs a bool with "verif" in its name, `wrong_left` needs `left|remain`, `past_due` needs `due|past|owed|balance`, `days_late` needs `days|late|overdue`. A rename (e.g. `identity_confirmed`) breaks the build. | `oas_bindings.py` lines 41-65; README: "The fields and the allowed values can change." |
| F9 | Greet assumes {title}/{last_name} | **Partly.** `_call_var_placeholders` maps `{x}` through the extracted `meta.call_vars`, and an unknown `{x}` is passed through as `{{x}}`. If the brief's sentence uses a name that is not a call variable, the agent **reads `{{x}}` aloud** (docs/workflow-format.md line 201). With no sentence at all, the opening is composed generically. | `generator.py` lines 200-240 |
| F10 | The example builder runs its own simulations | **TRUE, and it cannot be our fallback as it is.** SKILL step 6 runs `run_cases.py --brief A` (the PUBLIC customers, 3-11 min, up to 3 fix loops = up to 33+ min, loading our only workspace). Step 1 reads `tools/openapi.json` (the KIT OAS, not the hidden brief's). Also `claude_agent_sdk` **is not installed** here. | SKILL.md, `examples/agent_builder.py`, import check |
| F11 | (new) A silent stub hub | **Catastrophic, if rare.** If `builder.engine.reducer` raises ImportError (a missing file in a clean clone, a bad import), `integration.hub_code` silently returns the STUB hub (it always says "Sorry, could you say that again?"). The build passes and saves a dead agent. The same applies to `ev_field`. | `integration.py` `hub_code`/`ev_field` |
| F12 | (new) Time budget | **Our build takes 109-166 s** (20 traces). Of the 30 min, about 25 are free. A sequential fallback, a third run and a platform smoke test all fit. | trace `end.seconds` |
| F13 | (new) The input format | **The page's run line is `python3 builder/build.py briefs/hidden-1.md briefs/hidden-1.openapi.json`** and the form's `run_command` is `{brief_path} {tool_api_path}` (one path). The raw brief is most likely ONE .md with mail/extract/memo/code-list sections. | page.txt lines 244-262 |
| F14 | (new) Reproduction | The top-10 teams are re-run by Freya from the commit, and "if our run scores clearly below yours, the entry is removed". A clean clone must build, and any fallback must be deterministic in its triggering. | page.txt "How we verify" |
| F15 | (new) Bug fixes in the window | "Fixing a crash on a table your parser did not expect is allowed." We have 3 h and 2-3 min builds, so loud failures plus a human generic fix beat clever silent automation. | README "The final" |

### Likelihood for the hidden briefs (per brief)
| Risk | Likelihood | Impact if it hits | Verdict |
|---|---|---|---|
| A response field renamed or added (F8), core binding missing | **High (~50%)** that at least one response field changes; ~20-30% that a core binding breaks | 0/30 (no save) | **Real. Top OAS priority.** |
| A request field renamed, a new required body field, enums changed | High | block or api_mismatch; partly handled (re-extraction, block) | Covered; regression fixtures only |
| `$ref`/components in the OAS | Low (~10%): the kit OAS has `"components": {}`, inline schemas, the same 7 tools | 0/30 | Real but cheap: a 20-line resolver, do it |
| Wrapper/nested response (`data.result.products`) | Low-medium (~15%) | 0/30 | Only an explicit nested path if the reducer supports it cheaply |
| Brief is a non-text file (PDF/DOCX/zip) | Low (≤10%; F13) | Garbage policy -> wrong agent or extraction failure | Cheap insurance, hard time box |
| Brief is a folder of .md/.eml/.csv/.txt | Low-medium (~15%) | Works today; .tsv/.html/no-extension files are skipped | Covered by the UTF-8 sniff fix |
| Stub hub in a clean clone (F11) | Low | 0/30, silent | **5-minute fix, mandatory** |
| `core_missing` ignored (F5) | Medium on the raw brief | Wrong core rule on all cases | Must become a signal |
| Run disagreement (F4) | Low (0/20 so far) | A wrong core value on many cases | Targeted re-check, small |
| A placeholder spoken aloud / business customer (F9) | Medium (business/insurance brief: `{company_name}`, policy holder) | Policy or judge fail on many cases | Static check + generic rewrite, small |
| Unsupported rule types (HIDDEN-BRIEF-RISK catalogue) | **Certain** that some will appear | Partial loss of cases, not zero | Fork 3, rehearsal-driven only |

---

## 1. Decisions on the disagreements

1. **Ingestion: B wins, with A's coverage capped.**
   - Build a manifest (read / converted / unreadable, chars, sha1) in the trace.
   - Read **any file that decodes as UTF-8 and has no NUL bytes** (this drops the extension whitelist).
   - Conversions:
     - `.zip`: unpack to a temp dir and recurse.
     - `.pdf`: `pdftotext -layout` (present on this machine).
     - `.docx/.odt/.rtf/.html`: `soffice --headless --convert-to txt` (present), or bs4 for html.
     - `.xlsx`: openpyxl (present) to CSV text.
   - No OCR. A scanned PDF (fewer than 200 chars per page) is `unreadable`.
   - **An unreadable non-empty source is a hard signal (S1)**, not a warning.
   - Every converter is optional: if the tool is absent on Freya's re-run machine, the file is `unreadable` and S1 fires. Never crash.
2. **Disagreement: a targeted re-check, not a majority vote.**
   - A third full run costs ~2 min and can share the same error, so it is not evidence.
   - On `agree: false`: diff the core signatures, then make **one** Claude call. It gets ONLY the differing fields, both values, both quotes, the memo/superseded list and the precedence instruction ("a later memo overrides; a code list maps names").
   - Accept the answer only if its quote verifies verbatim **and** it equals one of the two candidates (or an OAS enum member).
   - If it fails, keep run 1 and raise S4 in the trace.
   - Plan A's "audit" pass (re-reading the whole policy against the brief) is **not done**: there is no time and no evidence it adds anything.
3. **OAS: B wins on runtime discovery (rejected); A's goal is met at build time instead.**
   (a) One `load_oas()` normaliser, used by `oas_summary`, `oas_bindings`, `generator.oas_tools`, `validate_workflow` and `selftest._oas_enum`. It resolves local `$ref` and `allOf`, takes any 2XX code or `default`, and takes `application/json` or else the first JSON-like content type.
   (b) **Build-time binding assist**, only when the deterministic binder misses a CORE fact.
       - One Claude call gets the response schema with its descriptions and returns `{fact: path, quote_of_description}`.
       - It is accepted only if the path exists AND the shape matches (bool / array-of-object / string id / number / integer).
       - It is written to the trace.
       - Never at runtime, and never "interpret ambiguous as verified".
   (c) Nested paths (`data.a.b`) only if Fork 3 confirms the reducer reads dotted paths at no cost; otherwise out of scope.
4. **Fallback: B's shape (local candidates, one save), and it is NOT the example builder.**
   - F10 rules the example builder out.
   - The L3 fallback is our own `claude -p` "direct workflow writer". Its input is the docs, `examples/base-agent.json`, the brief and **the brief's own OAS**. It has no tools and runs no simulation.
   - It starts in a thread at t0 and only writes a local file.
   - **There is exactly one `save_workflow`, to the canonical slot, after the selection.**
   - If the main path passes, the thread is cancelled, because build time is tie-break 2.
5. **Fork 3 scope: B wins.**
   - No wholesale confirmations/callbacks/topics.
   - Work only on (i) failures from the re-measure of the integration branch and (ii) gaps the frozen rehearsal packages show, ranked by cases affected.
   - Plus the nested-path answer for 3(c).
6. **Code freeze: A's 17:00 stays as the HARD freeze, with a feature freeze at 14:00** so that the dress rehearsal runs on the code that ships.

---

## 2. "Unsupported requirement detection -> fallback", concretely

The fallback ladder:
- **L0**: the normal build.
- **L1**: repair (run 2's policy; the targeted re-extraction that already exists).
- **L2**: degraded build. Regenerate with the failing *optional* features stripped (soft rules, unplaced hooks, `add_note`, `schedule_callback`, `transfer_to_agent` when their bindings are missing). The core flow is kept (identity -> account -> promise -> close).
- **L3**: the direct LLM workflow writer (local candidate, statically checked).
- **L4**: none. Exit 2 loudly: a human fixes the crash generically in the window and re-runs.

| Signal | Threshold | Action | Why |
|---|---|---|---|
| **S0** hub or ev_field source == `stub` (`GENERATED_FROM`) | any | **Abort** (exit 3, "engine not loaded"). No L3: this is a packaging bug, and the fix is to repair the clone. | F11. A dead agent must never be saved. |
| **S1** source unreadable, or total chars < 1500, or a converter failed on a non-empty file | any | Continue L0 with the readable files. If the ONLY brief file is unreadable: abort, exit 2 (a human converts it, which counts as a crash fix on input). | L3 would be equally blind, so S1 never selects it. |
| **S2** `core_missing` non-empty in **every** run | any | Targeted re-extraction of the missing paths (one call, quotes verified). Still missing -> L2 with contract defaults, **unless** the missing item is the identity questions or the closing table -> L3. | Without identity or outcomes our reducer cannot behave; L3 at least follows the prose. |
| **S3** core binding missing (rule-13 facts) after `load_oas` + the binding assist | any | **L3** | L3 reads tool results through the LLM, with no binding needed. **This is the one case where L3 beats us.** |
| **S4** core disagreement after the targeted re-check | unresolved | Keep run 1 and note it in the trace for the human; **no switch**. | Our build with one uncertain field still beats L3. |
| **S5** validator fails after L1 | errors only on optional tools/rules | **L2** | A partial loss beats 0. |
| | errors on core rules | **L3** | |
| **S6** local self-test (`run_selftest`) | safety invariants (identity before disclosure, no false "recorded") fail in > 0 scenarios | Keep ours, flag it **red** in the trace and the summary; **no auto-switch** (L3 is less safe). Human decision in the window. | |
| | crash | Log it; ignore for the selection | |
| **S7** chat smoke test after the save (Fork 5) | no reply in 20 s x2, a reply containing `{{`, or an HTTP error on chat turns 0-2 | If L3 is valid: save L3 to the same slot, export, re-smoke. Else exit 2. | It catches the "workflow cannot start a call" and placeholder classes (README troubleshooting). |
| **S8** many unmapped rules / unplaced hooks | count > 0 | **Never switch.** Print them at the top of the trace .txt as "NOT IMPLEMENTED: <quote>" for the human triage. | These are partial losses; L3 would lose more on the core. |

Is L3 better than ours? Only for S3, S2 (identity/closing missing), S5 (core) and S7, where ours would score 0.
- The example builder's v1 (no tests) passed 9/10 on public A in one run.
- On hidden, adversarial 3/3 we expect it to pass 20-50%.
- **Never prefer L3 over a validator-passing build of ours.**

The budget (default `--budget-min 25`):
- L0+L1 ≤ 6 min typical, hard cap 15 min;
- the L3 thread has its own cap of 10 min (it starts at t0, so it is ready by about t+8 min);
- L2 regenerate ≤ 1 min;
- save + export ≤ 1.5 min;
- smoke ≤ 3 min.

The worst case (L0 fails late, then L3, save, smoke) is ≈ 21 min. Fork 5 must **prove** that number with injected failures.

---

## 3. Per-session plan

The clock starts Sat 22:00. The human user sleeps about 02:00-09:00. Forks keep working overnight on **non-platform** tasks, except Fork 2's queued simulations.

### Fork 4: extract / bridge / generator / build (the critical path)
1. **22:00-22:30 S0 + S2 + exit codes.** Raise on a stub hub/ev_field; make `core_missing` a signal; turn `finish()` reasons into enumerated signal codes in the trace and the JSON result. *Exit:* a clone with `engine/reducer.py` removed gives exit 3 and saves nothing; a fixture with no identity section shows S2 in the trace.
2. **22:30-00:00 Ingestion** (decision 1). Hard cap 90 min: if the PDF/DOCX conversion is not done by then, ship the UTF-8 sniff + zip + pdftotext only. *Exit:* Cursor's binary-folder fixture gives a correct manifest; `brief-a.md` gives the same policy hash as before; no crash with `soffice` missing.
3. **00:00-01:00 `load_oas()` normaliser** (decision 3a), wired into all 5 readers. *Exit:* Cursor's `$ref` and `201` variants of the kit OAS produce a workflow **byte-identical** to the plain OAS (ignoring ids).
4. **09:00-10:30 The binding assist** (decision 3b) + the S3 signal. *Exit:* the renamed-response fixture builds and passes the validator; the ambiguous-shape fixture is refused, and S3 fires.
5. **10:30-11:30 Targeted disagreement re-check** (decision 2) + an S4 trace line. *Exit:* a unit test with two forged policies resolves to the quoted one.
6. **11:30-12:30 L2 degraded regenerate** (strip the optional features named by the validator errors). *Exit:* a fixture whose `schedule_callback` response has no `ok` field builds without callbacks instead of failing.
7. **12:30-13:00 Placeholder check (F9).** Any `{{x}}` in a tts/spoken line that is not a brief call variable, a workflow variable or a `test_variables` key -> rewrite the sentence without it (generic: drop the placeholder clause) and note it in the trace. *Exit:* a business-brief fixture with `{company_name}` declared works; an undeclared one is never spoken.

**NOT done:** runtime field discovery; a majority vote / a 3rd run; a whole-policy audit pass; OCR; new rule semantics in the bridge unless Fork 3 asks.

### Fork 5: the fallback and the self-test (new owner of `builder/fallback_llm.py`, `builder/smoke.py`)
1. **22:00-00:30 The L3 writer.** One `claude -p` call (no tools) with `docs/workflow-format.md`, `docs/tools-and-code.md`, `examples/base-agent.json`, the brief text (from the manifest) and the brief's OAS. Then a static check: valid JSON, `initial_node` exists, every transition target exists, no `agent_config`, tool URLs/names/enum values ⊂ the OAS, ≤ 128 KB per code node. One repair call on a static failure. *Exit:* on public A and B it produces a statically valid workflow in ≤ 8 min (local only, no save).
2. **00:30-01:30 Selection + single save in build.py** (paired with Fork 4: Fork 5 writes `select_candidate()`, Fork 4 merges it). L3 starts at t0 in a thread and is cancelled when L0 passes. *Exit:* the trace shows `candidate: main|degraded|llm`, plus the reason signal.
3. **01:30-02:30 Failure injection:** `BUILDER_INJECT=extract_fail|validator_core|stub_hub|unreadable|binding_core|slow_claude:600`. *Exit:* every path ends with exit 0 (a candidate saved) or a deliberate exit 2/3, and the **wall time is ≤ 25 min in all of them**; a table goes into the PR description.
4. **09:00-10:30 Chat smoke test** (`smoke.py`, inside build.py after the save, ≤ 3 min, skipped with a trace note if a simulation is running). Turn 0: the greet text has no `{{`. Turn 1: a name confirmation gets a reply in ≤ 20 s. Turn 2: an identity answer triggers `verify_identity`. The trace logs it as "test run on own agent" (the page asks for this). *Exit:* it runs green on the integration build of A, and an injected `{{bogus}}` greet fails it.
5. **10:30-12:00 A generic chat persona runner for the final window:** 5 scripted conversations built from the **built policy** (not from brief text in code): happy path, wrong identity x max, third party, dispute, a low offer. *Exit:* it runs on a hidden-like rehearsal build in ≤ 10 min. This runs only outside simulations.

**NOT done:** wrapping `examples/agent_builder.py`; running `run_cases.py` inside the builder; any second save slot.

### Fork 3: reducer
1. **22:00-23:00 Answer decision 3c** (do dotted response paths work in `tool_results`, and at what cost?), and confirm `hub_source` raises (not returns a stub) on bad input.
2. **23:00-02:00 Fix what the re-measure of the integration branch shows** (PUB-02/03/04 regressions first, then style failures from Fork 2's overnight queue). *Exit:* each fix comes with an oracle/property test, and the hub stays ≤ 100 KB packed.
3. **09:00-14:00 Rehearsal-driven gaps only:** take the top 3 failures by cases affected from the Cursor rehearsal packages run by Fork 2. A candidate for each, in this order, only if it is observed:
   - HIDDEN-BRIEF-RISK F5 (the `reject` false sentence);
   - F6 (the recording notice);
   - F7 (the identity answer prompt format).
   *Exit:* the failing rehearsal case passes 3/3 and nothing regresses on A/B reps3.

**NOT done:** confirmations, customer callbacks and new topics as features; refactors; anything after 14:00 except crash fixes.

### Fork 2: platform (simulations, serialised; no chat while a simulation runs)
1. **22:00 Re-measure the integration build:** A `--reps 3`, then B `--reps 3`. *Exit:* a baseline number (target A ≥ 9/10 3/3).
2. **Overnight queue (unattended):** A and B with `--style pieces`, `corrects`, `talkative`, `asks_back`, `in_words`; post the failures by call id to Fork 3 by 09:00.
3. **09:00-13:30 The rehearsal packages from Cursor** (built with build.py real save, own slots `reh-*`), one 10-case run each, then `--reps 3` on the worst one. *Exit:* a failure table for Fork 3 ranked by cases.
4. **14:00-17:00 Dress rehearsal on a fresh clone at the feature-freeze commit**, timed, with the exact final-night commands on 2 rehearsal packages (one clean, one raw), including the save, export, smoke and trace. *Exit:* both builds ≤ 10 min, exit 0, the exported files load, and a 10-case run on each.
5. Keep the workspace under 190 workflows (delete the `reh-*` slots after Sunday 17:00).

### Cursor: fixtures only (deliver in this order; each with `expected.json`)
1. **By 23:30:** OAS mutations:
   - a `$ref`+components version of the kit OAS;
   - responses under `201`;
   - renamed response fields, core and non-core (e.g. `all_verified -> identity_confirmed`, the past-due and days-late fields);
   - an ambiguous shape (two bool "verif" fields);
   - a wrapper `data:{...}`;
   - a new required body field.
2. **By 00:30:** an ingestion folder: the same Brief A raw package as `.md`, `.eml`, `.tsv`, no-extension, `.html`, `.pdf` (text), `.pdf` (scanned image), `.docx`, `.zip`.
3. **By 08:30:** rehearsal packages compatible with the public A/B customers (the same expected outcomes):
   - a clean re-worded spec;
   - a raw single-.md package (mail + policy extract + **overriding memo** + code list);
   - a raw multi-file folder;
   - a business-customer variant with `{company_name}`.

**NOT done:** code in `builder/`.

---

## 4. The freeze and the final-day runbook (Sunday)

- **14:00 feature freeze**: merge everything into `final`; after this, only fixes found by the dress rehearsal.
- **17:00 HARD freeze**: tag `final-freeze`, push, and record the clean-clone check (`git clone`, env, `python3 builder/build.py briefs/brief-a.md tools/openapi.json --mock-freya` exit 0, and the hub source != stub).
- **19:30 pre-flight:**
  - a clean clone at the tag; `claude` logged in; `FREYA_API_KEY`/`FREYA_BANK_TEAM_KEY` set;
  - a freya ping; no simulation running; workflows < 190;
  - `traces/` and `submission/` empty; a dry `--mock-freya` run on public A.
- **20:00** fetch the briefs. Store them exactly as delivered under `briefs/` (`hidden-1.md` + `hidden-1.openapi.json`, or the folder/zip as given). Record their sha1.
- **20:02** `python3 builder/build.py briefs/hidden-1.md briefs/hidden-1.openapi.json 2>&1 | tee traces/hidden-1.log`, and at **20:04** the same for hidden-2. They use different slots; both use only Claude until the save, and the smoke tests are short.
- **20:15 Triage of each trace .txt**, as a checklist: exit code + candidate; S-signals; source manifest; `core_agreement`; `api_mismatch` + blocked; the "NOT IMPLEMENTED" list; self-test red flags; smoke.
- **20:20-21:40 Test and fix loop:**
  - the persona chat runner (Fork 5) on each agent;
  - the human reads the transcripts against the brief;
  - a fix is allowed only for a crash/parse bug that is **brief-agnostic** (no rule, value or name from a hidden brief in code or prompts);
  - each fix -> commit -> a **full re-run** of build.py (new trace).
  - Max 2 re-runs per brief; the last re-run must start by **21:40**.
- **21:45 Decision gate:** per brief, pick the run with the best evidence, ranked: (1) no red flags; (2) the smoke test is green; (3) the persona chats are correct; (4) shorter build time. Its export **must** be the file that run wrote. Never edit by hand.
- **22:00** copy to `submission/hidden-{1,2}.workflow.json` + `traces/hidden-{1,2}.log` (+ .jsonl); strip keys (grep for `FREYA_`, `sk-`); commit; push; record the sha.
- **22:15** fill in the form JSON (repo, commit, `run_command: python3 builder/build.py {brief_path} {tool_api_path}`, paths). **Send it by 22:30**, which leaves 30 min of margin before 23:00.
- **22:30-23:00** a buffer only. No re-runs after the form is sent.

Roles in the window:
- Fork 2: runs the builds and exports.
- Fork 5: smoke tests and persona chats.
- Fork 4: generic crash fixes.
- Fork 3: on call for reducer crashes only.
- The human: triage, decisions, submission.

## 5. Explicitly NOT done (the whole plan)
- Runtime field discovery in tool responses; a majority vote; a whole-policy audit pass; OCR.
- Wrapping/running the kit example builder; `run_cases.py` inside the builder; parallel saves or two slots per brief.
- Wholesale new rule features (confirmations, callbacks, topics) without a rehearsal failure behind them.
- Any feature work after 14:00 Sunday; any change after 17:00 except a crash fix verified on public A.
