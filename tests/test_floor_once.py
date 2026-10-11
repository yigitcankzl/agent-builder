"""Per product, the full floor offer (amount + 'The rest stays overdue.') is stated once (kit A PUB-06 check "minimum
payment offered once, with the note that the rest stays overdue"; live dc18dc2c/9d011e5d: four cut-off turns burnt an
attempt and the floor was offered again). A later legitimate attempt names only the new day. Random interleavings of
cut-offs, chatter, non-answers, ambiguous turns, questions, refusals and amounts after "too much".

    python3 -m tests.test_floor_once [n]
"""
import copy, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1500
sys.argv = sys.argv[:1]
from builder.engine import reducer as R
from tests.test_partial_questions import POL, NOW, CV
import itertools
TOK = itertools.count(1)


def say(pol, st, body):
    tok = "kq%05x" % next(TOK)
    st = dict(st, tok=tok)
    st, act = R.step(pol, st, R.parse_event("n=" + tok + ";src=user;" + body, st, R.CONTRACT_TOPICS), None, NOW, CV)
    st["last_tok"] = tok
    return st, act
import tests.test_reducer_sequences as S

EVENTS = ["kind=other;also=none;st=partial;prod=", "kind=other;also=none;st=complete;prod=",
          "kind=other;also=none;st=none;prod=", "kind=other;also=none;st=ambiguous;prod=",
          "kind=no;also=none;st=ambiguous;prod=", "kind=topic;also=none;st=partial;prod=;t=robot",
          "kind=topic;also=none;st=complete;prod=;t=purpose", "kind=no;also=none;st=partial;prod=",
          "kind=reject;also=none;st=complete;prod=;why=too_much", "kind=reject;also=none;st=complete;prod=;why=flat",
          "kind=no;also=none;st=complete;prod=", "kind=amount;also=none;st=complete;prod=;amt=100",
          "kind=date;also=none;st=partial;prod=;rel=;d=;m=;wd=fri;wk=none;vague=no"]
END = ["kind=date;also=accept;st=complete;prod=;rel=;d=;m=;wd=fri;wk=this;vague=no", "kind=yes;also=none;st=complete;prod="]


def floor_offer(pol, name):
    c = [c for c in S.FIX["cases"] if c["id"] == "PUB-06"][0]     # the A case; A+B speaks the same floor
    cv = c["call_variables"]
    st = R.init_state(pol, cv)
    for s in c["steps"][:7]:
        if s["source"] == "user":
            st["tok"] = s["event_fields"]["n"]
            st, a = R.step(pol, st, R.parse_event(s["event"], st, S.TOPICS), None, c["now"], cv)
            st["last_tok"] = st["tok"]
        else:
            st, a = R.step(pol, st, None, s["tool_event"], c["now"], cv)
    return st, a


def run():
    rnd, fails, n = random.Random(7), [], 0
    for name in ("A", "A+B"):
        pol = POL[name]
        st0, a0 = floor_offer(pol, name)
        assert R.D_OVERDUE in a0["text"] and "637.50" in a0["text"], a0
        for _ in range(N):
            st, said = copy.deepcopy(st0), [a0["text"]]
            evs = [rnd.choice(EVENTS) for _ in range(rnd.randint(1, 14))] + END[:rnd.randint(0, 2)]
            for body in evs:
                if st["phase"] == "closed":
                    break
                st, a = say(pol, st, body)
                said.append(a.get("text") or a.get("farewell") or "")
            n += 1
            full = [t for t in said if "Could you pay 637.50" in t]
            if sum(t.count(R.D_OVERDUE) for t in said) > 1 or len(full) > 1:
                fails.append("%s %s\n      %s" % (name, evs, "\n      ".join(said)))
            cut = [i for i, b in enumerate(evs) if "st=partial" in b and "kind=other" in b]
            for i in cut:     # a cut-off chat at an open offer never states an offer
                if i + 1 < len(said) and "Could you pay" in said[i + 1]:
                    fails.append("%s cut-off re-offered: %s -> %r" % (name, evs[:i + 1], said[i + 1]))
    return n, fails


if __name__ == "__main__":
    n, fails = run()
    for f in fails[:8]:
        print("FAIL " + f)
    print("%d/%d interleavings state the floor offer and its overdue clause once" % (n - len(fails), n))
    sys.exit(1 if fails else 0)
