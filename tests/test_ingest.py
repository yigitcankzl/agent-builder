"""Source ingestion (builder/ingest.py) and signal S1, offline. Fixtures are written to a temp dir by this test.

    python3 tests/test_ingest.py
"""
import json, os, shutil, sys, tempfile, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder import ingest as I

fails = []


def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c:
        fails.append(m)


def mini_pdf(path, text):
    """A minimal one-page PDF with a text layer (hand-written objects, valid xref)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    open(path, "wb").write(out)


def mini_docx(path, paras):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, "brief")
        os.makedirs(os.path.join(d, "sub"))
        open(os.path.join(d, "policy.md"), "w").write("# Policy\nRule 1. Say the call is recorded.\n" * 40)
        open(os.path.join(d, "codes.csv"), "w").write("code,outcome\nP1,promise\n")
        open(os.path.join(d, "memo.cp1252.txt"), "wb").write("Memo – the café rule changes.\n".encode("cp1252"))
        open(os.path.join(d, "sub", "utf16.txt"), "wb").write("UTF-16 memo: rule 2.\n".encode("utf-16"))
        open(os.path.join(d, "logo.bin"), "wb").write(bytes(range(256)) * 4)
        open(os.path.join(d, "page.html"), "w").write("<html><body><h1>Rules</h1><p>Do not say <b>debt</b>.</p><script>x=1</script>"
                                                       "<table><tr><td>A</td><td>B</td></tr></table></body></html>")
        mini_docx(os.path.join(d, "memo.docx"), ["Memo from Ops", "Weekend dates are refused."])
        mini_pdf(os.path.join(d, "extract.pdf"), "Holidays: 2026-12-25 and 2027-01-01.")
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            wb.active.append(["code", "outcome", "reason"])
            wb.active.append(["OUT_PROM", "promise", ""])
            wb.save(os.path.join(d, "codes.xlsx"))
        except ImportError:
            pass
        files, man = I.ingest([d])
        st = {m["name"]: m["status"] for m in man}
        check(st.get("brief/policy.md") == "read" and "Rule 1" in files["brief/policy.md"], "markdown read as is")
        check("café" in files.get("brief/memo.cp1252.txt", "") and "–" in files["brief/memo.cp1252.txt"], "cp1252 text decoded")
        check("rule 2" in files.get("brief/sub/utf16.txt", ""), "UTF-16 with BOM decoded")
        check(st.get("brief/logo.bin") == "unreadable" and "brief/logo.bin" not in files, "a binary file is unreadable, never garbage text")
        h = files.get("brief/page.html", "")
        check("Do not say debt." in h and "x=1" not in h and "<" not in h, f"html to text: {h!r}")
        check("Weekend dates are refused." in files.get("brief/memo.docx", ""), "docx via stdlib")
        check("2026-12-25" in files.get("brief/extract.pdf", ""), "pdf via pdftotext")
        if "brief/codes.xlsx" in st:
            check("OUT_PROM,promise" in files.get("brief/codes.xlsx", ""), "xlsx via openpyxl")
        check(all({"name", "status", "how", "chars", "sha1"} <= set(m) for m in man), "manifest fields")
        # a zip, and a zip with a path traversal
        zp = os.path.join(tmp, "pack.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.write(os.path.join(d, "policy.md"), "inner/policy.md")
            z.write(os.path.join(d, "memo.docx"), "inner/memo.docx")
        files2, man2 = I.ingest([zp])
        check("pack.zip/inner/policy.md" in files2 and "Weekend dates are refused." in files2.get("pack.zip/inner/memo.docx", ""),
              f"zip expanded and walked: {sorted(files2)}")
        bad = os.path.join(tmp, "evil.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../../escape.txt", "x")
        _, man3 = I.ingest([bad])
        check(man3[0]["status"] == "unreadable" and "unsafe" in man3[0]["how"] and not os.path.exists(os.path.join(tmp, "..", "escape.txt")),
              "a zip path traversal is refused")
        # missing converters never crash
        real = I.shutil.which
        I.shutil.which = lambda *_: None
        try:
            f4, m4 = I.ingest([os.path.join(d, "extract.pdf")])
            check(m4[0]["status"] == "unreadable" and "not installed" in m4[0]["how"], "no pdftotext -> unreadable with a note")
            odt = os.path.join(tmp, "x.odt")
            open(odt, "wb").write(b"PK\x03\x04 fake")
            f5, m5 = I.ingest([odt])
            check(m5[0]["status"] == "unreadable" and "soffice" in m5[0]["how"], "no soffice -> unreadable with a note")
        finally:
            I.shutil.which = real
        # S1
        probs = I.s1(man, files)
        check(any("logo.bin" in p for p in probs), f"S1 lists the unreadable file: {probs}")
        lone = os.path.join(tmp, "brief.md")
        open(lone, "wb").write(bytes(range(256)) * 8)       # a binary file passed directly as the brief
        f6, m6 = I.ingest([lone])
        check(not f6 and m6[0]["status"] == "unreadable" and I.s1(m6, f6), "a binary passed directly is unreadable, S1")
        # build: only an unreadable brief -> exit 2, S1, before any model call
        from builder.build import MockFreya, build
        called = []
        r = build([lone], os.path.join(ROOT, "tools", "openapi.json"), "s1", MockFreya(), os.path.join(tmp, "sub"),
                  os.path.join(tmp, "tr"), 2, 1500, lambda *a: called.append(1))
        ev = [json.loads(l) for l in open(r["trace"])]
        check(r["exit_code"] == 2 and r["signal"] == "S1" and not called, f"build with no readable source -> exit 2 S1: {r.get('fallback_reason')}")
        check(any(e["event"] == "sources" and e.get("manifest") for e in ev), "the manifest is in the trace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    sys.exit(1 if fails else 0)
