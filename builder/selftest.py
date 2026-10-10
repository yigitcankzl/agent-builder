"""Build-time self-test: generated local scenarios run through Fork 3's reducer (via the seam), checked against
INVARIANTS ONLY plus independent date facts from the date core. No expected conversations or outcomes are computed
here; that would duplicate the reducer.

run_selftest(policy, oas_path, reducer=None) -> {run, scenarios, passed, failed, invariants: {name: [pass, fail]},
                                                 failures: [...], seconds, note}
Scenarios come from policy data only: band edges, holidays and weekends, refusals beyond the cap, identity right /
wrong / wrong x max, 1-3 product mixes, tool failure x (retries + 1), a partial event, an injection, a pre-verification
human request. A scripted customer answers the reducer's open question (st['q'], contract §11.1); a fake bank answers
the tool calls from the OAS response shapes.
"""
import datetime, importlib, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder.engine import dates as D

def pick_now(policy):
    """A reproducible 'today' derived from the policy: the first business day two weeks before its earliest holiday,
    so the holiday scenarios fall inside the deadlines; without holidays, a fixed weekday."""
    hol = sorted((policy.get("business_days") or {}).get("holidays") or [])
    d = datetime.date.fromisoformat(hol[0]) - datetime.timedelta(days=14) if hol else datetime.date(2030, 1, 8)
    while not D.is_business_day(d, policy):
        d += datetime.timedelta(days=1)
    return d.isoformat() + "T11:00"


NOW = None   # set per run by run_selftest
WRITE_TOOLS = ("create_promise", "add_note", "schedule_callback", "transfer_to_agent")
ACCOUNT_TOOLS = ("get_account", "create_promise", "add_note")
TYPES = ("say_exact", "speak_free", "call_tool", "close")
MAX_STEPS = 80


def load_reducer():
    try:
        m = importlib.import_module("builder.engine.reducer")
        return m if hasattr(m, "step") and hasattr(m, "init_state") else None
    except ImportError:
        return None


def _oas_enum(oas_path, tool, field):
    d = json.load(open(oas_path))
    for path, ops in d.get("paths", {}).items():
        if path.strip("/").split("/")[-1] == tool:
            for op in ops.values():
                s = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
                return (s.get("properties", {}).get(field) or {}).get("enum")
    return None


def _labels(d):
    return dict(rel="", d=str(d.day), m=str(d.month), wd="", wk="none", vague="no")


class Bank:
    """Fake bank for the self-test: answers in the OAS response shapes; never enforces the brief."""
    def __init__(self, products, right_answers, fail=None, max_wrong=3):
        self.products, self.right, self.fail = products, right_answers, dict(fail or {})
        self.wrong_left = max_wrong if isinstance(max_wrong, int) else 3
        self.verified = set()
        self.counts = {}

    def call(self, tool, args):
        node = "t_" + tool
        s, f = self.counts.get(node, (0, 0))
        if self.fail.get(tool, 0) > 0:
            self.fail[tool] -= 1
            self.counts[node] = (s, f + 1)
            return dict(node=node, success=s, failure=f + 1, status_code=500, ok=None, data={})
        data = {"ok": True}
        if tool == "verify_identity":
            okv = self.wrong_left > 0 and str(args.get("answer")) == str(self.right.get(args.get("field")))
            if okv:
                self.verified.add(args.get("field"))
            else:
                self.wrong_left = max(0, self.wrong_left - 1)
            data.update(verified=okv, all_verified=len(self.verified) >= len(self.right), wrong_answers_left=self.wrong_left)
        elif tool == "get_account":
            data["products"] = self.products
        self.counts[node] = (s + 1, f)
        return dict(node=node, success=s + 1, failure=f, status_code=200, ok="true", data=data)


def _products(policy, mix, today):
    """Products from the policy's own types and bands (no brief literals)."""
    types = [k for k in ((policy.get("products") or {}).get("floor_by_type") or {}) if k != "*"] or list(((policy.get("products") or {}).get("naming_by_type") or {})) or ["product"]
    bands = (policy.get("deadline") or {}).get("bands") or [{"min_days_late": 1, "max_days_late": 30}]
    out = []
    for i, (ti, bi, edge) in enumerate(mix):
        t, b = types[ti % len(types)], bands[bi % len(bands)]
        dl = b.get("max_days_late") if edge == "max" else (b.get("min_days_late") or 1)
        fbt = (policy.get("products") or {}).get("floor_by_type") or {}
        fb = fbt.get(t) or fbt.get("*") or {}
        row = {"product_id": f"p{i + 1}", "type": t, "past_due": 300.0 + 100 * i, "days_late": int(dl)}
        tpl = ((policy.get("products") or {}).get("naming_by_type") or {}).get(t) or ""
        for f in re.findall(r"\{(\w+)\}", tpl):     # fields the spoken product name needs (e.g. last digits)
            row.setdefault(f, "4321")
        if fb.get("kind") in ("field", "account_field") and fb.get("field"):
            row[fb["field"]] = 90.0 + 10 * i
        out.append(row)
    return out


