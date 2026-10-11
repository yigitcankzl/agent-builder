"""Offline checks for builder/final.py. No Freya, model or internet calls."""
import json
import os
import sys
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from builder.final import fetch_openapi, normalize_mock_url
import builder.final as final


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({
            "openapi": "3.0.3",
            "servers": [{"url": "https://wrong.invalid"}],
            "paths": {"/write": {"post": {"servers": [{"url": "https://also-wrong.invalid"}],
                                                "responses": {"200": {"description": "ok"}}}}},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("ok", message)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        spec = fetch_openapi(url)
        check(spec["servers"] == [{"url": url}], "root server pinned to the submitted mock")
        check(spec["paths"]["/write"]["post"]["servers"] == [{"url": url}], "operation server cannot escape the mock")
        for bad in ("http://example.com", "https://user:pass@example.com", "https://example.com?q=1"):
            try:
                normalize_mock_url(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"unsafe mock URL accepted: {bad}")
        print("ok unsafe mock URLs refused")
        with tempfile.TemporaryDirectory() as tmp:
            case = os.path.join(tmp, "case")
            os.mkdir(case)
            old_root = final.ROOT
            final.ROOT = tmp
            try:
                with mock.patch.object(final, "fetch_openapi", return_value=spec), \
                     mock.patch.object(final.subprocess, "run", return_value=mock.Mock(returncode=0)) as run, \
                     mock.patch.object(sys, "argv", ["final.py", case, "https://mock.example", "--slot", "chosen",
                                                     "--", "--mock-freya", "--no-l3"]):
                    check(final.main() == 0, "wrapper returns the builder exit code")
                    command = run.call_args.args[0]
                    check(command[command.index("--slot") + 1] == "chosen", "wrapper slot is parsed before builder arguments")
                    check(command[-2:] == ["--mock-freya", "--no-l3"], "builder arguments are forwarded after --")
            finally:
                final.ROOT = old_root
    finally:
        server.shutdown()
        server.server_close()
