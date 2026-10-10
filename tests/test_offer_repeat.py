"""fix-offers: an offer the customer heard is never offered again (live retest56b / retest05x2 / retest06x2 failures).
Replays the PUB-05 / PUB-06 public sequences up to the offer, then the live turns.
    python3 tests/test_offer_repeat.py"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import FIX, POL, TOPICS

CASES = {c["id"]: c for c in FIX["cases"]}


def upto(cid, n):
    c = CASES[cid]
    pol, cv = POL[c["policy"]], c["call_variables"]
    st = R.init_state(pol, cv)
    for s in c["steps"][:n]:
        if s["source"] == "user":
            st["tok"] = s["event_fields"]["n"]
            st, act = R.step(pol, st, R.parse_event(s["event"], st, TOPICS), None, c["now"], cv)
            st["last_tok"] = st["tok"]
        else:
            st, act = R.step(pol, st, None, dict(s["tool_event"]), c["now"], cv)
    return pol, st, act, c


def say(ctx, body, tok):
    pol, st, act, c = ctx
    st["tok"] = tok
    ev = R.parse_event(f"n={tok};src=user;st=complete;prod=;also=none;" + body, st, TOPICS)
    st, act = R.step(pol, st, ev, None, c["now"], c["call_variables"])
    st["last_tok"] = tok
    return (pol, st, act, c)


def text(ctx):
    a = ctx[2]
    return a.get("text") or a.get("farewell") or a.get("hint") or ""


if __name__ == "__main__":
    bad = []

    def check(name, ok, got):
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  got {got}"))
        bad.extend([] if ok else [name])

    # PUB-05 live: hardship (also=terms) -> support offer; "no, a discount?" (t=terms) -> no re-offer, hardship close
    ctx = upto("PUB-05", 6)
    ctx = say(ctx, "kind=topic;t=hardship", "kaaaaa")
    check("05 support offered", "customer support" in text(ctx), text(ctx))
    ctx = say(ctx, "kind=topic;t=terms", "kbaaaa")
    a = ctx[2]
    check("05 terms after offer closes no_promise/hardship", a["type"] == "close" and (a["outcome"], a["reason"]) == ("no_promise", "hardship"), a)
    check("05 no re-offer, no other terms said", "customer support" not in text(ctx) and "no other terms" in text(ctx), text(ctx))

    # PUB-05 variant: purpose / second hardship after the offer also never re-offer
    for body in ("kind=topic;t=purpose", "kind=topic;t=hardship"):
        ctx = say(say(upto("PUB-05", 6), "kind=topic;t=hardship", "kaaaaa"), body, "kcaaaa")
        check("05 " + body + " -> close", ctx[2]["type"] == "close" and "customer support" not in text(ctx), ctx[2])

    # PUB-06 live: too much -> floor offer; "You tell me." (t=purpose) -> only the day, no amount or date
    for body in ("kind=topic;t=purpose", "kind=topic;t=decline", "kind=topic;t=terms", "kind=other"):
        ctx = upto("PUB-06", 7)
        offer = text(ctx)
        att = ctx[1]["products"][0]["attempts"]
        ctx = say(ctx, body, "kdaaaa")
        t = text(ctx)
        check("06 " + body + " no re-proposal", not re.search(R.AMT, t) and "October" not in t and "Could you" not in t and t.strip() != offer, t)
        check("06 " + body + " attempts unchanged", ctx[1]["products"][0]["attempts"] == att, ctx[1]["products"][0])
        ctx = say(ctx, "kind=date;rel=;d=;m=;wd=fri;wk=this;vague=no", "keaaaa")
        check("06 " + body + " then Friday -> read-back 637.50 16 October", "637.50" in text(ctx) and "16 October" in text(ctx), text(ctx))

    print("PASS" if not bad else f"FAIL {len(bad)}")
    sys.exit(1 if bad else 0)