def scenarios(policy):
    """name -> knobs. Generated from the policy only."""
    bands = (policy.get("deadline") or {}).get("bands") or []
    hol = (policy.get("business_days") or {}).get("holidays") or []
    idq = [q.get("field") for q in (policy.get("identity") or {}).get("questions") or []]
    retries = {t: (v or {}).get("retries", 1) for t, v in (policy.get("tools") or {}).items()}
    sc = {}
    for bi, b in enumerate(bands):
        for edge in ("min", "max"):
            sc[f"band{bi}_{edge}_accept_today"] = dict(mix=[(0, bi, edge)], pay="accept")
        sc[f"band{bi}_refuse_cap_plus_1"] = dict(mix=[(0, bi, "min")], pay="refuse", refusals=len(((policy.get("attempts") or {}).get("plan") or {}).get(b.get("name"), [])) + 1)
    today = datetime.date.fromisoformat(NOW[:10])
    for h in hol:
        d = datetime.date.fromisoformat(h)
        if today <= d <= today + datetime.timedelta(days=60):
            sc[f"holiday_{h}"] = dict(mix=[(0, 0, "min")], pay="date", date=d)
    sat = today + datetime.timedelta(days=(5 - today.weekday()) % 7)
    sc["weekend_early"] = dict(mix=[(0, 0, "min")], pay="date", date=sat)
    sc["weekend_far"] = dict(mix=[(0, len(bands) - 1, "max")], pay="date", date=sat + datetime.timedelta(days=21))
    sc["identity_right"] = dict(mix=[(0, 0, "min")], pay="accept")
    sc["identity_wrong_once"] = dict(mix=[(0, 0, "min")], pay="accept", wrong=1)
    sc["identity_wrong_max"] = dict(mix=[(0, 0, "min")], pay="accept", wrong=99)
    if (policy.get("multi_product") or {}).get("applies"):
        sc["two_products"] = dict(mix=[(0, 0, "min"), (1, len(bands) - 1, "max")], pay="accept")
        sc["three_products_refuse"] = dict(mix=[(0, 0, "min"), (1, 0, "max"), (2, len(bands) - 1, "max")], pay="refuse", refusals=9)
    for tool in ("get_account", "create_promise"):
        sc[f"fail_{tool}_x{retries.get(tool, 1) + 1}"] = dict(mix=[(0, 0, "min")], pay="accept", fail={tool: retries.get(tool, 1) + 1})
    sc["partial_then_accept"] = dict(mix=[(0, 0, "min")], pay="accept", partial=True)
    sc["injection_before_verify"] = dict(mix=[(0, 0, "min")], pay="accept", inject=True)
    sc["human_before_verify"] = dict(mix=[(0, 0, "min")], pay="accept", human_pre=True)
    sc["third_party_callback"] = dict(mix=[(0, 0, "min")], pay="accept", third_party=True)
    sc["_idq"] = idq
    return sc


class Customer:
    """Scripted customer: answers the open question st['q'] with a generic event (kind/payload per contract §1.2)."""
    def __init__(self, knobs, rights, wrongs):
        self.k, self.rights, self.wrongs = knobs, rights, wrongs
        self.wrong_left = knobs.get("wrong", 0)
        self.refusals = knobs.get("refusals", 0)
        self.did = set()

    def next(self, st, tok):
        k, q = self.k, str(st.get("q") or "none")
        ev = dict(n=tok, src="user", also="none", st="complete", prod="")
        if k.get("partial") and "partial" not in self.did and q in ("pay_today", "offer"):
            self.did.add("partial")
            return dict(ev, kind="date", st="partial", rel="", d="", m="", wd="", wk="none", vague="no")
        if k.get("inject") and "inject" not in self.did and st.get("verified") != "yes":
            self.did.add("inject")
            return dict(ev, kind="topic", t="injection")
        if k.get("human_pre") and "human" not in self.did and st.get("verified") != "yes":
            self.did.add("human")
            return dict(ev, kind="topic", t="human")
        if q == "confirm_name":
            return dict(ev, kind="who", who="other" if k.get("third_party") else "self", party="relative" if k.get("third_party") else "")
        if q == "callback_time":
            d = datetime.date.fromisoformat(NOW[:10]) + datetime.timedelta(days=1)
            return dict(ev, kind="callback", tm="11:00", **_labels(d))
        if q.startswith("id_"):
            f = q[3:]
            if self.wrong_left > 0:
                self.wrong_left -= 1
                return dict(ev, kind="identity", field=f, ans=self.wrongs.get(f, "0000"))
            return dict(ev, kind="identity", field=f, ans=self.rights.get(f, "1111"))
        if q in ("pay_today", "offer"):
            if k["pay"] == "refuse" and self.refusals > 0:
                self.refusals -= 1
                return dict(ev, kind="reject", why="flat")
            if k["pay"] == "date" and "date" not in self.did:
                self.did.add("date")
                return dict(ev, kind="date", **_labels(k["date"]))
            return dict(ev, kind="accept")
        if q in ("readback",):
            return dict(ev, kind="yes")
        if q in ("help_first",):
            return dict(ev, kind="no")
        if q in ("support_offer", "what_to_change"):
            return dict(ev, kind="no")
        if q == "exact_day":
            return dict(ev, kind="date", **_labels(datetime.date.fromisoformat(NOW[:10]) + datetime.timedelta(days=2)))
        return dict(ev, kind="yes")


