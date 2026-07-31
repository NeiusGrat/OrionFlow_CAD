"""OrionFlow as an MCP server: one model, one tool surface, any client.

The engineering intelligence lives in three places that had no common door —
the fine-tuned Blueprint adapter, the knowledge assets under
``orion_agent/knowledge``, and the deterministic calculators in ``orion.calc``.
The studio reached some of it, the FreeCAD copilot reached a different some of
it, and nothing outside the repo reached any of it.

This exposes all of it over the Model Context Protocol, so Claude Desktop, an
IDE, or any other MCP client can design a part that proves itself, quote a NASA
clause, size a bolt, or check a wall thickness — through the same code paths the
products use, not a reimplementation.

Three groups of tools:

* ``design_part`` — a request in, a part built in FreeCAD and graded against the
  closed-form volume the model predicted for it. The verdict is the point: the
  answer says whether the geometry proved itself, not merely that a file exists.
* **knowledge** — ISO/DIN, the NASA requirement graph, materials, sheet-metal
  DFM, robotics components, assembly validation. No FreeCAD needed.
* **calculators** — beam bending, bearing life, thread engagement, thermal
  growth, mass properties, Pappus. Deterministic Python; the model never does
  arithmetic.

Geometry *editing* is deliberately absent. Those tools need a live FreeCAD
document over a localhost bridge, which is the desktop copilot's job; an MCP
client has no document to edit.

Run::

    python -m orion_agent.mcp_server            # stdio, for Claude Desktop
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Optional

log = logging.getLogger("orionflow.mcp")

SERVER_NAME = "orionflow"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


# --------------------------------------------------------------------------- #
# tool surface
# --------------------------------------------------------------------------- #
def _load_env() -> None:
    """The endpoint key, from .env, in-process. Never reaches a shell."""
    if os.environ.get("ORION_LLM_API_KEY"):
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("ORION_LLM_API_KEY="):
                os.environ["ORION_LLM_API_KEY"] = line.split("=", 1)[1].strip()
                return


def build_surface() -> tuple[Any, list[dict]]:
    """``(registry, schemas)`` — knowledge + design + calculators.

    Built from the same registry the products use rather than a parallel list,
    so a tool cannot exist here in a form it does not have there.
    """
    from orion_agent.harness.tools.registry import build_knowledge_registry

    registry = build_knowledge_registry()
    schemas = [s["function"] for s in registry.schemas()]

    from app.services.planner import calculator_tools

    calc_schemas = [s["function"] for s in calculator_tools()]
    return registry, schemas + calc_schemas


def call_tool(registry, name: str, arguments: dict) -> tuple[str, bool]:
    """``(text, is_error)`` for one tool call."""
    if name.startswith("calc_"):
        from app.services.planner import _run_calculator

        out = _run_calculator(name, arguments)
        return out, out.startswith("calculator error")
    result = registry.execute(name, arguments or {})
    return result.content, not result.ok


# --------------------------------------------------------------------------- #
# protocol
# --------------------------------------------------------------------------- #
class MCPServer:
    """Line-delimited JSON-RPC 2.0 over stdio.

    Implemented directly rather than against an SDK: the surface is three
    methods, and a dependency that has to be installed before the CAD stack can
    be reached from a client is a worse trade than sixty lines of dispatch.
    """

    def __init__(self) -> None:
        _load_env()
        self.registry, self.schemas = build_surface()
        log.info("orionflow mcp: %d tools", len(self.schemas))

    # ------------------------------------------------------------------ #
    def handle(self, request: dict) -> Optional[dict]:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME,
                                   "version": SERVER_VERSION},
                }
            elif method in ("notifications/initialized", "initialized"):
                return None                      # notification: no reply
            elif method == "tools/list":
                result = {"tools": [
                    {"name": s["name"], "description": s["description"],
                     "inputSchema": s["parameters"]}
                    for s in self.schemas]}
            elif method == "tools/call":
                text, is_error = call_tool(self.registry,
                                           params.get("name", ""),
                                           params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}],
                          "isError": is_error}
            elif method == "ping":
                result = {}
            else:
                return self._error(request_id, -32601,
                                   f"method not found: {method}")
        except Exception as exc:  # noqa: BLE001 — a bad call must not kill the server
            log.exception("mcp call failed")
            return self._error(request_id, -32603, str(exc))

        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": code, "message": message}}

    # ------------------------------------------------------------------ #
    def serve_stdio(self) -> int:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                sys.stdout.write(json.dumps(
                    self._error(None, -32700, "parse error")) + "\n")
                sys.stdout.flush()
                continue
            response = self.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        return 0


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    if "--list" in argv:                       # inspection without a client
        _, schemas = build_surface()
        for s in schemas:
            args = ", ".join((s.get("parameters") or {}).get("properties", {}))
            print(f"{s['name']:32s} ({args})")
        print(f"\n{len(schemas)} tools")
        return 0
    return MCPServer().serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
