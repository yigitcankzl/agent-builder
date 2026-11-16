# Cedar Credit — sources pasted into one file

Cedar Credit is fictional. A customer may be late on one, two, or three products. The practice customers keep the identity and the balances the mock already has.

## Source: note from the chair

From: Chair of credit <chair@cedarcredit.example>
To: collections@cedarcredit.example
Date: Thu, 1 Oct 2026 08:00:00 +0000
Subject: What to follow

The meeting transcript below is the collections procedure. The code table at the end is how an office word is sent to the API. Where the meeting uses an office word, send the table's api value. The table does not change a date, a floor, or which product is transferred. The meeting wins on those.

## Source: meeting transcript, 2 October 2026, 10:00

Speakers: Alex (policy), Dana (dialler)

Dana: How does the call start?

Alex: Say you are calling from Cedar Credit and that the call is recorded. Do not say collections, debt, payment, or a product before identity is verified. The greeting question is fixed. Ask "Am I speaking with {title} {last_name}?"

Dana: Identity?

Alex: Date of birth first, then the last four digits of the phone number. Three wrong answers end it. The office word is failed_id, and we do not state the account. A second refusal to answer is failed_id as well, with reason declined.

Dana: Products. We have cards, personal loans, and car loans. Take them in the order get_account returned them. State every late product, then ask whether they can pay all of the ones we are allowed to promise today. Do not ask about today again for each product.

Alex: Car loans are the exception. We do not promise a car loan. There is no car floor and no note on the car. Transfer every car loan to the new_plan queue. That transfer is instead of a promise.

Dana: Floors, and they are not the same. A credit card's floor is 40 percent of past_due, rounded half up to the penny. Three hundred on a card has a floor of 120. A personal loan's floor is 25 percent of past_due, rounded half up to the penny. Nine hundred on a personal loan has a floor of 225. Thirteen twenty on a personal loan has a floor of 330. Do not put the card's 40 percent on a loan. Forty percent of thirteen twenty is 528, and that number is wrong for a loan. The minimum and the instalment are not the floor.

Alex: Ask for the full past_due. Never ask how much they can pay. Accept the full past_due, or that product's exact floor once they have said the full amount is too much. If the full amount is too much, offer that product's floor once, on its deadline. That offer does not use an attempt.

Dana: Deadlines. Today does not count. Business days are Monday to Friday. Holidays are Friday 16 October 2026, 25 December 2026, 26 December 2026, and 1 January 2027. From Wednesday 14 October 2026 the business days after today are Thursday 15 October, Monday 19 October, Tuesday 20 October, and Wednesday 21 October. The next business day after Friday 16 October 2026 is Monday 19 October 2026.

Alex: One to ten days late is early. The deadline is the 3rd business day after today, Tuesday 20 October 2026. One attempt. Eleven to forty days late is late. The deadline is the 2nd business day after today, Monday 19 October 2026. Two attempts. The band is per product, from that product's days_late.

Dana: A promise is today or later, a business day, and not after that product's deadline. A date they name that is a business day on or before the deadline does not use an attempt. A weekend or a holiday that is not after the deadline moves to the next business day, and you say so. A date after the deadline is answered by offering the full past_due on the deadline. A flat no, with no date and no amount, uses an attempt. Early has no second attempt. On the late band the second attempt is the floor on the deadline.

Alex: One date for every product you are allowed to promise. The car is not in that set. If the date is not a business day, move it to the next business day when that day is on or before the product's deadline. If it is past a product's deadline, that product is recorded on its own deadline.

Dana: Read every promise back together. Ask "Do you confirm?" once. Then create_promise once per product you are promising. After each successful create_promise, say "A confirmation email will be sent to the address on file."

Alex: A product with no promise and no transfer gets a note. The office word for a refusal is will_not_pay. Write that note even when another product is transferred. The car transfer does not erase it. Do not write a note on the car.

Dana: Save the promises, then write the refused notes, then transfer the car if there is one, then close. close_call is last. If you transferred, the outcome word is handed_over, not arranged, even when other products have a promise or a note. The close reason is restructuring. If you saved a promise and did not transfer, the outcome word is arranged and there is no reason. If nothing was saved and nothing was transferred, the outcome word is declined and the reason is refused.

## Source: code table

Office words from the meeting. Send the api value.

| office_word | api_field | api_value |
|---|---|---|
| arranged | close_call.outcome | promise |
| settled | close_call.outcome | paid |
| handed_over | close_call.outcome | transferred |
| declined | close_call.outcome | no_promise |
| failed_id | close_call.outcome | not_verified |
| no_contact | close_call.outcome | not_reached |
| will_not_pay | add_note.reason | refused |
| new_plan | transfer_to_agent.queue | restructuring |
| help_desk | transfer_to_agent.queue | support |