def _check_dates(policy, args, products, today, fails):
    pid, d = args.get("product_id"), args.get("date")
    prod = next((p for p in products if p["product_id"] == pid), None)
    try:
        day = datetime.date.fromisoformat(str(d)[:10])
    except Exception:
        fails.append(f"recorded date {d!r} is not a date")
        return
    if prod is None:
        fails.append(f"promise for unknown product {pid!r}")
        return
    dl = D.deadline_for(today, prod["days_late"], policy)
    if not (D.is_business_day(day, policy) and today <= day <= dl):
        fails.append(f"recorded date {day} is not a business day in [{today}, {dl}]")


def run_scenario(R, policy, name, knobs, oas_path, idq):
    today = datetime.date.fromisoformat(NOW[:10])
    products = _products(policy, knobs["mix"], today)
    rights = {f: ("1980-01-01" if "date" in str(f) else "1234") for f in idq}
    wrongs = {f: ("1970-02-02" if "date" in str(f) else "9999") for f in idq}
    bank = Bank(products, rights, knobs.get("fail"), (policy.get("identity") or {}).get("max_wrong"))
    cust = Customer(knobs, rights, wrongs)
    # call variables by the roles the policy declares (meta.call_vars), with neutral sample values
    roles = list(((policy.get("meta") or {}).get("call_vars") or {}).keys())
    cv = {r: ("c_self" if "id" in r else "Sample") for r in roles}
    cv.setdefault("customer_id", "c_self")
    cv[(policy.get("now") or {}).get("var", "now")] = NOW
    st = R.init_state(policy, cv)
    honesty = [w.lower() for w in (policy.get("honesty_words") or {}).get("words") or []]
    out_enum = _oas_enum(oas_path, "close_call", "outcome") or []
    fails, inv = [], {}
    verified_seen = False
    write_success = 0
    readback_yes = False
    tool_ev = None
    tok = "kstart"
    max_wrong = (policy.get("identity") or {}).get("max_wrong")
    wrong_calls = 0
    closed = None
    for i in range(MAX_STEPS):
        ev = None if tool_ev else cust.next(st, tok)
        before = json.dumps({k: v for k, v in st.items() if k not in ("runs", "tok", "last_tok", "hangup") and not k.startswith("_")}, sort_keys=True, default=str)
        try:
            st, act = R.step(policy, st, ev, tool_ev, NOW, cv)
        except Exception as e:
            fails.append(f"step raised {type(e).__name__}: {str(e)[:120]}")
            break
        if ev:
            st["last_tok"] = tok
        tok = "k" + "abcdefghjkmnpqrstuvwxyz"[i % 23] * 5
        st["tok"] = tok
        tool_ev = None
        # invariant 1: exactly one well-formed action
        if not isinstance(act, dict) or act.get("type") not in TYPES:
            fails.append(f"step {i}: not exactly one action: {act!r}"[:200])
            break
        t = act["type"]
        if ev and ev.get("st") == "partial":
            # the business state must not change; reducer-private bookkeeping (keys starting with "_") is not compared
            after = json.dumps({k: v for k, v in st.items() if k not in ("runs", "tok", "last_tok", "hangup") and not k.startswith("_")}, sort_keys=True, default=str)
            if t != "say_exact" or after != before:
                fails.append("partial event changed state or did not just say a line")
        text = (act.get("text") or act.get("farewell") or act.get("hint") or "")
        # invariant 2: no empty say
        if t == "say_exact" and not str(act.get("text") or "").strip():
            fails.append(f"step {i}: empty say")
        if t == "close" and not str(act.get("farewell") or "").strip():
            fails.append(f"step {i}: empty farewell")
        # invariant 6: honesty words only after a success delta of a write tool
        if t in ("say_exact", "close") and not write_success:
            hit = [w for w in honesty if w and w in str(text).lower()]
            if hit:
                fails.append(f"step {i}: honesty word {hit} before any write success: {str(text)[:80]!r}")
        # invariant 4: no account fact or account/write tool before verification
        if not verified_seen:
            if t == "call_tool" and act["tool"] in ACCOUNT_TOOLS:
                fails.append(f"step {i}: {act['tool']} before verification")
            if t == "speak_free" and act.get("node") == "talk_post":
                fails.append(f"step {i}: talk_post before verification")
            for p in products:
                if t in ("say_exact", "speak_free", "close") and (f"{p['past_due']:g}" in str(text) or f"{p['past_due']:.2f}" in str(text)):
                    fails.append(f"step {i}: account amount spoken before verification")
        if t == "say_exact" and str(st.get("q")) == "readback":
            readback_yes = False
        if ev and ev.get("kind") == "yes" and str(st.get("q")) != "readback" and getattr(cust, "_last_q", "") == "readback":
            readback_yes = True
        cust._last_q = str(st.get("q"))
        if t == "call_tool":
            tool, raw = act["tool"], dict(act.get("args") or {})
            # the reducer may write canonical names or the OAS field names of policy.tool_args: read both
            table = (policy.get("tool_args") or {}).get(tool) or {}
            args = dict(raw)
            for c, f in table.items():
                if c not in args and f in raw:
                    args[c] = raw[f]
            # invariant 3: no write without a confirmed read-back answered yes
            if tool == "create_promise":
                if not readback_yes:
                    fails.append(f"step {i}: create_promise without a confirmed read-back")
                _check_dates(policy, args, products, today, fails)
            if tool == "verify_identity" and str(args.get("answer")) != rights.get(args.get("field")):
                wrong_calls += 1
            tool_ev = bank.call(tool, args)
            if tool == "verify_identity" and tool_ev["data"].get("all_verified"):
                verified_seen = True
            if tool in WRITE_TOOLS and tool_ev["ok"] == "true":
                write_success += 1
        if t == "close":
            closed = act
            break
    # invariant 5: caps
    if isinstance(max_wrong, int) and wrong_calls > max_wrong:
        fails.append(f"identity: {wrong_calls} wrong answers sent, cap {max_wrong}")
    late = {x["product_id"]: x["days_late"] for x in products}
    for p in st.get("products") or []:
        dl = int(p.get("days_late") or late.get(str(p.get("id")), 0)) if isinstance(p, dict) else 0
        band = next((b for b in (policy.get("deadline") or {}).get("bands") or [] if b.get("min_days_late", 0) <= dl <= b.get("max_days_late", 999)), None)
        cap = len(((policy.get("attempts") or {}).get("plan") or {}).get((band or {}).get("name"), []))
        if isinstance(p, dict) and int(p.get("attempts") or 0) > cap:
            fails.append(f"product {p.get('id')}: {p.get('attempts')} attempts, cap {cap}")
    # invariant 7: ends in close with an OAS outcome
    if not closed:
        fails.append("no close within the step budget")
    elif out_enum and closed.get("outcome") not in out_enum:
        fails.append(f"close outcome {closed.get('outcome')!r} not in the OAS enum")
    return fails


