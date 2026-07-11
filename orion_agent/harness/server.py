"""Harness HTTP service — the endpoint the FreeCAD chat panel talks to.

Thin: it owns the long-lived agent stack (LLM client, bridge client, sandbox,
tool registry, agent loop, trajectory logger) and exposes ``POST /chat``. All
intelligence is in the agent loop; this just marshals one request through it
and logs the trajectory.

Falls back to a stdlib HTTP server if FastAPI/uvicorn are unavailable so the
service still runs in a minimal environment.
"""

# NOTE: deliberately NOT using ``from __future__ import annotations`` here.
# The FastAPI route below annotates its parameter with a Pydantic model defined
# in local scope; stringised annotations would make FastAPI unable to resolve
# it and treat the body as a query param (HTTP 422).

import json
from typing import Optional

from orion_agent.shared.config import get_config
from orion_agent.harness.llm import get_llm_client
from orion_agent.harness.bridge_client import BridgeClient
from orion_agent.harness.sandbox import SandboxManager
from orion_agent.harness.tools.registry import build_registry
from orion_agent.harness.agent.loop import AgentLoop
from orion_agent.harness.agent.verify import EditVerifier
from orion_agent.harness.context import ContextPacker
from orion_agent.harness.memory import MemoryStore
from orion_agent.harness.spec import SpecParser
from orion_agent.harness.trajectory_logger import TrajectoryLogger


class HarnessApp:
    """Assembles the agent stack once and serves chat turns."""

    def __init__(self, config=None):
        self.cfg = config or get_config()
        self.llm = get_llm_client(config=self.cfg)
        self.bridge = BridgeClient()
        self.sandbox = SandboxManager(self.cfg)
        self.registry = build_registry(self.bridge, self.sandbox)
        self.memory = MemoryStore()
        self.logger = TrajectoryLogger()
        self.loop = AgentLoop(
            self.llm,
            self.registry,
            bridge=self.bridge,
            config=self.cfg,
            verifier=EditVerifier(self.bridge),
            context_packer=ContextPacker(self.memory),
            spec_parser=SpecParser(self.llm),
        )

    def handle_chat(self, payload: dict) -> dict:
        message = (payload.get("message") or "").strip()
        if not message:
            return {"final_answer": "(empty message)", "tool_calls": [], "artifacts": []}
        session_id = payload.get("session_id", "")
        document = payload.get("document", "")
        if not document:
            # Resolve the open document so memory reads and writes share a key.
            try:
                document = self.bridge.get_document_state().get("name", "") or ""
            except Exception:  # noqa: BLE001
                document = ""
        images = payload.get("images") or []
        forced = payload.get("pillar")

        result = self.loop.run(
            message, session_id=session_id, document=document,
            images=images, forced_pillar=forced,
        )
        if result.trajectory is not None:
            self.logger.log(result.trajectory)
            self.memory.observe(session_id, document, message, result)
        return result.to_response()

    def health(self) -> dict:
        return {
            "status": "ok",
            "model": self.cfg.llm.model,
            "provider": self.cfg.llm.provider,
            "bridge_alive": self.bridge.is_alive(),
        }


# --------------------------------------------------------------------------- #
# FastAPI app (preferred) with stdlib fallback
# --------------------------------------------------------------------------- #


def create_fastapi_app(app_state: Optional[HarnessApp] = None):
    from fastapi import FastAPI
    from pydantic import BaseModel

    state = app_state or HarnessApp()
    api = FastAPI(title="OrionFlow Harness", version="0.1.0")

    class ChatIn(BaseModel):
        message: str
        session_id: str = ""
        document: str = ""
        images: list[str] = []
        pillar: Optional[str] = None

    @api.get("/health")
    def health():
        return state.health()

    @api.post("/chat")
    def chat(body: ChatIn):
        return state.handle_chat(body.model_dump())

    return api


def _run_stdlib(state: HarnessApp, host: str, port: int) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: A003
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                self._send(200, state.health())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/chat":
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, state.handle_chat(payload))

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[orion-harness] stdlib server on {host}:{port}")  # noqa: T201
    httpd.serve_forever()


def main() -> None:
    cfg = get_config()
    state = HarnessApp(cfg)
    host, port = cfg.harness.host, cfg.harness.port
    try:
        import uvicorn

        uvicorn.run(create_fastapi_app(state), host=host, port=port, log_level="info")
    except ImportError:
        _run_stdlib(state, host, port)


if __name__ == "__main__":
    main()
