"""Measure the hub code-node size and what a lossless minification (AST round-trip: no comments, no docstrings) and a
leaner policy literal would save; plus the variable payload of the failed call.
    python3 tests/measure_hub.py <workflow export> [call json]"""
import ast, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

wf = json.load(open(sys.argv[1]))
wf = wf.get("workflow", wf)
code = wf["nodes"]["hub"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]


def strip_docs(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) and \
                isinstance(node.body[0].value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


mini = ast.unparse(strip_docs(ast.parse(code)))
lit_start = code.find("POLICY = json.loads(")
print(f"hub code {len(code)/1024:.1f} KB; minified {len(mini)/1024:.1f} KB; policy literal {len(code) - lit_start if lit_start > 0 else 0:,} bytes")
if len(sys.argv) > 2:
    c = json.load(open(sys.argv[2]))
    vt = {}
    for m in c.get("messages") or []:
        vt.update({k: x.get("value") for k, x in ((m.get("workflowSnapshot") or {}).get("variableTable") or {}).items()})
    sizes = sorted(((len(json.dumps(v, default=str)), k) for k, v in vt.items()), reverse=True)
    print(f"variables at the end: {sum(s for s, _ in sizes)/1024:.1f} KB in {len(sizes)} vars; largest:")
    for s, k in sizes[:12]:
        print(f"   {s:>7,}  {k}")
