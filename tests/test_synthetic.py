"""Codex's synthetic briefs (branch codex-gen, tests/gen/sample) replayed through step() with the policies our builder
extracted, compared with the independent oracle's ledgers (tests/gen/oracle.py, which imports no builder code).

    python3 tests/test_synthetic.py [gen-001 ...] [-v]
Policies: tests/generated/synthetic/<brief>.reducer_policy.json (SYNTH_POLICY_DIR overrides). Skipped when the
codex-gen files or a policy are absent. The customer is a small reactive persona driven by each case's declarative
`intent` (the oracle's own input), answering the agent's open question each turn, so no script is hand-written.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R

GEN = os.path.join(ROOT, "tests", "gen")
PDIR = os.path.join(ROOT, os.environ.get("SYNTH_POLICY_DIR", "tests/generated/synthetic"))


def ev_date(iso, also="none", prod=""):
    y, m, d = iso.split("-")
    return "kind=date;also=%s;st=complete;prod=%s;rel=;d=%d;m=%d;wd=;wk=none;vague=no" % (also, prod, int(d), int(m))


class Persona:
    """The customer of one case: answers the open question from the case's intent."""

    def __init__(self, case, policy):
        self.c, self.p = case, policy
        self.intent = case.get("intent") or dict(kind="pay_today")
        self.id_wrong = 0
        self.refusals = 0
        self.declines = 0
        self.cb_asked = 0

    def product_intent(self, st):
        i = st.get("cur")
        bp = self.intent.get("by_product") or dict()
        if i is not None and st.get("products"):
            return bp.get(st["products"][i]["id"], self.intent if not bp else dict(kind="refuse", count=99))
        return self.intent

    def say(self, st):
        q, ph, k = st.get("q") or "none", st.get("phase"), self.intent.get("kind")
        if ph == "opening" and q == "gate":
            return "kind=yes;also=none;st=complete;prod="
        if ph == "opening":
            if k == "third_party":
                return "kind=who;also=none;st=complete;prod=;who=other;party=relative"
            if k in ("wrong_number", "deceased"):
                return "kind=who;also=none;st=complete;prod=;who=other;party=%s" % k
            return "kind=who;also=none;st=complete;prod=;who=self;party="
        if ph == "third_party" or q == "callback_time":
            if self.cb_asked:
                return "kind=no;also=none;st=complete;prod="
            self.cb_asked += 1
            d = self.intent.get("callback_date", self.c["variables"]["now"][:10])
            y, m, dd = d.split("-")
            return "kind=callback;also=none;st=complete;prod=;rel=;d=%d;m=%d;wd=;wk=none;vague=no;tm=%s" % (
                int(dd), int(m), self.intent.get("callback_time", "12:00"))
        if str(q).startswith("id_"):
            f = q[3:]
            if "name" in f:              # a full-name confirmation step (gen-008)
                v = self.c["variables"]
                return "kind=identity;also=none;st=complete;prod=;field=%s;ans=%s %s" % (f, v.get("first_name", ""), v.get("last_name", ""))
            if k == "identity_decline":
                return "kind=topic;also=none;st=complete;prod=;t=decline"
            if k == "identity_fail":
                ans = "1900-01-01" if "birth" in f else "0000"
                return "kind=identity;also=none;st=complete;prod=;field=%s;ans=%s%s" % (f, ans, ";y=1900" if "birth" in f else "")
            a = self.c["identity"].get(f, "")
            return "kind=identity;also=none;st=complete;prod=;field=%s;ans=%s%s" % (f, a, (";y=" + a[:4]) if "birth" in f else "")
        if q == "help_first":
            return "kind=topic;also=none;st=complete;prod=;t=human"
        if q == "support_offer":
            return "kind=yes;also=none;st=complete;prod=" if self.product_intent(st).get("accept_transfer") else "kind=no;also=none;st=complete;prod="
        if q in ("readback", "confirm_np"):
            return "kind=yes;also=none;st=complete;prod="
        pi = self.product_intent(st)
        pk = pi.get("kind")
        prod = str(st["cur"] + 1) if st.get("cur") is not None and len(st.get("products") or []) > 1 else ""
        if pk in ("dispute", "paid", "hardship", "restructure", "human"):
            return "kind=topic;also=none;st=complete;prod=%s;t=%s" % (prod, pk)
        today = self.c["variables"]["now"][:10]
        offer = st.get("offer") or dict()
        if q == "pay_today" and st.get("cur") is None and len(st.get("products") or []) > 1:
            bp = self.intent.get("by_product") or dict()
            if not bp and pk == "pay_today":
                return "kind=yes;also=none;st=complete;prod="
            if not bp and pk == "name_date":
                return ev_date(pi["date"], "reject", "all")
            return "kind=no;also=none;st=complete;prod="
        if pk == "pay_today":
            if q == "pay_today":
                return "kind=yes;also=none;st=complete;prod="
            i = st["cur"] if st.get("cur") is not None else 0
            return "kind=date_amount;also=accept;st=complete;prod=%s;rel=today;d=;m=;wd=;wk=none;vague=no;amt=%s" % (
                prod, st["_pd"][i]["past_due"])          # the full amount today
        if pk == "name_date":
            if q in ("pay_today", "exact_day") or not offer:
                if pi.get("amount"):
                    y, m, d = pi["date"].split("-")
                    return "kind=date_amount;also=none;st=complete;prod=%s;rel=;d=%d;m=%d;wd=;wk=none;vague=no;amt=%s" % (
                        prod, int(d), int(m), pi["amount"])
                return ev_date(pi["date"], "reject", prod)
            return "kind=yes;also=none;st=complete;prod=" if pi.get("accept_adjustment", True) else "kind=reject;also=none;st=complete;prod=%s;why=flat" % prod
        if pk == "too_much":
            if q == "pay_today" or offer.get("kind") in ("full", "attempt_n") and abs(float(offer.get("amount") or 0) - self.floor(st)) > 0.005:
                return "kind=reject;also=none;st=complete;prod=%s;why=too_much" % prod
            want = pi.get("date", today)
            if offer.get("date") == want or not pi.get("date"):
                return "kind=yes;also=none;st=complete;prod="
            if not pi.get("_named"):
                pi["_named"] = True
                return ev_date(want, "accept", prod)
            return "kind=yes;also=none;st=complete;prod="
        if pk == "refuse":
            if q == "pay_today":
                return "kind=no;also=none;st=complete;prod="
            if offer.get("kind") == "attempt_n":
                i = st["cur"]
                if st["products"][i]["attempts"] - 1 < int(pi.get("count", 99)):
                    return "kind=reject;also=none;st=complete;prod=%s;why=flat" % prod
            return "kind=yes;also=none;st=complete;prod="
        return "kind=other;also=none;st=none;prod="

    def floor(self, st):
        i = st.get("cur") or 0
        return st["_pd"][i]["floor"] if st.get("_pd") else 0.0


