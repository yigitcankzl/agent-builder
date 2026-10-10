"""Source ingestion: every brief input becomes text, with a manifest of what happened to each file (signal S1).

ingest(paths) -> (files {name: text}, manifest [{name, status, how, chars, sha1, note}])
  status: read (text as is) | converted (pdf, docx, html, xlsx, odt/doc/rtf via soffice) | unreadable | skipped
  - folders are walked; a .zip is extracted to a temp dir (no path traversal, size-capped) and walked;
  - text files are decoded strictly: UTF-8 (BOM ok), UTF-16 with a BOM, else cp1252 only if the result looks like
    text; a file that is binary (NUL bytes, mostly non-printable) is 'unreadable', never read as garbage;
  - .pdf via pdftotext; .docx via the stdlib (word/document.xml), .html via html.parser, .xlsx via openpyxl (stdlib
    zip fallback), other office files via soffice --convert-to txt when installed. No OCR: a PDF with no text layer is
    unreadable. A missing converter makes the file unreadable with a note; it never crashes.
s1(manifest, files) -> list of S1 problems (unreadable files, a converter that failed on a non-empty file, < 1500 chars).
"""
import hashlib, html.parser, io, os, re, shutil, subprocess, tempfile, zipfile

TEXT_EXT = (".md", ".txt", ".eml", ".csv", ".json", ".yaml", ".yml", ".tsv", ".markdown", ".text", ".msg", ".xml", ".ini", ".log")
MIN_CHARS = 1500
ZIP_MAX_BYTES = 50 * 1024 * 1024


def _sha(b):
    return hashlib.sha1(b).hexdigest()[:12]


def _looks_text(t):
    if not t:
        return True
    bad = sum(1 for c in t if (ord(c) < 32 and c not in "\n\r\t\f") or 0x7f <= ord(c) < 0xa0 or c == "�")
    return bad / len(t) < 0.02


