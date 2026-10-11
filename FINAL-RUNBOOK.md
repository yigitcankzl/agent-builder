# Final runbook

The final opens at **20:00 Istanbul** and closes at **23:00 Istanbul**. It is one Turkish credit-card statement-debt
case. The bank zip contains mixed documents, a service contract, test customers, Q&A and six example conversations.

## Before 20:00

- [ ] `npx wrangler login` succeeds.
- [ ] `python3 tests/test_ingest.py` and `python3 tests/test_ingest_fixtures.py` pass.
- [ ] `python3 tests/test_final_entry.py` passes.
- [ ] `npx wrangler deploy --dry-run --config final-mock/wrangler.jsonc` passes.
- [ ] Frozen fallback remains `b1b2191b31030b36dd6ad0b027dbbb605d2bfdf4` on remote `integration`.

## 20:00-20:30 — evidence and mock

1. Download and unzip the case. Read `BRIEF.md`, then `README.md`; inventory every file.
2. Implement the supplied service contract and customers in `final-mock/`. Final data belongs in the mock, never in
   `builder/` or its prompts.
3. Make the mock expose its exact OpenAPI contract at `GET /openapi.json`.
4. Deploy; verify the public `/health` and one read/write lifecycle from the supplied test customers.

## 20:30-21:00 — one builder run

```bash
mkdir -p traces submission
python3 builder/final.py /absolute/path/to/CASE_FOLDER https://YOUR_WORKER.workers.dev \
  2>&1 | tee traces/final.log
```

Do not edit the workflow after the run. Confirm `submission/final.workflow.json`, the JSONL/TXT trace and
`submission/final.openapi.json` exist. Remove keys/tokens from `traces/final.log` before committing.

## 21:00-22:15 — verify, fix only generic bugs

1. Run the six supplied example conversations against the exact exported workflow and public mock.
2. Classify failures: mock contract/data, source ingestion, extraction/bridge, reducer/graph, or platform.
3. A builder change must be generic. Never add a final rule, name, field or value to `builder/` or prompts.
4. If a generic fix is needed, commit it and rerun the builder from scratch; submit only one run and its matching trace.

## 22:15-23:00 — freeze and submit

1. Export the exact selected workflow with `freya.export_workflow` if the build did not already do so.
2. Fill `submission.json` from `submission.example.json`; use the exact selected commit and matching trace.
3. From a clean clone, check the run command starts and the referenced files exist.
4. Push the commit, email `submission.json` to the address in the kit email, and keep the Worker online.

If Cloudflare or Freya returns 5xx, first verify whether the operation actually completed. Do not create duplicate
workflows or writes by retrying blindly.
