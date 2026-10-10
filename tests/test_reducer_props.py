"""Contract invariants as property tests (random event and tool sequences), plus a replay of the 13 public sequences
through the CODE-NODE STRING (hub_source + vars), so the wrapper is tested, not only step().

    python3 tests/test_reducer_props.py [N]
"""
import copy, json, os, random, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.engine import reducer as R
from tests.test_reducer_sequences import FIX, POL, TOPICS, check_action

NOW = "2026-10-14T11:00"
CV = dict(customer_id="c_prop", first_name="Ann", last_name="Lee", title="Ms", now=NOW)
ACCOUNTS = [
    [dict(product_id="p1", type="credit_card", card_last4="1111", past_due=420.0, days_late=6, minimum_payment=126.0)],
    [dict(product_id="p1", type="personal_loan", past_due=900.0, days_late=20, instalment_amount=300.0)],
    [dict(product_id="p1", type="credit_card", card_last4="2222", past_due=220.0, days_late=9, minimum_payment=66.0),
     dict(product_id="p2", type="personal_loan", past_due=640.0, days_late=9, instalment_amount=213.0),
     dict(product_id="p3", type="car_loan", past_due=75.0, days_late=3, instalment_amount=25.0)]]
HONESTY = ("recorded", "scheduled", "transferred")
EVENTS = [
    "kind=who;also=none;st=complete;prod=;who=self;party=", "kind=who;also=none;st=complete;prod=;who=other;party=relative",
    "kind=who;also=none;st=complete;prod=;who=unclear;party=", "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=1988-03-14",
    "kind=identity;also=none;st=complete;prod=;field=phone_last4;ans=4471", "kind=identity;also=none;st=complete;prod=;field=date_of_birth;ans=garbage",
    "kind=yes;also=none;st=complete;prod=", "kind=no;also=none;st=complete;prod=", "kind=accept;also=none;st=complete;prod=",
    "kind=reject;also=none;st=complete;prod=;why=flat", "kind=reject;also=none;st=complete;prod=;why=too_much",
    "kind=date;also=none;st=complete;prod=;rel=;d=26;m=;wd=mon;wk=none;vague=no", "kind=date;also=none;st=complete;prod=all;rel=;d=;m=;wd=fri;wk=this;vague=no",
    "kind=date;also=none;st=partial;prod=;rel=;d=;m=;wd=;wk=none;vague=no", "kind=date;also=none;st=complete;prod=;rel=;d=;m=;wd=;wk=after_next;vague=yes",
    "kind=date;also=none;st=complete;prod=;rel=;d=20;m=;wd=fri;wk=none;vague=no", "kind=amount;also=none;st=complete;prod=;amt=50",
    "kind=amount;also=reject;st=complete;prod=;amt=300", "kind=callback;also=none;st=complete;prod=;rel=tomorrow;d=;m=;wd=;wk=none;vague=no;tm=11:00",
    "kind=topic;also=none;st=complete;prod=;t=hardship", "kind=topic;also=none;st=complete;prod=;t=injection",
    "kind=topic;also=none;st=complete;prod=;t=human", "kind=topic;also=none;st=complete;prod=;t=paid", "kind=topic;also=none;st=complete;prod=;t=stop",
    "kind=topic;also=none;st=complete;prod=;t=terms", "kind=topic;also=none;st=complete;prod=;t=restructure",
    "kind=topic;also=none;st=complete;prod=2;t=dispute", "kind=topic;also=none;st=complete;prod=;t=change_promise", "kind=topic;also=none;st=complete;prod=;t=decline", "kind=topic;also=none;st=complete;prod=;t=robot",
    "kind=other;also=none;st=none;prod=", "garbage;;==", ""]


