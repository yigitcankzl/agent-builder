"""Trace audit (no build): an existing rehearsal trace re-rendered with the header, and key redaction.
    python3 tests/test_trace.py"""
import glob, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.trace import BuildTrace, redact

fails = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    cond or fails.append(msg)


src = sorted(glob.glob(os.path.join(ROOT, "tests", "generated", "rehearsal", "biz-1", "traces", "*.jsonl")))[-1]
d = tempfile.mkdtemp()
t = BuildTrace(os.path.join(d, "x.jsonl"), progress=False)
t.events = [json.loads(ln) for ln in open(src)]
t.summary(os.path.join(d, "x.txt"))
txt = open(os.path.join(d, "x.txt")).read()
print("\n".join(txt.splitlines()[:16]))
check(txt.startswith("== BUILD =="), "the header comes first")
for k in ("commit: ", "models: claude-", "command: python3 builder/build.py", "exit_code: 0"):
    check(k in txt, f"header has {k.strip()!r}")
for stage in ("extraction:", "examiner:", "bridge:", "validator: passed=True", "graph_walk:", "self_test:", "save:", "smoke:"):
    check("  " + stage in txt, f"pipeline lists {stage}")

fake = {"FREYA_API_KEY": "fak_" + "x" * 20, "MY_TEAM_TOKEN": "tok" + "y" * 20}
os.environ.update(fake)
line = redact(json.dumps({"a": fake["FREYA_API_KEY"], "b": fake["MY_TEAM_TOKEN"], "c": "ykz-" + "z" * 16,
                          "d": "Authorization: Bearer " + "q" * 30, "e": "sk-ant-" + "w" * 30}))
check(not any(v in line for v in list(fake.values()) + ["z" * 16, "q" * 30, "w" * 30]), f"keys redacted: {line}")
print("RESULT:", "PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
