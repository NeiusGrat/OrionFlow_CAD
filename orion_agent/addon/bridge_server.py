"""Bridge server: the addon-side RPC endpoint the harness calls.

JSON over localhost HTTP. Bound to ``127.0.0.1`` by default with an explicit
allow-list (mirroring the ``neka-nat/freecad-mcp`` allowed-IP model); remote
access is opt-in only. Every capability is marshalled onto FreeCAD's GUI thread
through :mod:`orion_agent.addon.task_queue`, so the HTTP worker threads never
touch geometry directly.

Works both with a GUI (workbench command starts it) and headless
(``freecadcmd`` console), which is what the eval harness and CI drive.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from orion_agent.shared.contract import (
    BridgeRequest,
    BridgeResponse,
    ErrorCode,
)
from orion_agent.shared.config import get_config
from orion_agent.addon.capabilities import Capabilities, CapabilityError
from orion_agent.addon.task_queue import get_task_queue, format_exc


class _Handler(BaseHTTPRequestHandler):
    server_version = "OrionBridge/1.0"

    # quiet the default stderr logging
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _client_allowed(self) -> bool:
        allow = self.server.allow_list  # type: ignore[attr-defined]
        return self.client_address[0] in allow

    def _write(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - health probe
        if self.path == "/health":
            self._write(200, {"status": "ok", "service": "orion-bridge"})
        else:
            self._write(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._client_allowed():
            self._write(403, BridgeResponse.failure(
                ErrorCode.NOT_PERMITTED, "client not in allow-list").to_dict())
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            req = BridgeRequest.from_dict(json.loads(raw.decode("utf-8")))
        except Exception as exc:  # noqa: BLE001
            self._write(400, BridgeResponse.failure(
                ErrorCode.BAD_REQUEST, f"malformed request: {exc}").to_dict())
            return

        caps: Capabilities = self.server.capabilities  # type: ignore[attr-defined]
        queue = get_task_queue()
        timeout = self.server.task_timeout  # type: ignore[attr-defined]

        try:
            result = queue.submit(
                lambda: caps.dispatch(req.capability, req.params), timeout=timeout
            )
            resp = BridgeResponse.success(result, request_id=req.request_id)
        except CapabilityError as exc:
            resp = BridgeResponse.failure(exc.code, exc.message, request_id=req.request_id)
        except TimeoutError:
            resp = BridgeResponse.failure(
                ErrorCode.GUI_TIMEOUT,
                f"capability {req.capability} timed out after {timeout}s",
                request_id=req.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            resp = BridgeResponse.failure(
                ErrorCode.INTERNAL, format_exc(exc), request_id=req.request_id
            )
        self._write(200, resp.to_dict())


class BridgeServer:
    """Lifecycle wrapper around a ThreadingHTTPServer."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        allow_list: Optional[tuple[str, ...]] = None,
        task_timeout: Optional[float] = None,
        capabilities: Optional[Capabilities] = None,
    ):
        cfg = get_config()
        self.host = host or cfg.bridge.host
        self.port = port or cfg.bridge.port
        self.allow_list = set(allow_list or cfg.bridge.allow_list)
        self.task_timeout = task_timeout or cfg.bridge.request_timeout
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        # Injectable so the bridge can be exercised with a mock (no FreeCAD).
        self.capabilities = capabilities or Capabilities()

    def start(self) -> str:
        if self._httpd is not None:
            return f"already running on {self.host}:{self.port}"
        httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        httpd.allow_list = self.allow_list           # type: ignore[attr-defined]
        httpd.capabilities = self.capabilities        # type: ignore[attr-defined]
        httpd.task_timeout = self.task_timeout         # type: ignore[attr-defined]
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever, name="orion-bridge", daemon=True
        )
        self._thread.start()
        return f"OrionFlow bridge listening on {self.host}:{self.port}"

    def stop(self) -> str:
        if self._httpd is None:
            return "not running"
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None
        return "OrionFlow bridge stopped"

    @property
    def running(self) -> bool:
        return self._httpd is not None


# Module-level singleton used by both the workbench command and headless start.
_SERVER: Optional[BridgeServer] = None


def get_server() -> BridgeServer:
    global _SERVER
    if _SERVER is None:
        _SERVER = BridgeServer()
    return _SERVER


def start_bridge() -> str:
    return get_server().start()


def stop_bridge() -> str:
    return get_server().stop()


def serve_headless() -> None:
    """Entry point for ``freecadcmd``: start the bridge and block forever.

    Headless has no Qt event loop, so the task queue runs capabilities inline.
    """
    msg = start_bridge()
    print(f"[orion] {msg}")  # noqa: T201 - console feedback in headless mode
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print(f"[orion] {stop_bridge()}")  # noqa: T201