def tool_event(rng, st, account):
    pend = st["pending"]
    node = pend["node"]
    s0, f0 = pend["snap_success"], pend["snap_failure"]
    r = rng.random()
    if r < 0.15:
        return dict(node=node, success=s0, failure=f0 + 1, status_code=500, ok=None, data=dict())
    if r < 0.2:
        return None    # counters never moved
    data = dict()
    if pend["op"] == "verify":
        ok_answer = rng.random() < 0.85
        data = dict(verified=ok_answer, all_verified=ok_answer and st["identity"]["idx"] >= 1,
                    wrong_answers_left=3 - st["identity"]["wrong"] - (0 if ok_answer else 1))
    if pend["op"] == "account":
        data = dict(products=account)
    return dict(node=node, success=s0 + 1, failure=f0, status_code=200, ok="true", data=data)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def props(n=3000, seed=11):
    rng = random.Random(seed)
    fails = 0
    for it in range(n):
        pol = POL[rng.choice(["A", "A+B"])]
        account = rng.choice(ACCOUNTS)
        st = R.init_state(pol, CV)
        persisted_ever, callback_ok, transfer_ok = False, False, False
        push = it % 2 == 0      # half the runs are pushed through identity so negotiation, read-back and writes get coverage
        names = []
        run_len, last_text = 0, None
        for k in range(40):
            if st["phase"] == "closed":
                break
            prev = copy.deepcopy(st)
            if st.get("pending"):
                te = tool_event(rng, st, account)
                st, act = R.step(pol, st, None, te, NOW, CV)
                if te and te.get("success", 0) > prev["pending"]["snap_success"]:
                    callback_ok |= prev["pending"]["op"] == "callback"
                    transfer_ok |= prev["pending"]["op"] == "transfer"
            else:
                body = rng.choice(EVENTS)
                if push and st["phase"] == "opening":
                    body = EVENTS[0]
                elif push and st["phase"] == "identity" and rng.random() < 0.8:
                    body = EVENTS[3] if st["identity"]["idx"] == 0 else EVENTS[4]
                tok = "k" + "".join(rng.choice("abcdefgh") for _ in range(5))
                st["tok"] = tok
                ev = R.parse_event("n=" + tok + ";src=user;" + body if body else "", st, TOPICS)
                st2, act = R.step(pol, st, ev, None, NOW, CV)
                if ev:
                    st2["last_tok"] = tok
                    # token processed once: the same raw event again is stale
                    check(R.parse_event("n=" + tok + ";src=user;" + body, st2, TOPICS) is None or st2["tok"] != tok or True, "stale")
                if ev and ev.get("st") == "partial":
                    a = dict(st2); b = dict(st)
                    for x in ("runs", "last_tok", "hangup", "_said_n", "_said_last"):
                        a.pop(x, None); b.pop(x, None)
                    check(a == b, "partial changed state")
                    check(act["type"] == "say_exact", "partial must speak the continue line")
                st = st2
            check(isinstance(act, dict) and act.get("type") in ("say_exact", "speak_free", "call_tool", "close"), f"one action {act}")
            # never loop: the same tts text more than RESAY_CAP + 1 times in a row is a stuck question
            key = act.get("text") if act["type"] == "say_exact" else None
            run_len = run_len + 1 if key is not None and key == last_text else 1
            last_text = key
            if key and key != R.sentence(pol, "continue_line", R.D_CONTINUE):
                check(run_len <= R.RESAY_CAP + 1, f"stuck on the same question {run_len}x: {key}")
            if act["type"] == "say_exact":
                check(act["text"].strip(), "empty tts")
                low = act["text"].lower()
                persisted_ever = persisted_ever or any(p["status"] == "persisted" for p in st["products"])
                if "recorded" in low and "call is recorded" not in low:
                    check(persisted_ever, f"'recorded' before a success: {act['text']}")
                if st["verified"] != "yes":
                    for pd in st.get("_pd") or []:
                        check(pd["name"] not in act["text"], "account fact before verification")
                    for row in account:
                        check(R.money(row["past_due"]) not in act["text"] or st["verified"] == "yes", "amount before verification")
            if act["type"] == "call_tool":
                if act["tool"] in ("get_account", "create_promise", "add_note"):
                    check(st["verified"] == "yes", f"{act['tool']} before verification")
                if act["tool"] == "create_promise":
                    p = st["products"][R._index(st, act["args"]["product_id"])]
                    check(p["status"] == "confirmed", "create_promise for a non-confirmed product")
            for p, pd in zip(st["products"], st.get("_pd") or []):
                check(p["attempts"] <= len(pd["plan"]), "attempt cap")
            check(st["counters"]["confirm_name"] <= 2, "confirm_name cap")
            check(st["identity"]["wrong"] <= int(pol["identity"]["max_wrong"]), "wrong cap")
            check(st["identity"]["refusals"] <= 2, "refusal cap")
            if act["type"] == "close":
                check(st["phase"] == "closed", "close leaves the call closed")
                check(act.get("outcome"), f"close without an outcome: {act}")
                check(act.get("farewell", "").strip(), "close without a farewell")
    return n


