"""PiNuke HTTP service with opt-in, verified DSP editing."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .device import readback, scan
from .controls import SPECS, EditValidationError, apply_changes, revision, validate_changes
from .telemetry import MeterStream, load_calibration

STATIC = Path(__file__).with_name("static")
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/graphs.js": ("graphs.js", "text/javascript; charset=utf-8"),
    "/meters.js": ("meters.js", "text/javascript; charset=utf-8"),
    "/presence.js": ("presence.js", "text/javascript; charset=utf-8"),
    "/pip.js": ("pip.js", "text/javascript; charset=utf-8"),
    "/pip-zone.css": ("pip-zone.css", "text/css; charset=utf-8"),
    "/pip.css": ("pip.css", "text/css; charset=utf-8"),
}


def make_handler(reader=readback, scanner=scan, public_origin: str | None = None,
                 enable_edits=False, writer=apply_changes, audit_dir=None,
                 enable_meters=False, meter_calibration=None, meter_stream=None):
    if public_origin:
        parsed = urlsplit(public_origin)
        if (parsed.scheme not in ("http", "https") or not parsed.netloc
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("public origin must be an http(s) scheme and host without a path")
        public_origin = f"{parsed.scheme}://{parsed.netloc}"
    state = {"snapshot": None, "error": None, "revision": None}
    device_lock = threading.Lock()
    meters = meter_stream or MeterStream(device_lock, enabled=enable_meters,
                                         calibration=load_calibration(meter_calibration))

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            # Same-origin homepage dialog embeds the editor; foreign framing blocked.
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, value: object) -> None:
            self._send(status, json.dumps(value).encode("utf-8"), "application/json")

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/controls":
                self._json(200, {"enabled": enable_edits, "groups": SPECS})
            elif path == "/api/state":
                self._json(200, state)
            elif path == "/api/availability":
                # Leased discovery: actual /info responses, not stale meters.
                self._json(200, meters.availability(touch=True))
            elif path == "/api/availability-state":
                self._json(200, meters.availability())
            elif path == "/api/meters":
                view = meters.snapshot(touch=True)
                snap = state["snapshot"]
                same_amp = (snap and snap["usb"].get("serial") and view.get("identity")
                            and snap["usb"]["serial"] == view["identity"].get("serial")
                            and snap["info"].get("firmware") == view["identity"].get("firmware"))
                view["threshold_vp"] = {f"output_{'a' if ch == '1' else 'b'}": values["limiter"]["threshold_vp"]
                                        for ch, values in snap["channels"].items()} if same_amp and state["revision"] else None
                self._json(200, view)
            elif path == "/api/meter-state":
                # Fixed read-only observability may use this cached endpoint.
                # It never creates/renews a viewer lease or opens USB.
                self._json(200, meters.snapshot())
            elif path == "/api/scan":
                try:
                    self._json(200, {"devices": scanner()})
                except Exception as exc:
                    self._json(503, {"error": str(exc)})
            elif path in FILES:
                name, content_type = FILES[path]
                self._send(200, (STATIC / name).read_bytes(), content_type)
            else:
                self._json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path not in ("/api/readback", "/api/apply"):
                self._json(404, {"error": "Not found"})
                return
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            expected_origin = public_origin or f"http://{host}"
            if (origin and origin != expected_origin) or (path == "/api/apply" and origin != expected_origin):
                self._json(403, {"error": "Page origin does not match PiNuke"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 32768 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Invalid request size")
                if path == "/api/readback" and length:
                    raise ValueError("This request takes no data")
                if path == "/api/apply":
                    if not enable_edits:
                        self._json(403, {"error": "Editing is not enabled on this service"})
                        return
                    if self.headers.get_content_type() != "application/json" or not length:
                        raise ValueError("Apply requires JSON")
                    # Avoid blocking a worker forever on a truncated request.
                    self.connection.settimeout(5)
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("Incomplete request")
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or set(payload) != {"revision", "changes"}:
                        raise ValueError("Apply requires a read revision and changed controls")
                    if not isinstance(payload["revision"], str):
                        raise ValueError("Invalid read revision")
                    changes = validate_changes(payload["changes"])
            except (ValueError, OSError) as exc:
                self._json(400, {"error": str(exc)})
                return
            with meters.exclusive():
                if path == "/api/apply":
                    if not state["revision"] or payload["revision"] != state["revision"]:
                        self._json(409, {"error": "Read the amplifier again before applying changes"})
                        return
                    before = state["snapshot"]
                    # Invalidate the old revision even if the writer fails after sending.
                    state["revision"] = None
                    try:
                        result = writer(before, changes, audit_dir=audit_dir)
                        if result.get("snapshot") is not None:
                            state["snapshot"] = result["snapshot"]
                        state["error"] = result.get("error")
                        if result["complete"]:
                            state["revision"] = revision(state["snapshot"])
                        self._json(200 if result["complete"] else 502, {**state, "complete": result["complete"],
                                   "verified": result.get("verified", []), "attempted": result.get("attempted", [])})
                    except Exception as exc:
                        state["error"] = f"Apply failed: {exc}. Read the amp before continuing."
                        self._json(503, state)
                    return
                try:
                    fresh = reader()
                    state["revision"] = revision(fresh)
                    state["snapshot"] = fresh
                    state["error"] = None
                    self._json(200, state)
                except Exception as exc:
                    state["revision"] = None
                    state["error"] = str(exc)
                    self._json(503, state)

        def log_message(self, format: str, *args: object) -> None:
            print(f"PiNuke {self.address_string()}: {format % args}")

    Handler.meters = meters
    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, public_origin: str | None = None,
          enable_edits=False, audit_dir=None, enable_meters=False, meter_calibration=None) -> None:
    handler = make_handler(public_origin=public_origin, enable_edits=enable_edits, audit_dir=audit_dir,
                           enable_meters=enable_meters, meter_calibration=meter_calibration)
    try:
        with ThreadingHTTPServer((host, port), handler) as server:
            print(f"PiNuke listening at http://{host}:{port}/")
            server.serve_forever()
    finally:
        handler.meters.close()