def run_case(pol, case, oas=None):
    now = case["variables"]["now"]
    cv = dict(case["variables"], customer_id="c_" + case["id"].lower())
    rows = [dict(p, product_id=p.get("product_id", "p%d" % i)) for i, p in enumerate(case["products"], 1)]
    idt = case["identity"]
    wrong = [0]
    passed = set()
    ledger = dict(outcome=None, reason=None, promises=[], notes=[], callbacks=[], transfers=[])
    said = []

    rev = dict((t, dict((v, k) for k, v in (m or dict()).items())) for t, m in (pol.get("tool_args") or dict()).items())
    tools = set(p.strip("/").split("/")[-1] for p in (oas or dict()).get("paths", dict())) if oas else None

    def bank(tool, args):
        if tools is not None and tool not in tools:
            ledger.setdefault("errors", []).append("called a tool the OAS does not have: " + tool)
            return dict(ok=False)
        args = dict((rev.get(tool, dict()).get(k, k), v) for k, v in (args or dict()).items())   # OAS names -> roles
        if tool == "verify_identity":
            f = args.get("field")
            if "name" in str(f):
                v = case["variables"]
                ok = str(args.get("answer")).strip().lower() == ("%s %s" % (v.get("first_name"), v.get("last_name"))).lower()
                return dict(verified=ok, all_verified=False, wrong_answers_left=max(0, 3 - wrong[0]))
            ok = str(args.get("answer")) == str(idt.get(f))
            (passed.add(args.get("field")) if ok else wrong.__setitem__(0, wrong[0] + 1))
            return dict(verified=ok, all_verified=set(idt) <= passed, wrong_answers_left=max(0, 3 - wrong[0]))
        if tool == "get_account":
            return dict(products=rows)
        a = dict(args or dict())
        if tool == "create_promise":
            ledger["promises"].append(dict(product_id=a.get("product_id"), amount=round(float(a.get("amount")), 2), date=a.get("date")))
        if tool == "add_note":
            ledger["notes"].append(dict(product_id=a.get("product_id"), reason=a.get("reason")))
        if tool == "schedule_callback":
            ledger["callbacks"].append(dict(date=a.get("date"), time=a.get("time")))
        if tool == "transfer_to_agent":
            ledger["transfers"].append(dict(queue=a.get("queue")))
        return dict(ok=True)

    persona = Persona(case, pol)
    st = R.init_state(pol, cv)
    for n in range(60):
        if st["phase"] == "closed":
            break
        tok = "ks" + "abcdefghjk"[n % 10] * 2 + "abcdefghjk"[(n // 10) % 10] * 2
        st["tok"] = tok
        body = persona.say(st)
        e = R.parse_event("n=" + tok + ";src=user;" + body, st, R.CONTRACT_TOPICS)
        st, act = R.step(pol, st, e, None, now, cv)
        st["last_tok"] = tok
        said.append((body, act))
        while act.get("type") == "call_tool":
            p = st["pending"]
            data = bank(act["tool"], act.get("args"))
            te = dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"], status_code=200, ok="true", data=data)
            st, act = R.step(pol, st, None, te, now, cv)
            said.append(("tool", act))
        if act.get("type") == "close":
            ledger["outcome"], ledger["reason"] = act.get("outcome"), act.get("reason")
    return ledger, said


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
    return out + got.get("errors", [])


if __name__ == "__main__":
    if not os.path.isdir(os.path.join(GEN, "sample")):
        print("SKIP: codex-gen tests/gen/sample is absent")
        sys.exit(0)
    sys.path.insert(0, GEN)
    import oracle
    verbose = "-v" in sys.argv
    want = [a for a in sys.argv[1:] if a.startswith("gen-")]
    total = ok = 0
    sets = [x for x in ("sample", "sample2") if os.path.exists(os.path.join(GEN, x, "manifest.json"))]
    for b in [dict(b, _set=x) for x in sets for b in json.load(open(os.path.join(GEN, x, "manifest.json")))["briefs"]]:
        d = b["directory"]
        base = os.path.join(GEN, b["_set"], d)
        if want and d not in want:
            continue
        pf = os.path.join(PDIR, d + ".reducer_policy.json")
        if not os.path.exists(pf):
            print("== %s: no policy (%s)" % (d, pf))
            continue
        pol = json.load(open(pf))
        truth = json.load(open(os.path.join(base, "expected_policy.json")))
        cases = json.load(open(os.path.join(base, "cases.json")))
        oas = json.load(open(os.path.join(base, "openapi.json"))) if os.path.exists(os.path.join(base, "openapi.json")) else None
        n_ok = 0
        lines = []
        for c in cases:
            exp = oracle.expected_ledger(truth, c, c["intent"])
            got, said = run_case(pol, c, oas)
            probs = diff(exp, got)
            if exp != c.get("expected"):
                probs.append("(oracle and the case's expected ledger differ)")
            n_ok += not probs
            if probs or verbose:
                lines.append(("PASS " if not probs else "FAIL ") + "%s %s  intent=%s" % (c["id"], c["title"][:45], json.dumps(c["intent"])))
                lines += ["        " + p[:260] for p in probs]
                if verbose or probs:
                    lines += ["          %s -> %s" % (b_[:70], (a.get("text") or a.get("farewell") or "%s %s" % (a.get("tool"), a.get("args")))[:150]) for b_, a in said]
        total += len(cases)
        ok += n_ok
        print("== %s (%s): %d/%d" % (d, b["style"], n_ok, len(cases)))
        for l in lines:
            print(l)
    print("%d/%d synthetic cases match the oracle" % (ok, total))
