"""Final entry point: case folder + deployed mock URL -> submitted Freya workflow.

The mock must expose its OpenAPI document at GET /openapi.json.  This wrapper
pins every OpenAPI server to that mock, stores the exact contract beside the
submission, then runs the frozen builder unchanged.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_OPENAPI_BYTES = 5 * 1024 * 1024


def normalize_mock_url(value):
    value = value.rstrip("/")
    p = urllib.parse.urlsplit(value)
    local = p.hostname in {"localhost", "127.0.0.1", "::1"}
    if p.scheme not in ({"http", "https"} if local else {"https"}) or not p.netloc:
        raise ValueError("mock_url must be HTTPS (HTTP is allowed only for localhost)")
    if p.username or p.password or p.query or p.fragment:
        raise ValueError("mock_url must not contain credentials, a query or a fragment")
    return value


def _pin_servers(node, mock_url):
    if isinstance(node, list):
        return [_pin_servers(x, mock_url) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _pin_servers(v, mock_url) for k, v in node.items()}
    if "servers" in out:
        out["servers"] = [{"url": mock_url}]
    return out


def fetch_openapi(mock_url):
    mock_url = normalize_mock_url(mock_url)
    req = urllib.request.Request(mock_url + "/openapi.json", headers={"User-Agent": "build-the-builder-final"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(MAX_OPENAPI_BYTES + 1)
    if len(raw) > MAX_OPENAPI_BYTES:
        raise ValueError("mock OpenAPI is larger than 5 MiB")
    try:
        spec = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"mock /openapi.json is not valid JSON: {e}") from None
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict) or not spec["paths"]:
        raise ValueError("mock /openapi.json must contain at least one path")
    spec = _pin_servers(spec, mock_url)
    spec["servers"] = [{"url": mock_url}]
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case_folder")
    ap.add_argument("mock_url")
    ap.add_argument("--slot", default="final")
    a, extra = ap.parse_known_args()
    if not os.path.isdir(a.case_folder):
        ap.error("case_folder must be a directory")
    try:
        mock_url = normalize_mock_url(a.mock_url)
        spec = fetch_openapi(mock_url)
    except Exception as e:
        ap.error(str(e))

    submission = os.path.join(ROOT, "submission")
    os.makedirs(submission, exist_ok=True)
    openapi_path = os.path.join(submission, f"{a.slot}.openapi.json")
    with open(openapi_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
        f.write("\n")

    extra = extra[1:] if extra[:1] == ["--"] else extra
    cmd = [sys.executable, os.path.join(ROOT, "builder", "build.py"), os.path.abspath(a.case_folder), openapi_path,
           "--slot", a.slot, *extra]
    print(json.dumps({"final_input": os.path.abspath(a.case_folder), "mock_url": mock_url,
                      "openapi": openapi_path, "builder_command": cmd}, ensure_ascii=False), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
