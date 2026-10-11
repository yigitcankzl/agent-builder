# Final-case runner (test infrastructure only)

Runs final-case cases against a phone agent through the simulations API, the same way `tools/run_cases.py` does. It does not touch `builder/`, the reducer, the generator or any prompt.

## Files

| File | What it does |
|---|---|
| `run_final.py` | Cases → Turkish personas → Freya simulation → per-case results |
| `convert_shadow.py` | Shadow personas (`tests/final_shadow/render.py` output) → case format |
| `test_payload.py` | Offline unit tests of the payload shape (no Freya call) |

## Case format

A JSON list. Each case:

| Key | Meaning |
|---|---|
| `id` | unique |
| `customerNumber` | 8 digits (the IVR gives it; the agent never asks) |
| `now` | Istanbul time, e.g. `2026-10-12T10:30:00+03:00` |
| `script` | Turkish: what the caller knows and wants, how they react to each offer; end with "anything else → refuse" |
| `checks` | judge success criteria, plain words (required unless `unchecked: true` + `--allow-unchecked`) |
| `style` | optional kit style (`pieces`, `corrects`, `talkative`, `asks_back`, `in_words`) |
| `expect` | optional `{"mock": {...}}`: expected mock side effects, compared with a read-only state read |
| `title` | optional short name |

Values come only from the case files or bindings; nothing in the runner carries case facts.

## Commands

Dry run (prints the persona and simulation payloads, makes no Freya call):

    python3 tests/final_runner/run_final.py <agent_id> --cases <cases.json> --dry-run

Real run (Freya; concurrency 5 by default, no re-send on 503/504, waits if another sim runs):

    python3 tests/final_runner/run_final.py <agent_id> --cases <cases.json> --reps 3 --out results/final.json [--style talkative] [--mock-state https://freya-final-mock.kizilyigit33.workers.dev]

`--mock-state` reads `GET {base}/state/{customerNumber}` (read-only). The mock's state route is not fixed yet; without it the expected side effects are reported as not checked.

Offline tests:

    python3 tests/final_runner/test_payload.py

Shadow personas to cases (checks come from a meta file written by the case owner):

    python3 tests/final_shadow/render.py tests/final_shadow/persona_templates.json <bindings.json> -o rendered.json
    python3 tests/final_runner/convert_shadow.py rendered.json --meta <meta.json> -o <cases.json>

## Results

Per rep: the simulation id, and per case pass/fail, the judge reason, the call id, the slowest agent turn, the tools called (by URL segment for `api_call`) and the mock check. `summary` gives passes/runs per case. Errors are recorded and not retried.

## Not done yet

- The sample conversations (`example-scenarios.md`) → case converter: waits for the file.
- The mock's state route: a hook only.
