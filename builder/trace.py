"""Builder trace (required for submission): one jsonl event per line plus a plain-text summary next to it.
Secrets are stripped: the values of key-like environment variables and anything shaped like an API key."""
import json, os, re, sys, time

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


PROGRESS = ("start", "reproducibility", "sources", "extraction_run", "examiner_result", "core_missing", "core_agreement",
            "bridge", "validator", "workflow", "graph_walk", "save", "self_test", "signal", "fallback_started",
            "fallback_selection", "hub_import_failed", "end")


def _short(e):
    keep = ("run", "seconds", "agree", "passed", "errors", "signal", "level", "reason", "candidate", "exit_code", "nodes",
            "workflow_id", "scenarios", "failed", "patched", "unresolved", "disagreements", "error", "slot", "commit", "model")
    return " ".join(f"{k}={json.dumps(e[k], default=str)[:80]}" for k in keep if k in e and e[k] not in (None, [], {}))


class BuildTrace:
    def __init__(self, path, progress=True):
        self.path, self.t0, self.events, self.progress = path, time.time(), [], progress
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").close()

    def log(self, event, **kw):
        kw = {"event": event, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "t": round(time.time() - self.t0, 1), **kw}
        self.events.append(kw)
        with open(self.path, "a") as f:
            f.write(redact(json.dumps(kw, ensure_ascii=False, default=str)) + "\n")
        if self.progress and event in PROGRESS:      # progress on stderr: `2>&1 | tee` logs read well, stdout stays JSON
            print(redact(f"[build +{kw['t']}s] {event} {_short(kw)}"), file=sys.stderr, flush=True)

    def model_call(self, model, purpose, seconds, ok=True, **kw):  # same shape as policy_extract's Trace
        self.log("model_call", model=model, purpose=purpose, seconds=seconds, ok=ok, **kw)

    def summary(self, path):
        lines = []
        for e in self.events:                # the assumptions block first (FINAL-PLAN S8: NOT IMPLEMENTED at the top)
            if e["event"] == "assumptions":
                lines.append("== ASSUMPTIONS AND NOT IMPLEMENTED (read first) ==")
                for k, v in e.items():
                    if k in ("event", "at", "t") or not v:
                        continue
                    for item in (v if isinstance(v, list) else [v]):
                        lines.append(f"  {k}: " + json.dumps(item, ensure_ascii=False, default=str)[:400])
                lines.append("== EVENTS ==")
        for e in self.events:
            ev = e["event"]
            rest = {k: v for k, v in e.items() if k not in ("event", "at", "t")}
            lines.append(f"[{e['at']} +{e['t']}s] {ev}: " + json.dumps(rest, ensure_ascii=False, default=str)[:4000])
        open(path, "w").write(redact("\n".join(lines)) + "\n")
