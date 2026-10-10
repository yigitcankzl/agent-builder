# Ingestion

Local files only. Pebble Mutual is fictional. Nothing here is called.

The same collections extract is a text PDF and a zip. The zip member is `policy-extract.txt`. A reader has to open the zip; the PDF is not inside it. Both carry the same sentences, including the late deadline of the 6th business day.

| File | What it is | What must be read |
|---|---|---|
| `policy-extract.pdf` | Text PDF, not a scan | Institution, identity order, three wrong answers, the 6th-business-day deadline, Monday to Friday, the card floor |
| `policy-extract.zip` | Zip of that same extract | The same facts, from member `policy-extract.txt` |
| `opening.docx` | Opening note | The recorded-call sentence, and the callback window 10:00 to 18:00, both included |
| `memo.html` | Later memo | It wins over the extract. The late deadline becomes the 4th business day. 19 October 2026 is a holiday. |
| `codes.xlsx` | Sheet `codes` | Alias `arranged` to outcome `promise`. Alias `hardship_desk` to queue `support`. |
| `junk.bin` | Binary, not a document | Nothing. It is not a PDF, a zip, or text. |

`expected.json` names each fact, the file it comes from, and the quote or the cells. The merged late deadline is the memo's 4th business day, not the extract's 6th.