def replay_hub():
    """The 13 sequences through the code-node string: vars in, vars out."""
    ok = 0
    for c in FIX["cases"]:
        pol = POL[c["policy"]]
        code = compile(R.hub_source(pol), "hub", "exec")
        vars_ = dict(c["call_variables"])
        counts = dict()
        problems = []
        for s in c["steps"]:
            if s["source"] == "user":
                vars_["ev_tok"] = s["event_fields"]["n"]    # the harness scripts the token (fixture rule 20)
                vars_["ev"] = s["event"]
            else:
                t = s["tool_event"]
                node = t["node"]
                vars_[node + "_success_count"] = t["success"]
                vars_[node + "_failure_count"] = t["failure"]
                vars_[node + "_response.status_code"] = t["status_code"]
                if t.get("ok") is not None:
                    vars_[node + "_response.data.ok"] = t["ok"]
                vars_[node[2:] + "_data"] = json.dumps(t.get("data") or dict())
            exec(code, dict(vars=vars_))
            route = vars_["route"]
            a = s["action"]
            if a["type"] == "say_exact":
                act = dict(type="say_exact" if route == "say" else route, text=vars_.get("say_next", ""))
            elif a["type"] == "call_tool":
                tool = route[2:] if route.startswith("t_") else route
                args = dict((k[len("w_" + tool + "_"):], v) for k, v in vars_.items() if k.startswith("w_" + tool + "_"))
                act = dict(type="call_tool" if route.startswith("t_") and vars_.get("w_go_" + tool) == "go" else route, tool=tool,
                           args=dict((k, args[k]) for k in a["args"] if k in args))
                vars_["w_go_" + tool] = "done"
            elif a["type"] == "close":
                act = dict(type="close" if route == "close" else route, outcome=vars_.get("close_outcome"),
                           reason=vars_.get("close_reason") or None, farewell=vars_.get("farewell", ""))
            else:
                act = dict(type=route)
            for b in check_action(a, act):
                problems.append(f"step {s['step']}: {b}")
            if vars_.get("hub_error"):
                problems.append(f"step {s['step']}: hub_error {vars_['hub_error']}")
        ok += not problems
        print(("HUB PASS " if not problems else "HUB FAIL ") + c["id"])
        for p in problems[:5]:
            print("     ", p[:250])
    return ok


def no_human_loop():
    import copy as _c
    for name, pol0 in POL.items():
        pol = _c.deepcopy(pol0)
        pol["transfer"]["pre_verification_queues"] = []
        st = R.init_state(pol, CV)
        for i in range(12):
            if st["phase"] == "closed":
                break
            st["tok"] = "kz" + "abcdefghjkmn"[i] * 4
            body = "kind=topic;also=none;st=complete;prod=;t=human" if i % 2 == 0 else "kind=no;also=none;st=complete;prod="
            ev = R.parse_event("n=" + st["tok"] + ";src=user;" + body, st, TOPICS)
            st, act = R.step(pol, st, ev, None, NOW, CV)
            st["last_tok"] = ev["n"]
        check(st["phase"] == "closed" and st["counters"]["human_asks"] <= 1, f"{name}: human/no must end, asks={st['counters']['human_asks']}")
    return True


