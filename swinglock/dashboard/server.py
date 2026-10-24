"""Tiny read-only HTTP server for the live dashboard.

Serves the static page from `static/` and the scanner's state file at `/state.json`.
The state file is re-read on every request, so the page always shows what the scanner
last wrote. Nothing here talks to a venue API or places orders.
"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_STATE = Path(__file__).parent / "sample_state.json"

_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "swinglock-dashboard"

    def __init__(self, *args, state_path: Path, **kwargs):
        self.state_path = state_path
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?", 1)[0]
        if path == "/state.json":
            self._send_state()
        elif path in _STATIC_FILES:
            name, ctype = _STATIC_FILES[path]
            self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), ctype)
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def _send_state(self) -> None:
        try:
            raw = self.state_path.read_bytes()
        except FileNotFoundError:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE,
                            {"error": f"state file not found: {self.state_path}"})
            return
        except OSError as exc:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": f"cannot read state file: {exc}"})
            return
        try:
            json.loads(raw)
        except ValueError as exc:
            # The scanner may be mid-write; the page keeps its last good copy.
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": f"state file is not valid JSON: {exc}"})
            return
        self._send(HTTPStatus.OK, raw, "application/json")

    def _send_json(self, status: HTTPStatus, obj: dict) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _send(self, status: HTTPStatus, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        pass  # quiet: the page polls every few seconds


def make_server(state_path: str | Path, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    handler = partial(DashboardHandler, state_path=Path(state_path))
    return ThreadingHTTPServer((host, port), handler)
