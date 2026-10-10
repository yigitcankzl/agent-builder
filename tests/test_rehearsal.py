"""Offline replay of Cursor's rehearsal briefs (fixtures-briefs: nightmare-1 496a942, raw-2 0d0345c, biz-1 a381750)
through step() with Fork 4's extracted policies, compared with each case's expected ledger.

    python3 tests/test_rehearsal.py [brief ...]
Customer turns are scripted as ev events from each case's script (the persona's answers to the agent's expected
offers); a fake bank answers from the case's identity and products. Policies: tests/generated/rehearsal/<brief>.
reducer_policy.json (or the first *.policy.json in tests/generated/rehearsal/<brief>/); a missing policy is skipped.
"""
import glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R

W = "kind=who;also=none;st=complete;prod=;who=self;party="
NO = "kind=no;also=none;st=complete;prod="
FLAT = "kind=reject;also=none;st=complete;prod=;why=flat"
TOO = "kind=reject;also=none;st=complete;prod=;why=too_much"
YES = "kind=yes;also=none;st=complete;prod="
OTHER = "kind=other;also=none;st=none;prod="
DOB = lambda c: "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=%s;y=%s" % (c["identity"]["date_of_birth"], c["identity"]["date_of_birth"][:4])
PH = lambda c: "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=%s" % c["identity"]["phone_last4"]
DT = lambda d, m, prod="", also="none": "kind=date;also=%s;st=complete;prod=%s;rel=;d=%s;m=%s;wd=;wk=none;vague=no" % (also, prod, d, m)
REL = lambda rel, prod="", also="none": "kind=date;also=%s;st=complete;prod=%s;rel=%s;d=;m=;wd=;wk=none;vague=no" % (also, prod, rel)
WD = lambda wd, prod="", also="none": "kind=date;also=%s;st=complete;prod=%s;rel=;d=;m=;wd=%s;wk=none;vague=no" % (also, prod, wd)
DA = lambda d, m, amt: "kind=date_amount;also=none;st=complete;prod=;rel=;d=%s;m=%s;wd=;wk=none;vague=no;amt=%s" % (d, m, amt)
AMT = lambda amt, st="complete": "kind=amount;also=none;st=%s;prod=;amt=%s" % (st, amt)
CB = lambda tm, rel="tomorrow": "kind=callback;also=none;st=complete;prod=;rel=%s;d=;m=;wd=;wk=none;vague=no;tm=%s" % (rel, tm)
TOPIC = lambda t: "kind=topic;also=none;st=complete;prod=;t=%s" % t
OTHER_PERSON = lambda party="relative": "kind=who;also=none;st=complete;prod=;who=other;party=%s" % party

V = lambda c: [W, DOB(c), PH(c)]                       # verified
G = lambda c: [W, YES, DOB(c), PH(c)]                  # biz-1: named contact, then 'Are you authorised?' yes

SCRIPTS = {
    "nightmare-1": {
        "PUB-01": lambda c: V(c) + [NO, FLAT, DA(19, 10, 420), YES],   # the note question: no + 420 on Monday 19
        "PUB-06": lambda c: V(c) + [TOO, YES, YES],                    # 50 percent 1062.55 on Thursday 15
        "PUB-04": lambda c: V(c) + [DT(6, 11, also="reject"), YES, YES],
        "PUB-10": lambda c: V(c) + [WD("fri", also="reject"), YES, YES],
        "PUB-07": lambda c: [W, CB("15:00")],                          # callback before identity
        "PUB-09": lambda c: [W, TOPIC("complaint")],
        "PUB-02": lambda c: [OTHER_PERSON(), CB("19:00"), NO],
    },
    "biz-1": {
        "PUB-01": lambda c: G(c) + [NO, YES, YES],
        "PUB-02": lambda c: [OTHER_PERSON(""), CB("10:00")],          # the receptionist
        "PUB-04": lambda c: G(c) + [DT(6, 11, also="reject"), YES, YES],
        "PUB-06": lambda c: G(c) + [TOO, YES, YES],
        "PUB-07": lambda c: G(c) + [DT(26, 10, also="reject"), YES, YES],
        "PUB-10": lambda c: G(c) + [WD("fri", also="reject"), YES, YES],
    },
    "raw-2": {
        "PUB-11": lambda c: V(c) + [DT(19, 10, "all", "reject"), YES, YES],
        "PUB-12": lambda c: V(c) + [REL("tomorrow", "1"), TOO, YES, FLAT, YES],
        "PUB-13": lambda c: V(c) + [DT(30, 10, "all", "reject"), YES, YES],
        "PUB-04": lambda c: V(c) + [DT(6, 11, also="reject"), YES, YES],
        "PUB-06": lambda c: V(c) + [TOO, YES, YES],
        "PUB-07": lambda c: V(c) + [DT(26, 10, also="reject"), YES, YES],
    },
}
DOB_SPLIT = lambda c: ["kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=;d=%d;m=%d" % (
    int(c["identity"]["date_of_birth"][8:]), int(c["identity"]["date_of_birth"][5:7])),
    "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=;y=%s" % c["identity"]["date_of_birth"][:4]]
SCRIPTS["clean-1"] = {}      # the main clean-1 cases run on the platform; the surface live failures are replayed here
SURFACE = {   # the surface siblings: the same events, with the turn the style changes
    ("clean-1", "PUB-06"): lambda c: [W] + DOB_SPLIT(c) + [PH(c), TOO, YES, YES],      # live e6d1cc28: DOB over two turns
    ("clean-1", "PUB-07"): lambda c: [W, DOB(c)] + [OTHER] * 4 + [PH(c), NO, YES, YES],  # live d34d93ed: chatter at the phone question
    ("raw-2", "PUB-11"): lambda c: V(c) + [WD("mon", "all", "reject"), YES, YES],
    ("raw-2", "PUB-06"): lambda c: V(c) + [TOO, AMT("", "partial"), AMT("637.53"), YES, YES],
}
SKIP = {("biz-1", "PUB-03")}     # debatable (coordinator)
PFILE = (("clean-1", "rh-clean-1"),)


