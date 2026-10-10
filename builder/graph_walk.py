"""Local workflow-graph walker: runs a compiled workflow JSON the way the Freya engine does (docs/workflow-format.md,
docs/tools-and-code.md), with scripted `ev` extractions and a fake bank, so wiring bugs show up before the platform.

    from builder.graph_walk import walk
    report = walk(workflow, oas, call_vars, user_events, bank)

What it emulates
- initial_node; on_enter tts with {{var}} substitution (an unresolved placeholder in spoken text is an error);
  on_enter llm is recorded as '<llm>' speech;
- conversation nodes wait for a user message; extraction writes `ev` (the scripted value with the code copied from
  {{ev_tok}}, as the extractor does) only when it matches the field's validation_pattern;
- transitions in list order, same-target transitions merged (OR, unconditional wins), deterministic operators
  (equals, not_equals, greater_than, less_than, contains, is_set, is_not_set, always), AND/OR groups; a model-routed
  condition never matches here (reported);
- passthrough nodes route at once (no match = deadlock, an error);
- code nodes exec their code_exec string with `vars` (the packed hub included);
- api_request nodes build the body from the baked defaults (an exact unresolved placeholder drops the field, a mixed
  one stays literal and is an error), coerce to the declared types, validate against the OAS, call the fake bank,
  then write <node>_success_count / _failure_count, <node>_status_code, the flattened <node>_response.* keys and the
  node-level response_mapping;
- end_call nodes, then the lifecycle tools (alwaysRunsAt end_of_call) with their pre_process_code.
Assumption (not documented): a body field declared number/integer/boolean is sent as that type after substitution.
"""
import json
import re

PH = re.compile(r'\{\{\s*([A-Za-z0-9_.\-]+)(:json)?\s*\}\}')


class WalkError(Exception):
    pass


def _resolve(text, vars_):
    """{{var}} -> value; returns (text, unresolved names)."""
    missing = []

    def rep(m):
        name, as_json = m.group(1), m.group(2)
        if name not in vars_ or vars_[name] is None:
            missing.append(name)
            return m.group(0)
        v = vars_[name]
        return json.dumps(v) if as_json else (str(v).lower() if isinstance(v, bool) else str(v))
    return PH.sub(rep, str(text)), missing


def _set(v):
    return v is not None


def _cond(c, vars_):
    if not c:
        return False
    if 'conditions' in c:
        rs = [_cond(x, vars_) for x in c.get('conditions') or []]
        return all(rs) if str(c.get('logic', 'and')).lower() == 'and' else any(rs)
    op = c.get('operator')
    if op == 'always':
        return True
    if op == 'matches_intent':
        return False
    v = vars_.get(c.get('variable'))
    o = c.get('operand')
    try:
        if op == 'equals':
            return _set(v) and str(v) == str(o)
        if op == 'not_equals':
            return not (_set(v) and str(v) == str(o))
        if op == 'greater_than':
            return _set(v) and float(v) > float(o)
        if op == 'less_than':
            return _set(v) and float(v) < float(o)
        if op == 'contains':
            return _set(v) and str(o).lower() in str(v).lower()
        if op == 'is_set':
            return _set(v)
        if op == 'is_not_set':
            return not _set(v)
    except (TypeError, ValueError):
        return False
    raise WalkError('unknown operator ' + str(op))


def _merged(transitions):
    """Same target_node -> one transition, OR of the conditions; an unconditional one makes it unconditional."""
    order, by = [], dict()
    for t in transitions or []:
        tgt = t.get('target_node')
        if tgt not in by:
            order.append(tgt)
            by[tgt] = []
        by[tgt].append(t.get('condition') or dict(operator='always'))
    out = []
    for tgt in order:
        cs = by[tgt]
        cond = dict(operator='always') if any(c.get('operator') == 'always' for c in cs) else dict(logic='or', conditions=cs)
        out.append((tgt, cond))
    return out