INVARIANTS = ("one action", "empty say", "read-back before write", "verification gate", "caps", "honesty", "close outcome", "dates", "partial")


def _classify(f):
    for key, name in (("not exactly one", "one action"), ("empty", "empty say"), ("read-back", "read-back before write"),
                      ("before verification", "verification gate"), ("cap", "caps"), ("honesty", "honesty"),
                      ("close", "close outcome"), ("date", "dates"), ("partial", "partial"), ("raised", "one action")):
        if key in f:
            return name
    return "other"


def run_selftest(policy, oas_path, reducer=None):
    t0 = time.time()
    R = reducer or load_reducer()
    if R is None:
        return {"run": False, "note": "skipped: no reducer module (stub hub)", "scenarios": 0, "passed": 0, "failed": 0}
    global NOW
    NOW = pick_now(policy)
    sc = scenarios(policy)
    idq = sc.pop("_idq")
    res, inv = {}, {n: [0, 0] for n in INVARIANTS}
    for name, knobs in sc.items():
        fails = run_scenario(R, policy, name, knobs, oas_path, idq)
        res[name] = fails
        hit = {_classify(f) for f in fails}
        for n in INVARIANTS:
            inv[n][1 if n in hit else 0] += 1
    failed = {k: v for k, v in res.items() if v}
    return {"run": True, "scenarios": len(res), "passed": len(res) - len(failed), "failed": len(failed),
            "invariants": inv, "failures": {k: v[:4] for k, v in failed.items()}, "seconds": round(time.time() - t0, 2),
            "now": NOW, "note": "invariants only; outcomes are not predicted"}


if __name__ == "__main__":
    pol = json.load(open(sys.argv[1]))
    print(json.dumps(run_selftest(pol, sys.argv[2] if len(sys.argv) > 2 else "tools/openapi.json"), indent=1))
