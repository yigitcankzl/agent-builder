# Final mock scaffold

This is deliberately not a bank implementation. The final service contract and test customers are not public yet,
and final-case values must not be written into the builder.

Before the final opens:

```bash
npx wrangler login
npx wrangler deploy --dry-run --config final-mock/wrangler.jsonc
```

After it opens:

1. Implement only the endpoints in the supplied service contract in `src/index.js`.
2. Replace `openapi.json` with the same endpoints, exact request fields, required fields, types and enums.
3. Seed only the supplied test customers and persist every ledger write as the contract requires. Do not rely on
   process memory: Worker instances are disposable. Use the smallest Cloudflare persistent store that satisfies the
   contract.
4. Run locally, then deploy and verify `/health` and `/openapi.json` from the public URL.
5. Keep the Worker deployed until results are published.

The final builder entry point downloads `/openapi.json` and pins every tool server to the submitted mock URL.