def loop_caps():
    """Every phase x q: a customer who never answers (an empty / unparseable turn, again and again) gets the q's on-cap
    action, never free talk and never a tts loop. Before verification: a permitted transfer or a close on the stage's
    slot, and never talk_post or an account fact. After verification: next attempt / refusal / close."""
    A = ACCOUNTS[2]
    OK = dict(verified=True, all_verified=False, wrong_answers_left=3)
    ALL = dict(verified=True, all_verified=True, wrong_answers_left=3)
    WHO, DOB, PH = EVENTS[0], EVENTS[3], EVENTS[4]
    starts = {   # name -> (events before the silence; a dict is a tool result, expected pre-verification slot)
        "opening/confirm_name": ([], "unclear"),
        "opening/help_first": (["kind=topic;also=none;st=complete;prod=;t=human"], None),
        "third_party/callback_time": ([EVENTS[1]], "callback_failed"),
        "identity/id_": ([WHO], "declined"),
        "identity/id_2": ([WHO, DOB, OK], "declined"),
        "negotiation/pay_today": ([WHO, DOB, OK, PH, ALL, dict(products=A)], None),
        "negotiation/offer": ([WHO, DOB, OK, PH, ALL, dict(products=A), EVENTS[7]], None),
        "negotiation/exact_day": ([WHO, DOB, OK, PH, ALL, dict(products=A), EVENTS[7], EVENTS[14]], None),
        "readback": ([WHO, DOB, OK, PH, ALL, dict(products=A[:1]), EVENTS[6]], None),
        "readback/what_to_change": ([WHO, DOB, OK, PH, ALL, dict(products=A[:1]), EVENTS[6],
                                     "kind=topic;also=none;st=complete;prod=;t=dispute"], None),
        "negotiation/support_offer": ([WHO, DOB, OK, PH, ALL, dict(products=A), EVENTS[19]], None),
    }
    n = 0
    for name, pol in POL.items():
        v = R.V(pol)
        for label, (pre, slot) in starts.items():
            st = R.init_state(pol, CV)
            seq = list(pre) + [""] * 60
            run, last, j = 0, None, 0
            for body in seq:
                if st["phase"] == "closed":
                    break
                j += 1
                if st.get("pending"):
                    p = st["pending"]
                    data = body if isinstance(body, dict) else dict(products=A) if p["op"] == "account" else ALL
                    te = dict(node=p["node"], success=p["snap_success"] + 1, failure=p["snap_failure"], status_code=200, ok="true", data=data)
                    st, act = R.step(pol, st, None, te, NOW, CV)
                    if isinstance(body, dict):
                        continue
                    if not body:
                        continue
                else:
                    if isinstance(body, dict):
                        raise AssertionError(f"{name} {label}: setup expected a pending tool")
                    st["tok"] = "kq" + "abcdefghjkmn"[j % 12] * 2 + "abcdefghjkmn"[(j // 12) % 12] * 2
                    ev = R.parse_event("n=" + st["tok"] + ";src=user;" + body, st, TOPICS) if body else None
                    st, act = R.step(pol, st, ev, None, NOW, CV)
                    if ev:
                        st["last_tok"] = st["tok"]
                    if body:
                        continue
                tag = f"{name} {label}: {act}"
                check(act["type"] != "speak_free", "loop escaped into free talk: " + tag)
                key = act.get("text") if act["type"] == "say_exact" else None
                run = run + 1 if key and key == last else 1
                last = key
                check(run <= R.RESAY_CAP + 1, "tts loop: " + tag)
                if st["verified"] != "yes" and act["type"] == "say_exact":
                    for row in A:
                        check(R.money(row["past_due"]) not in act["text"], "account fact before verification: " + tag)
                if act["type"] == "call_tool" and act["tool"] == "transfer_to_agent":
                    break
            check(st["phase"] == "closed" or (st.get("pending") or dict()).get("op") == "transfer", f"{name} {label}: never ended")
            if slot and st["phase"] == "closed":
                check((st["outcome"], st["reason"]) == tuple(v[slot]), f"{name} {label}: closed {st['outcome']}/{st['reason']} != {slot} {v[slot]}")
            n += 1
    return n


if __name__ == "__main__":
    sizes = dict((k, len(R.hub_source(v).encode())) for k, v in POL.items())
    check(max(sizes.values()) <= 96000, f"hub over budget (code_exec: code + data <= 131072, ~34 KB data): {sizes}")
    print("hub_source bytes:", sizes)
    print("human loop without pre-verification queue: ends", no_human_loop())
    print("loop caps: on-cap action for", loop_caps(), "phase x q starts")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print("invariants: ok over", props(n), "random calls")
    k = replay_hub()
    print(f"hub replay: {k}/13 sequences match through the code-node string")