def decode(b):
    """bytes -> (text, how) or (None, why). Strict: a binary file is never returned as text."""
    if b.count(b"\x00") and not (b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff")):
        return None, "binary (NUL bytes)"
    for enc, bom in (("utf-8-sig", b"\xef\xbb\xbf"), ("utf-16", b"\xff\xfe"), ("utf-16", b"\xfe\xff")):
        if b.startswith(bom):
            try:
                return b.decode(enc), enc
            except UnicodeDecodeError:
                pass
    try:
        t = b.decode("utf-8")
        return (t, "utf-8") if _looks_text(t) else (None, "binary (non-printable)")
    except UnicodeDecodeError:
        pass
    t = b.decode("cp1252", errors="replace")
    return (t, "cp1252") if _looks_text(t) else (None, "not UTF-8 and not text-like")


class _HTML(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, a):
        self.skip += tag in ("script", "style")
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        self.skip -= tag in ("script", "style") and self.skip > 0
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_text(t):
    p = _HTML()
    p.feed(t)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(p.out)).strip()


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        paras.append("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)))
    import html as _h
    return _h.unescape("\n".join(paras)).strip()


def xlsx_text(path):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append(f"# sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                if any(c is not None for c in row):
                    out.append(",".join("" if c is None else str(c) for c in row))
        return "\n".join(out), "openpyxl"
    except ImportError:
        pass
    with zipfile.ZipFile(path) as z:      # stdlib fallback: shared strings + inline values, sheet by sheet
        ss = re.findall(r"<si>.*?</si>", z.read("xl/sharedStrings.xml").decode("utf-8", "replace"), re.S) if "xl/sharedStrings.xml" in z.namelist() else []
        ss = ["".join(re.findall(r"<t[^>]*>(.*?)</t>", s, re.S)) for s in ss]
        out = []
        for n in sorted(x for x in z.namelist() if x.startswith("xl/worksheets/sheet")):
            out.append(f"# sheet: {n.split('/')[-1]}")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", z.read(n).decode("utf-8", "replace"), re.S):
                vals = []
                for attrs, v in re.findall(r"<c([^>]*)>(?:<f>.*?</f>)?(?:<v>(.*?)</v>)?", row, re.S):
                    vals.append(ss[int(v)] if 't="s"' in attrs and v.isdigit() and int(v) < len(ss) else v)
                out.append(",".join(vals))
        return "\n".join(out), "stdlib-xlsx"


def pdf_text(path):
    if not shutil.which("pdftotext"):
        return None, "pdftotext not installed"
    r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=60)
    t = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0:
        return None, "pdftotext failed: " + r.stderr.decode(errors="replace")[:120]
    if len(t.strip()) < 20:
        return None, "no text layer (scanned PDF; no OCR)"
    return t, "pdftotext"


def soffice_text(path):
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None, "soffice not installed"
    out = tempfile.mkdtemp()
    try:
        subprocess.run([exe, "--headless", "--convert-to", "txt:Text", "--outdir", out, path], capture_output=True, timeout=120)
        got = [f for f in os.listdir(out) if f.endswith(".txt")]
        if not got:
            return None, "soffice produced no text"
        t, how = decode(open(os.path.join(out, got[0]), "rb").read())
        return (t, "soffice") if t else (None, "soffice output " + how)
    except Exception as e:
        return None, f"soffice failed: {type(e).__name__}"
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _safe_extract(zpath, dest):
    with zipfile.ZipFile(zpath) as z:
        total = sum(i.file_size for i in z.infolist())
        if total > ZIP_MAX_BYTES:
            raise ValueError(f"zip too large ({total} bytes)")
        for i in z.infolist():
            target = os.path.realpath(os.path.join(dest, i.filename))
            if not target.startswith(os.path.realpath(dest) + os.sep) and target != os.path.realpath(dest):
                raise ValueError(f"unsafe path in zip: {i.filename}")
        z.extractall(dest)


def _one(path, name, files, manifest):
    raw = open(path, "rb").read()
    ext = os.path.splitext(name)[1].lower()
    rec = {"name": name, "bytes": len(raw), "sha1": _sha(raw)}
    text, how, status = None, "", "unreadable"
    try:
        if not raw.strip():
            text, how, status = "", "empty", "read"
        elif ext == ".pdf" or raw.startswith(b"%PDF"):
            text, how = pdf_text(path)
            status = "converted" if text else "unreadable"
        elif ext == ".docx" or (raw[:2] == b"PK" and ext in (".docm", ".dotx")):
            text, how, status = docx_text(path), "stdlib-docx", "converted"
        elif ext in (".xlsx", ".xlsm"):
            (text, how), status = xlsx_text(path), "converted"
        elif ext in (".html", ".htm"):
            t, how = decode(raw)
            text, status = (html_text(t), "converted") if t is not None else (None, "unreadable")
        elif ext in (".doc", ".odt", ".rtf", ".xls", ".ods", ".pptx", ".ppt"):
            text, how = soffice_text(path)
            status = "converted" if text else "unreadable"
        else:
            text, how = decode(raw)
            status = "read" if text is not None else "unreadable"
    except Exception as e:
        text, how, status = None, f"{type(e).__name__}: {str(e)[:120]}", "unreadable"
    rec.update(status=status, how=how, chars=len(text or ""))
    if text is not None:
        files[name] = text
    manifest.append(rec)


def ingest(paths):
    files, manifest = {}, []

    def walk_dir(d, base):
        for root, dirs, fs in os.walk(d):
            dirs.sort()
            for f in sorted(fs):
                if f.startswith("."):
                    continue
                full = os.path.join(root, f)
                name = os.path.relpath(full, base)
                if f.lower().endswith(".zip"):
                    do_zip(full, name)
                else:
                    _one(full, name, files, manifest)

    def do_zip(zpath, name):
        tmp = tempfile.mkdtemp(prefix="brief-zip-")
        try:
            _safe_extract(zpath, tmp)
            manifest.append({"name": name, "status": "expanded", "how": "zip", "chars": 0, "bytes": os.path.getsize(zpath),
                             "sha1": _sha(open(zpath, "rb").read())})
            before = len(manifest)
            walk_dir(tmp, tmp)
            for rec in manifest[before:]:     # names inside the zip are prefixed with the zip's name
                old = rec["name"]
                rec["name"] = name + "/" + old
                if old in files:
                    files[rec["name"]] = files.pop(old)
        except Exception as e:
            manifest.append({"name": name, "status": "unreadable", "how": f"zip: {type(e).__name__}: {str(e)[:100]}", "chars": 0})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    for p in paths:
        if os.path.isdir(p):
            walk_dir(p, os.path.dirname(p.rstrip("/")))
        elif p.lower().endswith(".zip"):
            do_zip(p, os.path.basename(p))
        elif os.path.exists(p):
            _one(p, os.path.basename(p), files, manifest)
        else:
            manifest.append({"name": os.path.basename(p), "status": "unreadable", "how": "file not found", "chars": 0})
    return files, manifest


def s1(manifest, files):
    """Signal S1 problems: unreadable sources, converters that failed on a non-empty file, too little text overall."""
    probs = [f"unreadable: {m['name']} ({m.get('how')})" for m in manifest if m["status"] == "unreadable"]
    total = sum(len(t) for t in files.values())
    if total < MIN_CHARS:
        probs.append(f"only {total} characters of readable text (< {MIN_CHARS})")
    return probs
