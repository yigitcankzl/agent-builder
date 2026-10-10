# Speech-hard public cases

Frozen. Two siblings of each public case, PUB-01 through PUB-13. `variables`, `identity`, `products` and `expected` are copied from `public-test-set.json`. The speech is in the script, in the organisers' second-person form, with a reaction table that ends `anything else → refuse`.

Do not pass `--style`. One style flag would replace this mix, and `messy` and `compound` are not names in `tools/run_cases.py`. Run `messy.json` and `compound.json` as two `--cases` files. PUB-02 stays `family` `Third party`, so the husband is not given Maria's security answers.

`now` is Wednesday 14 October 2026, 11:00. The ledgers are the public ones: today is 14 October, tomorrow is 15 October, this Friday is 16 October, the late deadline is 23 October, and the day after the 26 October holiday is 27 October.

## messy.json

A messy talker rambles, uses fillers, asks one question back, says an amount in words or across two turns, corrects one figure mid-sentence, and names one date that is not the payment.

| Case | Trap | Ledger |
|---|---|---|
| PUB-01 | Dentist on 30 October, then "four hundred, sorry, four hundred and twenty", and "why do you need that?" before the date of birth | 420 on 2026-10-14 |
| PUB-02 | "What is this about?", an offer to pay, and this Friday before tomorrow at eleven | `not_reached` / `callback`, 2026-10-15 11:00 |
| PUB-03 | Each wrong date is spoken in words with the year held back, plus "how much do I owe?". The real date 21 July 1992 is never said | `not_verified` / `failed` |
| PUB-04 | Dentist on 15 October, "are you a robot?", and "the sixth of December, sorry, the sixth of November" | 1250 on 2026-10-23 |
| PUB-05 | 30 October is mentioned and is not a payment. He still lost his job, asks for a discount, and declines support | `no_promise` / `hardship` |
| PUB-06 | Thursday, then this Friday. "Six hundred, sorry, six hundred and thirty-seven pounds fifty", split across two turns. If asked for an amount: "you tell me" | 637.50 on 2026-10-16 |
| PUB-07 | Wedding on the 30th, then "the week after next". "Monday the 19th, sorry, Monday the 26th" | 540 on 2026-10-27 |
| PUB-08 | "Is this a scam?", and "yesterday, sorry, this morning". Friday is not when she paid | `paid` |
| PUB-09 | 6 November is mentioned and is not a payment. "Which account is this about?" before the phone digits | `transferred` / `restructuring` |
| PUB-10 | Monday 19 October, then this Friday. "Three hundred, sorry, three hundred and sixty-five", split across two turns | 365 on 2026-10-16 |
| PUB-11 | 30 October, then all three this Friday, amounts in words. "Which of the three is this?" | 220, 640 and 75 on 2026-10-16 |
| PUB-12 | This Friday, then tomorrow for the card. "Why do you need the phone?", then 4401 in two turns, and 4410 only when asked again | card 510 on 2026-10-15. Notes `refused` on p2 and p3 |
| PUB-13 | The 16th, then "the 23rd, sorry, the 30th". The card stays on the 30th | card 300 on 2026-10-30, loan 900 on 2026-10-23 |

## compound.json

A compound speaker puts two intents in one sentence, answers a different question and then the real one, and starts an agreement with "I suppose" or "if I must". A matching read-back still ends with "Yes, I confirm."

| Case | Trap | Ledger |
|---|---|---|
| PUB-01 | "I can pay the full 420 today, are you a robot?" The date-of-birth turn starts with the phone digits | 420 on 2026-10-14 |
| PUB-02 | One sentence asks what the call is about, offers to pay, and gives tomorrow at eleven | `not_reached` / `callback`, 2026-10-15 11:00 |
| PUB-03 | Each wrong date shares a sentence with "how much do I owe?" | `not_verified` / `failed` |
| PUB-04 | "I can pay on 6 November, are you a robot?" The 23 October agreement starts with "If I must" | 1250 on 2026-10-23 |
| PUB-05 | "I lost my job and I cannot pay, can you take something off?" The support answer is "If I must answer, no." | `no_promise` / `hardship`. Debatable |
| PUB-06 | "That's too much, can I do 300 next week?" 300 and next week are refused. The agreement is still 637.50 this Friday | 637.50 on 2026-10-16 |
| PUB-07 | "Not today, but the week after next." The exact day is "Monday the 26th, I suppose", with the wedding in that same sentence | 540 on 2026-10-27 |
| PUB-08 | "I paid it in the app this morning, is this a scam?" | `paid` |
| PUB-09 | "I can't pay this amount, can you lower the instalments?" A question about today is answered with the instalment request | `transferred` / `restructuring` |
| PUB-10 | "Not today, but I could do Friday, are you a robot?" | 365 on 2026-10-16 |
| PUB-11 | "Not today, but I could do Friday." A question about one product is answered for all three | 220, 640 and 75 on 2026-10-16 |
| PUB-12 | "The card tomorrow, but not the loan and not the car." The phone turn starts with the date of birth, then 4401 | card 510 on 2026-10-15. Notes `refused` on p2 and p3 |
| PUB-13 | "Not today, but I could do the 30th for both." The loan's earlier day and the card's 30 October are accepted in one sentence | card 300 on 2026-10-30, loan 900 on 2026-10-23 |

## Debatable

PUB-05 in `compound.json` only. "If I must answer, no" declines the support transfer, which is the public ledger `no_promise` / `hardship`. A reader could treat "if I must" as agreeing to the transfer and close `transferred` / `support`.

No other trap is debatable. Each reaction table says which date and which amount are the agreement, and the distractor is named as not a payment. A hedged agreement that matches the read-back still includes "Yes, I confirm."
