"""Offline unit test of the final runner's payload shape (no Freya call, no network).
    python3 tests/final_runner/test_payload.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_final as R  # noqa: E402

STYLES = {"pieces": "STIL: parça parça konuş."}
CASE = {"id": "T-01", "customerNumber": "12345678", "now": "2026-10-12T10:30:00+03:00", "title": "test",
        "script": "Borcunu öğrenmek istiyorsun. Teklif ne olursa reddet.", "checks": ["selam verildi"]}


def write(cases):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(cases, f, ensure_ascii=False)
    f.close()
    return f.name


def expect_error(fn, needle):
    try:
        fn()
    except ValueError as e:
        assert needle in str(e), f"wrong error: {e}"
        return
    raise AssertionError(f"no error for {needle}")


def test_persona_has_turkish_rule_and_script():
    p = R.persona_for(CASE, None, STYLES)
    assert "Türkçe konuş" in p["prompt"]
    assert "Borcunu öğrenmek istiyorsun" in p["prompt"]
    assert "STIL" not in p["prompt"]
    assert "selam verildi" in p["successCriteria"]


def test_style_is_applied_once():
    p = R.persona_for(CASE, "pieces", STYLES)
    assert p["prompt"].count("STIL: parça parça konuş.") == 1
    assert p["name"].endswith("[pieces]")


def test_unknown_style_rejected():
    expect_error(lambda: R.persona_for(CASE, "nope", STYLES), "unknown style")


def test_payload_shape():
    pids = {"T-01": "persona-1"}
    body = R.simulation_payload("agent-x", "final test", pids, [CASE], concurrency=5)
    assert body["agentId"] == "agent-x" and body["mode"] == "chat"
    assert body["selectedPersonaIds"] == ["persona-1"]
    assert body["customerVariablesMap"] == {"persona-1": {"customerNumber": "12345678", "now": "2026-10-12T10:30:00+03:00"}}
    assert body["maxConcurrentCalls"] == 5 and body["runsPerPersona"] == 1
    for k in ("assistantLlmOverride", "routingLlmOverride", "extractionLlmOverride", "personaLlmOverride", "analysisLlmOverride"):
        assert k in body


def test_load_validates_fields():
    ok = R.load_cases(write([CASE]))
    assert [c["id"] for c in ok] == ["T-01"]
    expect_error(lambda: R.load_cases(write([dict(CASE, customerNumber="123")])), "8 digits")
    expect_error(lambda: R.load_cases(write([dict(CASE, now="2026-10-12T10:30:00+02:00")])), "+03:00")
    expect_error(lambda: R.load_cases(write([dict(CASE, checks=[])])), "no checks")
    expect_error(lambda: R.load_cases(write([CASE, dict(CASE)])), "duplicate")
    expect_error(lambda: R.load_cases(write([dict(CASE, surprise=1)])), "unknown keys")


def test_unchecked_needs_flag():
    unchecked = dict(CASE, checks=[], unchecked=True)
    expect_error(lambda: R.load_cases(write([unchecked])), "no checks")
    assert R.load_cases(write([unchecked]), allow_unchecked=True)


def test_dry_run_prints_payload_without_calls():
    path = write([CASE])
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = R.main(["agent-x", "--cases", path, "--dry-run", "--style", "pieces"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["simulation"]["customerVariablesMap"]
    assert "HOW YOU TALK" in out["personas"][0]["prompt"]  # the kit pieces paragraph
    assert out["personas"][0]["name"].endswith("[pieces]")


def test_side_effect_check():
    ok, _ = R.check_expect({"expect": {"mock": {"week": 3}}}, {"week": 3})
    assert ok is True
    bad, note = R.check_expect({"expect": {"mock": {"week": 3}}}, {"week": 2})
    assert bad is False and "week" in note
    none, note = R.check_expect({"expect": {"mock": {"week": 3}}}, None)
    assert none is None and "not checked" in note


def test_shadow_converter_marks_unchecked_and_keeps_turns():
    import convert_shadow as C
    rendered = {"rendered": [{"id": "p1", "name": "Test persona", "turns": ["Merhaba.", "Evet."]}], "skipped": []}
    cases = C.convert(rendered, {"customerNumber": "12345678", "now": "2026-10-12T10:30:00+03:00"})
    assert cases[0]["unchecked"] is True and cases[0]["checks"] == []
    assert "1. Merhaba." in cases[0]["script"] and "2. Evet." in cases[0]["script"]
    checked = C.convert(rendered, {"customerNumber": "12345678", "now": "2026-10-12T10:30:00+03:00", "checks": ["x"]})
    assert "unchecked" not in checked[0] and checked[0]["checks"] == ["x"]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")
