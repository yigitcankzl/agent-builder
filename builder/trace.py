"""Builder trace (required for submission): one jsonl event per line plus a plain-text summary next to it.
Secrets are stripped: the values of key-like environment variables and anything shaped like an API key."""
import json, os, re, time

SECRET_ENV = ("FREYA_API_KEY", "FREYA_BANK_TEAM_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")
KEY_SHAPES = (r"fak_[A-Za-z0-9_\-]{8,}", r"sk-[A-Za-z0-9_\-]{16,}", r"Bearer\s+[A-Za-z0-9._\-]{12,}")


def redact(text):
    for k in SECRET_ENV:
        v = os.environ.get(k)
        if v and len(v) >= 6:
            text = text.replace(v, f"<{k}>")
    for pat in KEY_SHAPES:
        text = re.sub(pat, "<redacted>", text)
    return text


class BuildTrace:
    def __init__(self, path):
        self.path, self.t0, self.events = path, time.time(), []
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").close()

    def log(self, event, **kw):
        kw = {"event": event, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "t": round(time.time() - self.t0, 1), **kw}
        self.events.append(kw)
        with open(self.path, "a") as f:
            f.write(redact(json.dumps(kw, ensure_ascii=False, default=str)) + "\n")

    def model_call(self, model, purpose, seconds, ok=True, **kw):  # same shape as policy_extract's Trace
        self.log("model_call", model=model, purpose=purpose, seconds=seconds, ok=ok, **kw)

    def summary(self, path):
        lines = []
        for e in self.events:
            ev = e["event"]
            rest = {k: v for k, v in e.items() if k not in ("event", "at", "t")}
            lines.append(f"[{e['at']} +{e['t']}s] {ev}: " + json.dumps(rest, ensure_ascii=False, default=str)[:4000])
        open(path, "w").write(redact("\n".join(lines)) + "\n")
