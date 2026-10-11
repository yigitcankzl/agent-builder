"""A question topic (robot, purpose) is answered exactly once in every event shape and phase, and the rest of the event
is still handled (e155c8c live, A talkative PUB-04: kind=topic;also=date;t=robot -> the robot question was dropped,
because the built policy had no robot line).

    python3 -m tests.test_question_answers
Shapes: kind=topic+also=X+t=Q, kind=X+also=topic+t=Q, kind=X+also=Q, kind=X+t=Q, and the partial forms. Phases:
opening, identity, third party, statement/offer, read-back, wrap-up. Policies: A, and A without a robot line (the
answer then falls back to the brief's own opening identity). The expected rest is the same event without the question.
"""
import copy, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = sys.argv[:1]
from builder.engine import reducer as R
from tests.test_partial_questions import POL, say, stages

REST = {"date": "rel=;d=23;m=10;wd=;wk=none;vague=no", "amount": "amt=50", "yes": "", "no": "", "other": ""}
fails = []


def answer(pol, q, st):
    if q == "purpose" and st.get("verified") != "yes" and not (R.event_row(pol, "purpose") or {}).get("say"):
        return R.caller_line(pol)
    return R.info_line(pol, copy.deepcopy(st), q)


def spoken(act):
    return act.get("text") if act.get("type") == "say_exact" else act.get("farewell") if act.get("type") == "close" else None


def shapes(q):
    for x, extra in REST.items():
        if x == "other":
            continue
        tail = (";" + extra) if extra else ""
        rest = "kind=%s;also=none;st=complete;prod=%s" % (x, tail)
        yield "kind=topic;also=%s;st=complete;prod=;t=%s%s" % (x, q, tail), rest
        yield "kind=%s;also=topic;st=complete;prod=;t=%s%s" % (x, q, tail), rest
        yield "kind=%s;also=%s;st=complete;prod=%s" % (x, q, tail), rest
        yield "kind=%s;also=none;st=complete;prod=;t=%s%s" % (x, q, tail), rest
    yield "kind=topic;also=none;st=partial;prod=;t=%s" % q, "kind=other;also=none;st=partial;prod="
    yield "kind=other;also=%s;st=partial;prod=" % q, "kind=other;also=none;st=partial;prod="
    yield "kind=date;also=topic;st=partial;prod=;t=%s;d=2" % q, "kind=date;also=none;st=partial;prod=;d=2"


def run(name, pol):
    n = 0
    for st in stages(pol):
        for q in ("robot", "purpose"):
            want = answer(pol, q, st)
            for body, rest in shapes(q):
                n += 1
                s1, act = say(pol, copy.deepcopy(st), body)
                s0, base = say(pol, copy.deepcopy(st), rest)
                text = spoken(act)
                where = "%s %s q=%s %s" % (name, st["phase"], st.get("q"), body)
                if not want:
                    fails.append("%s: no answer line for %s" % (where, q))
                    continue
                if "st=partial" in body:     # a cut-off turn with a question: the answer, then the continue line
                    ok = text == want + " " + R.sentence(pol, "continue_line", R.D_CONTINUE)
                elif text is None:     # a tool call: the answer waits for the next spoken line, once
                    ok = act.get("type") == base.get("type") and (s1.get("_info_next") or "").count(want) == 1
                else:
                    b = spoken(base) or ""
                    ok = text.count(want) == 1 + b.count(want) and text.startswith(want) and (
                        text == (want + " " + b).strip() or b.count(want) > 0 or base.get("type") != act.get("type"))
                    ok = ok and act.get("type") == base.get("type")
                if not ok:
                    fails.append("%s\n        got  %s\n        rest %s" % (where, act, base))
    return n


if __name__ == "__main__":
    a = POL["A"]
    no_robot = copy.deepcopy(a)
    for row in no_robot.get("events") or []:
        if row.get("topic") == "robot":
            row["say"] = ""
    total = run("A", a) + run("A-no-robot-line", no_robot)
    for f in fails[:25]:
        print("FAIL " + f)
    print("%d/%d question shapes answered exactly once with the rest handled" % (total - len(fails), total))
    sys.exit(1 if fails else 0)
