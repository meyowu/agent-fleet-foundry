"""Authenticated, foreground-owned IPv4 loopback observer using packaged assets."""

from __future__ import annotations

import hmac
import io
import json
import secrets
import socket
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlsplit

from pydantic import JsonValue, TypeAdapter

from agent_fleet.application.dashboard import DashboardService
from agent_fleet.domain.dashboard import MAX_DASHBOARD_RESPONSE, DashboardCursors, checked_cursors
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import ArtifactId, Project, RunId

_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class DashboardServer(ThreadingMixIn, HTTPServer):
    """At most eight requests; timed sockets and streams; no HTTP request logging."""

    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, service: DashboardService, project: Project, *, port: int = 0) -> None:
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("dashboard port must be between 0 and 65535")
        self.service = service
        self.project = project
        self.token = secrets.token_urlsafe(32)
        self.stopping = threading.Event()
        self.slots = threading.BoundedSemaphore(8)
        self.connections: set[socket.socket] = set()
        self.connections_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.origin = f"http://127.0.0.1:{self.server_address[1]}"

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        if isinstance(request, socket.socket):
            with self.connections_lock:
                self.connections.add(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            if isinstance(request, socket.socket):
                with self.connections_lock:
                    self.connections.discard(request)
            self.slots.release()

    def handle_error(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        # Never dump request contents, token, repository data, or raw exceptions.
        del request, client_address

    def server_close(self) -> None:
        self.stopping.set()
        self.token = ""
        with self.connections_lock:
            for connection in self.connections:
                _interrupt_connection(connection)
        super().server_close()


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    raw_requestline: bytes
    protocol_version = "HTTP/1.0"  # one bounded request per connection
    server_version = "FleetObserver"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.header_deadline = threading.Timer(3, _interrupt_connection, (self.connection,))
        self.header_deadline.daemon = True
        self.header_deadline.start()

    def finish(self) -> None:
        self.header_deadline.cancel()
        super().finish()

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # BaseHTTPRequestHandler can reflect the attacker-controlled method/path.
        del message, explain
        self._json(code, {"error": "Request rejected."})

    def parse_request(self) -> bool:
        self.request_version = "HTTP/1.0"
        self.command = ""
        self.requestline = ""
        if len(self.raw_requestline) > 8192:
            self.request_version = "HTTP/1.0"
            self.command = ""
            self.send_error(414)
            return False
        # Bound bytes before the standard parser allocates/decodes the headers.
        # The absolute setup timer covers both the request line and slow headers.
        raw_headers = bytearray()
        while True:
            line = self.rfile.readline(4097)
            if not line or len(line) > 4096 or len(raw_headers) + len(line) > 16384:
                self.send_error(431)
                return False
            raw_headers.extend(line)
            if line in {b"\r\n", b"\n"}:
                break
        original = self.rfile
        try:
            self.rfile = io.BytesIO(raw_headers)
            return super().parse_request()
        finally:
            self.rfile = original
            self.header_deadline.cancel()

    def _headers(self, status: int, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()
        self.close_connection = True

    def _json(self, status: int, value: dict[str, JsonValue]) -> None:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self._headers(status, "application/json; charset=utf-8", len(payload))
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _boundary(self) -> bool:
        for name in ("Host", "Origin", "Authorization", "Content-Length", "X-Fleet-Cursors"):
            if len(self.headers.get_all(name, [])) > 1:
                self.send_error(400)
                return False
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            self.send_error(403)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            self.send_error(403)
            return False
        if self.headers.get("Sec-Fetch-Site") not in {None, "none", "same-origin"}:
            self.send_error(403)
            return False
        if self.headers.get("Content-Length", "0") != "0" or "Transfer-Encoding" in self.headers:
            self.send_error(400)
            return False
        return True

    def _authenticated(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        if (
            self.server.stopping.is_set()
            or not self.server.token
            or not hmac.compare_digest(
                authorization.encode("utf-8"), f"Bearer {self.server.token}".encode()
            )
        ):
            self._json(401, {"error": "Paste the current terminal access token to connect."})
            return False
        return True

    def do_GET(self) -> None:
        if not self._boundary():
            return
        try:
            self._get()
        except FleetError as error:
            # Use only the stable code, never arbitrary adapter messages/details.
            self._json(
                409, {"error": "Local state could not be verified.", "code": error.code.value}
            )
        except (ValueError, TypeError, KeyError):
            self.send_error(400)
        except (OSError, TimeoutError):
            self.close_connection = True

    def _get(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment or "%" in parsed.path:
            self.send_error(400)
            return
        if parsed.path in _ASSETS:
            if parsed.query:
                self.send_error(400)
                return
            name, content_type = _ASSETS[parsed.path]
            payload = files("agent_fleet.assets").joinpath("dashboard", name).read_bytes()
            self._headers(200, content_type, len(payload))
            self.wfile.write(payload)
            return
        if not self._authenticated():
            return
        query = parse_qs(
            parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=1
        )
        if parsed.path == "/api/catalog":
            if set(query) - {"before"}:
                raise ValueError("unknown query")
            before = int(query["before"][0]) if "before" in query else None
            self._json(200, self.server.service.catalog(self.server.project, before=before))
            return
        if query:
            raise ValueError("unknown query")
        parts = parsed.path.split("/")
        if len(parts) < 4 or parts[1:3] != ["api", "runs"]:
            self.send_error(404)
            return
        run_id = TypeAdapter(RunId).validate_python(parts[3])
        raw_cursors = self.headers.get("X-Fleet-Cursors")
        cursors = checked_cursors(json.loads(raw_cursors)) if raw_cursors is not None else None
        if len(parts) == 4:
            self._json(200, self.server.service.frame(self.server.project, run_id, cursors=cursors))
        elif len(parts) == 5 and parts[4] == "events":
            self._stream(run_id, cursors)
        elif len(parts) == 6 and parts[4] == "artifacts":
            artifact_id = TypeAdapter(ArtifactId).validate_python(parts[5])
            self._json(200, self.server.service.artifact(self.server.project, run_id, artifact_id))
        else:
            self.send_error(404)

    def _stream(self, run_id: str, cursors: DashboardCursors | None) -> None:
        frame = self.server.service.frame(self.server.project, run_id, cursors=cursors)
        self._headers(200, "text/event-stream; charset=utf-8")
        deadline = time.monotonic() + 10
        last_revision: JsonValue = None
        emitted_bytes = 0
        while not self.server.stopping.is_set():
            if frame["revision"] != last_revision:
                payload = json.dumps(frame, ensure_ascii=False, allow_nan=False).encode()
                emitted_bytes += len(payload)
                if (
                    len(payload) > MAX_DASHBOARD_RESPONSE
                    or emitted_bytes > 4 * MAX_DASHBOARD_RESPONSE
                ):
                    break
                self.wfile.write(b"event: snapshot\ndata: " + payload + b"\n\n")
                last_revision = frame["revision"]
            else:
                self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()
            cursors = checked_cursors(frame["cursors"])
            if time.monotonic() >= deadline or self.server.stopping.wait(0.5):
                break
            try:
                frame = self.server.service.frame(self.server.project, run_id, cursors=cursors)
            except (FleetError, ValueError, TypeError, KeyError):
                self.wfile.write(
                    b'event: unavailable\ndata: {"error":"Local state could not be verified."}\n\n'
                )
                self.wfile.flush()
                break

    def _method_denied(self) -> None:
        self._json(405, {"error": "This dashboard is read-only. Use the trusted terminal."})

    do_POST = _method_denied
    do_PUT = _method_denied
    do_PATCH = _method_denied
    do_DELETE = _method_denied
    do_OPTIONS = _method_denied
    do_HEAD = _method_denied


def _interrupt_connection(connection: socket.socket) -> None:
    # Already closed by the peer or the request owner is harmless.
    with suppress(OSError):
        connection.shutdown(socket.SHUT_RDWR)