def policy_for(brief):
    f = os.path.join(ROOT, "tests/generated/rehearsal/%s.reducer_policy.json" % dict(PFILE).get(brief, brief))
    if os.path.exists(f):
        return json.load(open(f))
    g = sorted(glob.glob(os.path.join(ROOT, "tests/generated/rehearsal/%s/*policy.json" % brief)))
    return json.load(open(g[0])) if g else None


def run_case(pol, c, events):
    now = c["variables"]["now"]
    cv = dict(c["variables"], customer_id="c_" + c["id"].lower())
    idt = c["identity"]
    rows = []
    for i, p in enumerate(c["products"], 1):
        rows.append(dict(dict((k, v) for k, v in p.items()), product_id="p%d" % i))
    wrong = [0]
    passed = set()
    ledger = dict(outcome=None, reason=None, promises=[], notes=[], callbacks=[], transfers=[])
    said = []
    st = R.init_state(pol, cv)
    n = [0]

    def bank(tool, args):
        if tool == "verify_identity":
            f = args.get("field")
            ok = str(args.get("answer")) == str(idt.get(f))
            if ok:
                passed.add(f)
            else:
                wrong[0] += 1
            return dict(verified=ok, all_verified=set(idt) <= passed, wrong_answers_left=max(0, 3 - wrong[0]))
        if tool == "get_account":
            return dict(products=rows)
        if tool == "create_promise":
            ledger["promises"].append(dict(product_id=args.get("product_id"), amount=round(float(args.get("amount")), 2), date=args.get("date")))
        if tool == "add_note":
            ledger["notes"].append(dict(product_id=args.get("product_id"), reason=args.get("reason")))
        if tool == "schedule_callback":
            ledger["callbacks"].append(dict(date=args.get("date"), time=args.get("time")))
        if tool == "transfer_to_agent":
            ledger["transfers"].append(dict(queue=args.get("queue")))
        return dict(ok=True)

    def settle(act):
        while act.get("type") == "call_tool":
            p = st_[0]["pending"]
            data = bank(act["tool"], act.get("args") or dict())
            te = dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"], status_code=200, ok="true", data=data)
            st_[0], act = R.step(pol, st_[0], None, te, now, cv)
            said.append(act)
        return act

    st_ = [st]
    for body in events:
        if st_[0]["phase"] == "closed":
            break
        n[0] += 1
        tok = "kr" + "abcdefghjk"[n[0] % 10] * 2 + "abcdefghjk"[(n[0] // 10) % 10] * 2
        st_[0]["tok"] = tok
        e = R.parse_event("n=" + tok + ";src=user;" + body, st_[0], R.CONTRACT_TOPICS)
        st_[0], act = R.step(pol, st_[0], e, None, now, cv)
        st_[0]["last_tok"] = tok
        said.append(act)
        act = settle(act)
        if act.get("type") == "close":
            ledger["outcome"], ledger["reason"] = act.get("outcome"), act.get("reason")
    return ledger, said, st_[0]


def diff(exp, got):
    out = []
    for k in ("outcome", "reason"):
        if exp.get(k) != got.get(k):
            out.append("%s %r != %r" % (k, got.get(k), exp.get(k)))
    for k in ("promises", "notes", "callbacks", "transfers"):
        e = sorted(json.dumps(x, sort_keys=True) for x in exp.get(k) or [])
        g = sorted(json.dumps(x, sort_keys=True) for x in got.get(k) or [])
        if e != g:
            out.append("%s %s != %s" % (k, g, e))
    return out


def lines(said):
    return [(a.get("text") or a.get("farewell") or ("%s %s" % (a.get("tool"), a.get("args")))) for a in said]


if __name__ == "__main__":
    briefs = [a for a in sys.argv[1:] if a in SCRIPTS] or list(SCRIPTS)
    verbose = "-v" in sys.argv
    total = ok = 0
    for b in briefs:
        pol = policy_for(b)
        if pol is None:
            print("== %s: no policy yet (tests/generated/rehearsal/%s...)" % (b, b))
            continue
        print("== %s   vocab log: %s" % (b, R.vocab(pol)["log"]))
        for fname, scripts in (("cases.json", SCRIPTS[b]), ("cases-surface.json", None)):
            d = json.load(open(os.path.join(ROOT, "tests/fixtures/rehearsal/%s/%s" % (b, fname))))
            for c in (d if isinstance(d, list) else d["cases"]):
                if (b, c["id"]) in SKIP:
                    continue
                fn = (SURFACE.get((b, c["id"])) if fname == "cases-surface.json" else None) or SCRIPTS[b].get(c["id"])
                if fn is None:
                    continue
                ledger, said, st = run_case(pol, c, fn(c) + [OTHER, OTHER])   # 'Thank you' after the last line
                probs = diff(c["expected"], ledger)
                total += 1
                ok += not probs
                tag = c["id"] + ("s" if fname == "cases-surface.json" else "")
                print(("PASS " if not probs else "FAIL ") + "%-7s %s" % (tag, c["title"][:60]))
                for p in probs:
                    print("        " + p[:240])
                if probs or verbose:
                    for l in lines(said):
                        print("          > " + str(l)[:200])
    print("%d/%d rehearsal cases match the expected ledger" % (ok, total))
