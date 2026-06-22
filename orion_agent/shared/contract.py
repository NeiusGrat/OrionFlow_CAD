"""The versioned bridge contract between the FreeCAD addon and the harness.

This is the single source of truth for capability names, the request/response
envelope, and the error taxonomy. Both halves import these constants so a
rename can never silently desync the two processes.

Transport is JSON over localhost HTTP (see ``orion_agent.addon.bridge_server``
and ``orion_agent.harness.bridge_client``). The envelope is transport-agnostic
on purpose so the transport can change without touching call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

CONTRACT_VERSION = "1.0"


class Capability:
    """Stable capability names exposed by the addon bridge.

    Read capabilities ship first (Phase 1); mutating ones are gated by pillar
    and always marshalled onto FreeCAD's GUI thread inside the addon.
    """

    # --- liveness / meta ---------------------------------------------------
    PING = "ping"
    GET_CAPABILITIES = "get_capabilities"

    # --- read (Phase 1) ----------------------------------------------------
    GET_DOCUMENT_STATE = "get_document_state"
    LIST_OBJECTS = "list_objects"
    GET_OBJECT_PARAMETERS = "get_object_parameters"
    INSPECT_TOPOLOGY = "inspect_topology"
    MEASURE = "measure"
    RENDER_VIEWS = "render_views"
    GET_MODEL_TIER = "get_model_tier"

    # --- mutate (Phase 2/5) ------------------------------------------------
    SET_PARAMETER = "set_parameter"
    EDIT_FEATURE = "edit_feature"
    EXECUTE_CODE = "execute_code"          # import sandbox artifact into doc
    IMPORT_SHAPE = "import_shape"
    SELECT = "select"
    HIGHLIGHT = "highlight"
    UNDO = "undo"
    REDO = "redo"
    EXPORT = "export"
    BEGIN_TRANSACTION = "begin_transaction"
    COMMIT_TRANSACTION = "commit_transaction"
    ABORT_TRANSACTION = "abort_transaction"

    READ_ONLY = frozenset(
        {
            PING,
            GET_CAPABILITIES,
            GET_DOCUMENT_STATE,
            LIST_OBJECTS,
            GET_OBJECT_PARAMETERS,
            INSPECT_TOPOLOGY,
            MEASURE,
            RENDER_VIEWS,
            GET_MODEL_TIER,
        }
    )

    ALL = READ_ONLY | frozenset(
        {
            SET_PARAMETER,
            EDIT_FEATURE,
            EXECUTE_CODE,
            IMPORT_SHAPE,
            SELECT,
            HIGHLIGHT,
            UNDO,
            REDO,
            EXPORT,
            BEGIN_TRANSACTION,
            COMMIT_TRANSACTION,
            ABORT_TRANSACTION,
        }
    )


class ModelTier:
    """The §4 classification that the pillar router consumes."""

    CODE_NATIVE = "A"        # Build123d source of truth attached -> Modify first
    FEATURE_TREE = "B"       # live PartDesign/Sketch history, no source code
    DUMB_BREP = "C"          # imported STEP/IGES solid, no history/params
    EMPTY = "empty"          # no document / blank document
    UNKNOWN = "unknown"


class ErrorCode:
    """Bridge error taxonomy. The harness maps these to typed exceptions."""

    OK = "ok"
    UNKNOWN_CAPABILITY = "unknown_capability"
    BAD_REQUEST = "bad_request"
    NO_DOCUMENT = "no_document"
    OBJECT_NOT_FOUND = "object_not_found"
    RECOMPUTE_FAILED = "recompute_failed"
    GUI_TIMEOUT = "gui_timeout"
    NOT_PERMITTED = "not_permitted"
    INTERNAL = "internal"


@dataclass
class BridgeRequest:
    capability: str
    params: dict[str, Any] = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION
    request_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "params": self.params,
            "contract_version": self.contract_version,
            "request_id": self.request_id,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BridgeRequest":
        return BridgeRequest(
            capability=d.get("capability", ""),
            params=d.get("params", {}) or {},
            contract_version=d.get("contract_version", CONTRACT_VERSION),
            request_id=d.get("request_id"),
        )


@dataclass
class BridgeResponse:
    ok: bool
    result: Any = None
    error_code: str = ErrorCode.OK
    error_message: str = ""
    contract_version: str = CONTRACT_VERSION
    request_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "result": self.result,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "contract_version": self.contract_version,
            "request_id": self.request_id,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BridgeResponse":
        return BridgeResponse(
            ok=bool(d.get("ok", False)),
            result=d.get("result"),
            error_code=d.get("error_code", ErrorCode.OK),
            error_message=d.get("error_message", ""),
            contract_version=d.get("contract_version", CONTRACT_VERSION),
            request_id=d.get("request_id"),
        )

    @staticmethod
    def success(result: Any, request_id: Optional[str] = None) -> "BridgeResponse":
        return BridgeResponse(ok=True, result=result, request_id=request_id)

    @staticmethod
    def failure(
        code: str, message: str, request_id: Optional[str] = None
    ) -> "BridgeResponse":
        return BridgeResponse(
            ok=False, error_code=code, error_message=message, request_id=request_id
        )


class BridgeError(Exception):
    """Raised harness-side when the bridge returns a non-ok response."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
