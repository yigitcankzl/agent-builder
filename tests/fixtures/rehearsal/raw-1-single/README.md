# raw-1-single

The same Pebble Mutual pack as `tests/fixtures/rehearsal/raw-1`, pasted into one Markdown file. `cases.json` and `cases-surface.json` are copies of that pack. `openapi.json` is the kit file. The ledgers are unchanged. None are debatable.

`now` is Wednesday 14 October 2026, 11:00. Run the two case files separately. Do not pass `--style`.

## Precedence

1. The dialler email of 1 July 2026 sets the opening, the callback window, and the relative rule. It says it does not change bands, holidays, or the confirmation sentence.
2. The policy extract effective 1 July 2026 is the base for bands, the 50 percent floor, product order, and the text-message sentence. It says a later memo wins on a conflict.
3. The memo of 8 October 2026 wins wherever it conflicts with the extract. The email stays where the memo is silent.
4. `codes.csv`, pasted at the end, maps `arranged` to the kit outcome `promise`. The ledgers use `promise`.

## Where each live rule is

| Rule | Where it lives |
|---|---|
| Opening, callback 10:00–18:00, relatives | 1 July email |
| Identity, product order, one date for every product, notes, attempts | 1 July extract. The memo does not replace these |
| Holidays, including Friday 16 October 2026, and the worked 4th and 8th business days | 8 October memo |
| Late deadline, the 4th business day, not the 6th | 8 October memo. The extract's 6th is dead |
| Early deadline, the 8th business day | 1 July extract, and the memo says it stays |
| Floor, 50 percent. 2125.10 → 1062.55. 1320 → 660 | 1 July extract. The memo does not replace it |
| Confirmation sentence | 8 October memo. The July text-message sentence is withdrawn |
| Outcome `arranged` | 1 July extract, then the code list sends `promise` |

The case table is the one in `tests/fixtures/rehearsal/raw-1/README.md`. PUB-11 is 220, 640 and 75 on 2026-10-19. PUB-12 is 510 on 2026-10-15 and 660 on 2026-10-21, with the car refused. PUB-13 is 300 on 2026-10-27 and 900 on 2026-10-21. PUB-04 is 1250 on 2026-10-21. PUB-06 is 1062.55 on 2026-10-21. PUB-07 is 540 on 2026-10-26.
