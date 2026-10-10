"""Phase 2 of STYLES-RESEARCH.md: the 14 style paragraphs -> tests/styles/styles.json, and per brief and pass a copy of
the brief's cases.json with a "style" key per case (the matrix), -> tests/styles/<brief>-p<pass>.json.
    python3 tests/make_styled_cases.py <STYLES-RESEARCH.md> <rehearsal fixtures dir>"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec, fix = sys.argv[1], sys.argv[2]
text = open(spec).read()
styles = json.loads("{" + ",".join(re.findall(r'```\n("[a-z_]+": ".*?"),?\n```', text, re.S)) + "}")
assert len(styles) == 14, len(styles)
CODE = dict(PC="pieces_corrects", TA="talkative_asks_back", WP="in_words_pieces", HY="hedged_yes", RC="refuse_and_counter",
            PD="past_dates", PB="per_product_breath", CO="cuts_off", HN="hedged_no", MC="mind_change_readback",
            OO="out_of_order", EA="echo_amount", TE="terse", DN="date_numeric")
matrix = {}
for table in re.findall(r"\| Case \|(.*?)\n\|---.*?\n(.*?)\n\| calls", text, re.S):
    briefs = [b.strip() for b in table[0].split("|") if b.strip()]
    for row in table[1].splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        for b, cell in zip(briefs, cells[1:]):
            if "/" in cell:
                matrix.setdefault(b, {})[cells[0]] = [CODE[x.strip()] for x in cell.split("/")]
out = os.path.join(ROOT, "tests", "styles")
os.makedirs(out, exist_ok=True)
json.dump(styles, open(os.path.join(out, "styles.json"), "w"), indent=1)
for b, rows in matrix.items():
    cases = {c["id"]: c for c in json.load(open(os.path.join(fix, b, "cases.json")))}
    for p in (0, 1):
        styled = [dict(cases[i], style=s[p]) for i, s in rows.items() if i in cases]
        missing = [i for i in rows if i not in cases]
        json.dump(styled, open(os.path.join(out, f"{b}-p{p + 1}.json"), "w"), indent=1)
        print(b, f"p{p + 1}", len(styled), "cases", ("missing " + ",".join(missing)) if missing else "")
