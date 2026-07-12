"""Harness-side client for the addon bridge.

Thin, typed wrapper over the JSON/HTTP bridge contract with retries, timeouts
and typed errors. One method per capability so call sites read naturally and a
contract rename surfaces as an import/attribute error rather than a silent miss.

Uses stdlib ``urllib`` (localhost, small JSON payloads) so the client has no
third-party dependency and is trivially mockable in tests.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from orion_agent.shared.config import get_config
from orion_agent.shared.contract import (
    BridgeError,
    BridgeRequest,
    BridgeResponse,
    Capability,
    ErrorCode,
)


class BridgeClient:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
    ):
        cfg = get_config()
        self.host = host or cfg.bridge.host
        self.port = port or cfg.bridge.port
        self.timeout = timeout or cfg.bridge.request_timeout
        self.retries = retries if retries is not None else cfg.bridge.connect_retries
        self._url = f"http://{self.host}:{self.port}/"

    # ------------------------------------------------------------------ #
    def _call(self, capability: str, params: Optional[dict] = None) -> Any:
        req = BridgeRequest(capability=capability, params=params or {})
        data = json.dumps(req.to_dict()).encode("utf-8")
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(
                    self._url, data=data, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                response = BridgeResponse.from_dict(body)
                if not response.ok:
                    raise BridgeError(response.error_code, response.error_message)
                return response.result
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise BridgeError(
                    ErrorCode.INTERNAL,
                    f"cannot reach bridge at {self._url}: {exc}",
                ) from exc
        raise BridgeError(ErrorCode.INTERNAL, str(last_exc))

    # ---- liveness ------------------------------------------------------ #
    def ping(self) -> dict:
        return self._call(Capability.PING)

    def is_alive(self) -> bool:
        """Fast liveness probe.

        Deliberately does NOT go through :meth:`_call` — that uses the full
        ``request_timeout`` (120s) with several retry sleeps, so a *down* bridge
        would make this block ~10s (each refused localhost connect can take ~2s
        on Windows). A liveness check must be cheap, so we do a single short
        socket connect; if the port is open we confirm with one quick ping.
        """
        import socket

        try:
            with socket.create_connection((self.host, self.port), timeout=0.6):
                pass
        except OSError:
            return False
        try:
            request = urllib.request.Request(
                self._url,
                data=json.dumps(
                    BridgeRequest(capability=Capability.PING).to_dict()
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=2.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return bool(BridgeResponse.from_dict(body).ok)
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def get_capabilities(self) -> dict:
        return self._call(Capability.GET_CAPABILITIES)

    # ---- read ---------------------------------------------------------- #
    def get_document_state(self) -> dict:
        return self._call(Capability.GET_DOCUMENT_STATE)

    def list_objects(self) -> dict:
        return self._call(Capability.LIST_OBJECTS)

    def get_object_parameters(self, name: str) -> dict:
        return self._call(Capability.GET_OBJECT_PARAMETERS, {"name": name})

    def inspect_topology(self, name: Optional[str] = None) -> dict:
        return self._call(Capability.INSPECT_TOPOLOGY, {"name": name})

    def measure(self, a: dict, b: dict) -> dict:
        return self._call(Capability.MEASURE, {"a": a, "b": b})

    def render_views(self, views: Optional[list] = None, out_dir: Optional[str] = None) -> dict:
        return self._call(Capability.RENDER_VIEWS, {"views": views, "out_dir": out_dir})

    def get_model_tier(self) -> dict:
        return self._call(Capability.GET_MODEL_TIER)

    def extract_featuregraph(self) -> dict:
        return self._call(Capability.EXTRACT_FEATUREGRAPH)

    # ---- mutate -------------------------------------------------------- #
    def begin_transaction(self, label: str = "OrionFlow edit") -> dict:
        return self._call(Capability.BEGIN_TRANSACTION, {"label": label})

    def commit_transaction(self) -> dict:
        return self._call(Capability.COMMIT_TRANSACTION)

    def abort_transaction(self) -> dict:
        return self._call(Capability.ABORT_TRANSACTION)

    def set_parameter(self, name: str, property: str, value: Any) -> dict:  # noqa: A002
        return self._call(
            Capability.SET_PARAMETER, {"name": name, "property": property, "value": value}
        )

    def edit_feature(self, name: str, properties: dict) -> dict:
        return self._call(Capability.EDIT_FEATURE, {"name": name, "properties": properties})

    def import_shape(self, path: str, label: str = "OrionResult",
                     replace: Optional[str] = None,
                     source_code: Optional[str] = None) -> dict:
        params: dict = {"path": path, "label": label, "replace": replace}
        if source_code:
            params["source_code"] = source_code
        return self._call(Capability.IMPORT_SHAPE, params)

    def compile_featuregraph(self, graph: dict) -> dict:
        return self._call(Capability.COMPILE_FEATUREGRAPH, {"graph": graph})

    def compile_assembly_graph(
        self,
        graph: dict,
        bindings: dict[str, str],
        root_part_id: str,
        joint_values: Optional[dict[str, float]] = None,
        label: Optional[str] = None,
    ) -> dict:
        """Compile an explicit AssemblyGraph into linked FreeCAD occurrences.

        ``bindings`` intentionally maps each graph part instance to an existing
        FreeCAD source object by name.  The bridge never guesses source objects
        from a part number, graph id, or label.
        """
        return self._call(
            Capability.COMPILE_ASSEMBLY_GRAPH,
            {
                "graph": graph,
                "bindings": bindings,
                "root_part_id": root_part_id,
                # ``None`` is semantically distinct from an empty object: the
                # compiler may apply its documented neutral-pose default only
                # when the caller omitted a configuration altogether.
                "joint_values": joint_values,
                "label": label,
            },
        )

    def select(self, refs: list) -> dict:
        return self._call(Capability.SELECT, {"refs": refs})

    def undo(self) -> dict:
        return self._call(Capability.UNDO)

    def redo(self) -> dict:
        return self._call(Capability.REDO)

    def export(self, path: str, names: Optional[list] = None) -> dict:
        return self._call(Capability.EXPORT, {"path": path, "names": names})
