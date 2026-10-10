"""Cursor's ingestion fixture (fixtures-briefs 51768eb, tests/fixtures/ingestion): every expected file read or refused
as expected.json says, and every expected fact's quote (or cells) present in the text of the file it names.

    python3 tests/test_ingest_fixtures.py
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine.date_policy import _norm
from builder.ingest import ingest, s1

FX = os.path.join(ROOT, "tests", "fixtures", "ingestion")
fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


if __name__ == "__main__":
    files, man = ingest([FX])
    exp = json.load(open(os.path.join(FX, "expected.json")))
    by = {m["name"]: m for m in man}
    for m in man:
        print(f"     {m['name']:40} {m['status']:10} {m.get('how', '')[:40]:40} {m.get('chars')}")
    for f in exp["files"]:
        name = "ingestion/" + f["path"]
        if f.get("members"):
            got = [k for k in files if k.startswith(name + "/")]
            check(f["read"] == bool(got) and all(any(k.endswith(x) for k in got) for x in f["members"]), f"{f['path']}: members {got}")
        else:
            ok = (by.get(name, {}).get("status") in ("read", "converted")) == f["read"]
            check(ok, f"{f['path']}: read={f['read']} (status {by.get(name, {}).get('status')}, {by.get(name, {}).get('how')})")
    for fact in exp["facts"]:
        src = "ingestion/" + fact["file"]
        texts = [t for k, t in files.items() if k == src or k.startswith(src + "/")]
        hay = _norm(" ".join(texts))
        q = fact.get("quote")
        if q:
            check(_norm(q) in hay, f"fact {fact['fact']}: quote found in {fact['file']}")
        else:
            cells = [str(c) for c in (fact.get("cells") or fact.get("row") or []) if c not in (None, "")]
            check(cells and all(_norm(c) in hay for c in cells), f"fact {fact['fact']}: cells {cells} found in {fact['file']}")
    probs = s1(man, files)
    check(any("junk.bin" in p for p in probs) and len([p for p in probs if p.startswith("unreadable")]) == 1,
          f"S1 names only junk.bin: {probs}")
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
