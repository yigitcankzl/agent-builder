"""Builder trace (required for submission): one jsonl event per line plus a plain-text summary next to it.
Secrets are stripped: the values of key-like environment variables and anything shaped like an API key."""
import json, os, re, sys, time

SECRET_ENV = ("FREYA_API_KEY", "FREYA_BANK_TEAM_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")
KEY_SHAPES = (r"fak_[A-Za-z0-9_\-]{8,}", r"sk-[A-Za-z0-9_\-]{16,}", r"ykz-[A-Za-z0-9_\-]{8,}",
              r"Bearer\s+[A-Za-z0-9._\-]{12,}", r"(?i)(?<=authorization: )[A-Za-z0-9._\-]{16,}")
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)


def redact(text):
    for k in sorted(set(SECRET_ENV) | {k for k in os.environ if _SECRET_NAME.search(k)}):
        v = os.environ.get(k)
        if v and len(v) >= 8:
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

    def header(self):
        """The reviewer's first screen: what ran (commit, models, command), how it ended (exit code, signal) and every
        pipeline stage with its status and seconds (each stage's time since the previous stage)."""
        first = lambda ev: next((e for e in self.events if e["event"] == ev), None)
        every = lambda ev: [e for e in self.events if e["event"] == ev]
        rep, end = first("reproducibility") or {}, first("end") or {}
        res = end.get("result") or {}
        models = sorted({m for m in [rep.get("model")] + [e.get("model") for e in every("model_call")] if m})
        sig = [e for e in every("signal") if e.get("level") != "warning"]
        lines = ["== BUILD ==",
                 f"  commit: {rep.get('commit')} branch={rep.get('branch')} dirty={rep.get('dirty')}"
                 + (f" dirty_files={rep.get('dirty_files')}" if rep.get("dirty") else ""),
                 f"  models: {', '.join(models) or 'none'}",
                 "  command: python3 builder/build.py " + " ".join(str(a) for a in rep.get("argv") or []),
                 f"  exit_code: {res.get('exit_code')} signal: {sig[-1].get('signal') if sig else None}"
                 f" fallback_used: {res.get('fallback_used')} seconds: {end.get('seconds')}"
                 + (f" warning: {res.get('warning')}" if res.get("warning") else ""),
                 "== PIPELINE (stage: status, seconds) =="]
        ext = every("extraction_run")
        ca = first("core_agreement") or {}
        val, st, gw = every("validator"), first("self_test"), first("graph_walk")
        br = every("bridge")
        stages = [
            ("extraction", ext, (f"{len(ext)} run(s), core agree={ca.get('agree')}" + (" schema errors" if any(e.get("schema_errors") for e in ext) else ""))
             if ext else "not run"),
            ("examiner", every("examiner_result"), (lambda e: f"disagreements={e[-1].get('disagreements')} patched={e[-1].get('patched')}" if e else "not run")(every("examiner_result"))),
            ("bridge", br, f"{len(br)} attempt(s), {sum('ASSUMPTION' in str(n) for e in br for n in e.get('notes') or [])} ASSUMPTION note(s) (listed above), api_mismatch={len((br[-1].get('api_mismatch') or []) if br else [])}" if br else "not run"),
            ("validator", val, (f"passed={val[-1].get('passed')} errors={len(val[-1].get('errors') or [])}" if val else "not run")),
            ("graph_walk", [gw] if gw else [], (f"errors={len(gw.get('errors') or [])}" if gw and gw.get("run") else "not run")),
            ("self_test", [st] if st else [], (f"{st.get('passed')}/{st.get('scenarios')} passed" if st and st.get("run") else "not run")),
            ("save", every("save"), "; ".join(f"{e.get('candidate')}: " + ("skipped (" + str(e.get("note")) + ")" if e.get("skipped") else f"workflow_id={e.get('workflow_id')}")
                                               for e in every("save")) or "not run"),
            ("smoke", every("smoke"), "; ".join(f"{e.get('candidate')}: " + ("off" if e.get("run") is False else "ok" if e.get("ok") else "skipped" if e.get("skipped") else "S7")
                                                + (f" ({e.get('reason')})" if e.get("reason") else "") for e in every("smoke")) or "not run"),
        ]
        prev = 0.0
        timed = [(max((e["t"] for e in evs), default=None), name, status) for name, evs, status in stages]
        for t, name, status in sorted(timed, key=lambda x: (x[0] is None, x[0] or 0)):     # in the order they ran
            lines.append(f"  {name}: {status}" + (f" [{round(t - prev, 1)} s, at +{t} s]" if t is not None else ""))
            prev = t if t is not None else prev
        return lines

    def summary(self, path):
        lines = self.header()
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