def _flatten(prefix, obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(prefix + '.' + str(k), v, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(prefix + '.' + str(i), v, out)
    else:
        out[prefix] = str(obj).lower() if isinstance(obj, bool) else obj
    return out


def _get(obj, path):
    cur = obj
    for p in [x for x in str(path).split('.') if x]:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return None
    return cur


# ---------------------------------------------------------------- OAS
def _deref(oas, s, depth=0):
    if isinstance(s, dict) and '$ref' in s and depth < 20:
        node = oas
        for p in s['$ref'].lstrip('#/').split('/'):
            node = node.get(p, dict())
        return _deref(oas, node, depth + 1)
    return s


def oas_schema(oas, url):
    """The JSON request-body schema of the operation whose path ends the URL (servers base ignored)."""
    tail = '/' + url.rstrip('/').split('/')[-1]
    for path, ops in (oas.get('paths') or dict()).items():
        if path.rstrip('/').endswith(tail):
            op = ops.get('post') or next(iter(ops.values()))
            body = _deref(oas, (op.get('requestBody') or dict()))
            return _deref(oas, (((body.get('content') or dict()).get('application/json') or dict()).get('schema')))
    return None


def validate(oas, schema, value, where='body'):
    """Small JSON-schema check: type, required, enum, properties, items. Returns a list of problems."""
    s = _deref(oas, schema or dict())
    errs = []
    t = s.get('type')
    types = dict(string=str, integer=int, number=(int, float), boolean=bool, object=dict, array=list)
    if t in types and not (isinstance(value, types[t]) and not (t in ('integer', 'number') and isinstance(value, bool))):
        errs.append('%s: %r is not %s' % (where, value, t))
        return errs
    if 'enum' in s and value not in s['enum']:
        errs.append('%s: %r not in enum %s' % (where, value, s['enum']))
    if t == 'object' or 'properties' in s:
        for r in s.get('required') or []:
            if not isinstance(value, dict) or r not in value:
                errs.append('%s: required field %s missing' % (where, r))
        for k, sub in (s.get('properties') or dict()).items():
            if isinstance(value, dict) and k in value:
                errs += validate(oas, sub, value[k], where + '.' + k)
        for k in (value if isinstance(value, dict) else dict()):
            if s.get('additionalProperties') is False and k not in (s.get('properties') or dict()):
                errs.append('%s: field %s not in the schema' % (where, k))
    if t == 'array' and isinstance(value, list):
        for i, x in enumerate(value):
            errs += validate(oas, s.get('items') or dict(), x, '%s[%d]' % (where, i))
    return errs


# ---------------------------------------------------------------- the walk
def _coerce(v, decl):
    t = (decl or dict()).get('type')
    try:
        if t == 'number' and isinstance(v, str) and v.strip() != '':
            return float(v)
        if t == 'integer' and isinstance(v, str) and v.strip() != '':
            return int(float(v))
        if t == 'boolean' and isinstance(v, str):
            return v.strip().lower() == 'true'
    except ValueError:
        return v
    return v


def walk(workflow, oas, call_vars, user_events, bank, max_steps=2000):
    """Run one call. bank(tool_name, body) -> (status_code, json_body). user_events: ev strings (one per user turn;
    None = the extractor wrote nothing). Returns dict(errors, warnings, entered, speech, calls, hub, vars, ended)."""
    wf = workflow.get('workflow', workflow)
    nodes = wf['nodes']
    vars_ = dict(wf.get('test_variables') or dict())
    vars_.update(call_vars)
    rep = dict(errors=[], warnings=[], entered=[], speech=[], calls=[], hub=[], ended=False)
    err = lambda m: rep['errors'].append(m)
    events = list(user_events)
    turn_spoke = [True]

    def speak(node, text):
        rep['speech'].append((node, text))
        turn_spoke[0] = True

    def api(node_id, fn, cfg_pre=None):
        params = (fn.get('parameters') or dict()).get('properties') or dict()
        url = _resolve((params.get('url') or dict()).get('default', ''), vars_)[0]
        props = ((params.get('body') or dict()).get('properties') or dict())
        body = dict()
        for k, decl in props.items():
            raw = decl.get('default')
            if raw is None:
                continue
            if isinstance(raw, str):
                val, miss = _resolve(raw, vars_)
                if miss and PH.fullmatch(raw.strip()):
                    rep['warnings'].append('%s: field %s dropped (unresolved %s)' % (node_id, k, miss[0]))
                    continue
                if miss:
                    err('%s: field %s sent with a literal placeholder %s' % (node_id, k, miss))
                body[k] = _coerce(val, decl)
            else:
                body[k] = raw
        if cfg_pre:
            env = dict(config=dict(body=body, url=url), vars=vars_)
            try:
                exec(compile(cfg_pre, node_id + '.pre_process', 'exec'), env)
            except Exception as e:
                err('%s: pre_process_code raised %s' % (node_id, e))
            body = env['config'].get('body', body)
        tool = url.rstrip('/').split('/')[-1]
        schema = oas_schema(oas, url)
        if schema is None:
            err('%s: no OAS operation for %s' % (node_id, url))
        else:
            for p in validate(oas, schema, body):
                err('%s: OAS: %s' % (node_id, p))
        for k, v in body.items():
            if isinstance(v, str) and PH.search(v):
                err('%s: unresolved placeholder in body.%s' % (node_id, k))
        sc, data = bank(tool, dict(body))
        rep['calls'].append(dict(node=node_id, tool=tool, body=body, status_code=sc))
        ok = sc is not None and sc < 400
        env = dict(status='success' if ok else 'error', data=data, status_code=sc,
                   message='Successfully executed POST request' if ok else 'Request failed')
        return ok, env

    def record(node_id, ok, env):
        vars_[node_id + '_success_count'] = int(vars_.get(node_id + '_success_count') or 0) + (1 if ok else 0)
        vars_[node_id + '_failure_count'] = int(vars_.get(node_id + '_failure_count') or 0) + (0 if ok else 1)
        vars_[node_id + '_status_code'] = env.get('status_code')
        for k in [k for k in vars_ if k.startswith(node_id + '_response.')]:
            del vars_[k]
        vars_.update(_flatten(node_id + '_response', env, dict()))

    def enter(nid):
        n = nodes.get(nid)
        if n is None:
            raise WalkError('transition to a missing node ' + str(nid))
        rep['entered'].append(nid)
        oe = n.get('on_enter') or dict()
        if oe.get('type') == 'tts':
            text, miss = _resolve(oe.get('text', ''), vars_)
            if miss:
                err('%s: unresolved placeholder in spoken text: %s' % (nid, miss))
            if not text.strip():
                err('%s: empty tts' % nid)
            speak(nid, text)
        elif oe.get('type') == 'llm':
            speak(nid, '<llm>')
        for a in n.get('pre_actions') or []:
            fn = a.get('function') or dict()
            if fn.get('name') == 'code_exec' or 'code_exec' in str(fn.get('handler')):
                code = ((fn.get('parameters') or dict()).get('properties') or dict()).get('code', dict()).get('default', '')
                if PH.search(code):
                    err('%s: {{...}} inside code_exec' % nid)
                try:
                    exec(compile(code, nid, 'exec'), dict(vars=vars_, __name__='hub'))
                    record(nid, True, dict(status='success', data=None, status_code=200, message='Code executed successfully'))
                except Exception as e:
                    err('%s: code raised %s: %s' % (nid, type(e).__name__, e))
                    record(nid, False, dict(status='error', data=None, status_code=500))
                if vars_.get('hub_error'):
                    err('%s: hub_error %s' % (nid, vars_.get('hub_error')))
                    vars_['hub_error'] = ''
                if nid == 'hub':
                    rep['hub'].append(dict(route=vars_.get('route'), say_next=vars_.get('say_next'), farewell=vars_.get('farewell'),
                                           close_outcome=vars_.get('close_outcome'), close_reason=vars_.get('close_reason')))
            else:
                ok, env = api(nid, fn, a.get('pre_process_code') or (a.get('config') or dict()).get('pre_process_code'))
                record(nid, ok, env)
                last_env[nid] = env
        for m in n.get('response_mapping') or []:      # node level, paths from the envelope (status, data, data.x)
            vars_[m['variable']] = _get(last_env.get(nid) or dict(), m['path'])
        return n

    last_env = dict()

    def route(nid, n):
        for tgt, cond in _merged(n.get('transitions')):
            if _cond(cond, vars_):
                return tgt
        return None

    def lifecycle():
        for t in wf.get('tools') or []:
            if 'end_of_call' in ((t.get('config') or dict()).get('alwaysRunsAt') or []):
                ok, env = api('lifecycle:' + t['function']['name'], t['function'], t.get('pre_process_code'))
                record(t['function']['name'], ok, env)

    nid = wf['initial_node']
    steps = 0
    try:
        n = enter(nid)
        while steps < max_steps:
            steps += 1
            if n.get('node_type') == 'end_call':
                rep['ended'] = True
                lifecycle()
                break
            if n.get('passthrough'):
                tgt = route(nid, n)
                if tgt is None:
                    err('%s: passthrough node with no matching transition (deadlock)' % nid)
                    break
                if nid == 'hub':       # the hub's decision must be the node it goes to
                    r = str(vars_.get('route') or '')
                    want = dict(say='exact_say', close='close_say').get(r, r)
                    if want in nodes and tgt != want:
                        err('hub: route=%s but the graph went to %s' % (r, tgt))
                nid = tgt
                n = enter(nid)
                continue
            # a conversation node: the next user message
            if not turn_spoke[0]:
                err('a turn without speech before node %s' % nid)
            if not events:
                rep['warnings'].append('script ended at node %s' % nid)
                break
            ev = events.pop(0)
            turn_spoke[0] = False
            for x in n.get('extraction_schema') or []:
                if x.get('name') == 'ev' and ev is not None:
                    v = re.sub(r'^n=[a-z0-9]*', 'n=' + str(vars_.get('ev_tok') or ''), ev)
                    if x.get('validation_pattern') and not re.match(x['validation_pattern'], v):
                        rep['warnings'].append('ev rejected by validation_pattern: ' + v)
                    else:
                        vars_['ev'] = v
            tgt = route(nid, n)
            if tgt is None:
                continue          # no match: stay in the node, wait for the next message
            nid = tgt
            n = enter(nid)
        else:
            err('step limit reached (a routing loop)')
    except WalkError as e:
        err(str(e))
    if not any(c['tool'] == 'close_call' for c in rep['calls']):
        err('the call never sent close_call')
    rep['vars'] = vars_
    return rep


def hub_actions(rep):
    """The hub's decisions as reducer-style actions (say_exact / speak_free / call_tool / close)."""
    out = []
    calls = [c for c in rep['calls'] if not c['node'].startswith('lifecycle:') and c['tool'] != 'close_call']
    ci = 0
    for h in rep['hub']:
        r = str(h.get('route') or '')
        if r == 'say':
            out.append(dict(type='say_exact', text=h.get('say_next')))
        elif r == 'close':
            out.append(dict(type='close', outcome=h.get('close_outcome'), reason=h.get('close_reason') or None, farewell=h.get('farewell')))
        elif r.startswith('t_'):
            c = calls[ci] if ci < len(calls) else dict(tool=r[2:], body=None)
            ci += 1
            out.append(dict(type='call_tool', tool=c['tool'], args=c['body']))
        elif r.startswith('talk_'):
            out.append(dict(type='speak_free', node=r))
        else:
            out.append(dict(type=r or 'none'))
    return out
