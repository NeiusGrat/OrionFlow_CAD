"""Capability implementations against the live FreeCAD document.

Every method here runs on FreeCAD's GUI/main thread (marshalled by the bridge
server through :mod:`orion_agent.addon.task_queue`). Methods return plain
JSON-serialisable values that become the ``result`` of a ``BridgeResponse``.

FreeCAD is imported lazily inside methods so this module still imports (and the
contract stays testable) outside a FreeCAD interpreter.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from orion_agent.shared.contract import Capability, ErrorCode, ModelTier


class CapabilityError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _app():
    import FreeCAD  # type: ignore
    return FreeCAD


def _gui():
    try:
        import FreeCADGui  # type: ignore
        return FreeCADGui
    except Exception:  # noqa: BLE001
        return None


def _active_doc():
    app = _app()
    doc = app.ActiveDocument
    if doc is None:
        raise CapabilityError(ErrorCode.NO_DOCUMENT, "No active FreeCAD document")
    return doc


def _surface_type(face) -> str:
    surf = getattr(face, "Surface", None)
    if surf is None:
        return "Unknown"
    name = type(surf).__name__
    return name.replace("Geom", "")


def _curve_type(edge) -> str:
    curve = getattr(edge, "Curve", None)
    if curve is None:
        return "Unknown"
    return type(curve).__name__.replace("Geom", "")


def _shape_of(obj):
    return getattr(obj, "Shape", None)


def _bbox_dict(bb) -> dict[str, Any]:
    return {
        "min": [round(bb.XMin, 4), round(bb.YMin, 4), round(bb.ZMin, 4)],
        "max": [round(bb.XMax, 4), round(bb.YMax, 4), round(bb.ZMax, 4)],
        "size": [round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4)],
    }


class Capabilities:
    """Dispatch table backing the bridge server."""

    # ------------------------------------------------------------------ #
    def dispatch(self, capability: str, params: dict[str, Any]) -> Any:
        handler = getattr(self, f"cap_{capability}", None)
        if handler is None:
            raise CapabilityError(
                ErrorCode.UNKNOWN_CAPABILITY, f"Unknown capability: {capability}"
            )
        return handler(params or {})

    # ---- meta ---------------------------------------------------------- #
    def cap_ping(self, params: dict[str, Any]) -> Any:
        app = _app()
        return {
            "pong": True,
            "freecad_version": ".".join(app.Version()[:3]),
            "gui": _gui() is not None and getattr(app, "GuiUp", 0) == 1,
        }

    def cap_get_capabilities(self, params: dict[str, Any]) -> Any:
        return {"capabilities": sorted(Capability.ALL), "version": "1.0"}

    # ---- read ---------------------------------------------------------- #
    def cap_get_document_state(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        return {
            "name": doc.Name,
            "label": doc.Label,
            "file_name": doc.FileName or "",
            "object_count": len(doc.Objects),
            "modified": bool(getattr(doc, "Modified", False)),
            "tier": self._classify_tier(doc),
        }

    def cap_list_objects(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        objects = []
        for obj in doc.Objects:
            shape = _shape_of(obj)
            parametric = self._is_parametric(obj)
            entry = {
                "name": obj.Name,
                "label": obj.Label,
                "type_id": obj.TypeId,
                "parametric": parametric,
                "imported": (shape is not None and not parametric),
                "visible": bool(getattr(getattr(obj, "ViewObject", None), "Visibility", True)),
            }
            if shape is not None and not shape.isNull():
                entry["solids"] = len(shape.Solids)
                entry["faces"] = len(shape.Faces)
            objects.append(entry)
        return {"objects": objects}

    def cap_get_object_parameters(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        name = params.get("name")
        obj = doc.getObject(name) if name else None
        if obj is None:
            raise CapabilityError(ErrorCode.OBJECT_NOT_FOUND, f"No object named {name!r}")
        props: dict[str, Any] = {}
        for prop in obj.PropertiesList:
            try:
                value = getattr(obj, prop)
                props[prop] = self._coerce(value)
            except Exception:  # noqa: BLE001
                props[prop] = None
        return {"name": obj.Name, "label": obj.Label, "type_id": obj.TypeId, "parameters": props}

    def cap_inspect_topology(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        name = params.get("name")
        targets = [doc.getObject(name)] if name else list(doc.Objects)
        targets = [o for o in targets if o is not None and _shape_of(o) is not None]
        if not targets:
            raise CapabilityError(ErrorCode.OBJECT_NOT_FOUND, "No shape to inspect")

        summaries = []
        for obj in targets:
            shape = _shape_of(obj)
            if shape is None or shape.isNull():
                continue
            surf_counts: dict[str, int] = {}
            for f in shape.Faces:
                st = _surface_type(f)
                surf_counts[st] = surf_counts.get(st, 0) + 1
            curve_counts: dict[str, int] = {}
            for e in shape.Edges:
                ct = _curve_type(e)
                curve_counts[ct] = curve_counts.get(ct, 0) + 1
            try:
                com = shape.CenterOfMass
                center = [round(com.x, 4), round(com.y, 4), round(com.z, 4)]
            except Exception:  # noqa: BLE001
                center = None
            summaries.append(
                {
                    "name": obj.Name,
                    "label": obj.Label,
                    "solids": len(shape.Solids),
                    "shells": len(shape.Shells),
                    "faces": len(shape.Faces),
                    "edges": len(shape.Edges),
                    "vertices": len(shape.Vertexes),
                    "surface_types": surf_counts,
                    "curve_types": curve_counts,
                    "cylindrical_faces": surf_counts.get("Cylinder", 0),
                    "bounding_box": _bbox_dict(shape.BoundBox),
                    "volume": round(shape.Volume, 4),
                    "area": round(shape.Area, 4),
                    "center_of_mass": center,
                }
            )
        return {"shapes": summaries}

    def cap_measure(self, params: dict[str, Any]) -> Any:
        """Distance between two sub-elements: params {a:{name,sub}, b:{name,sub}}."""
        doc = _active_doc()

        def resolve(ref):
            obj = doc.getObject(ref.get("name"))
            if obj is None:
                raise CapabilityError(ErrorCode.OBJECT_NOT_FOUND, f"No object {ref.get('name')!r}")
            shape = _shape_of(obj)
            sub = ref.get("sub")
            if sub:
                return shape.getElement(sub)
            return shape

        a = resolve(params.get("a", {}))
        b = resolve(params.get("b", {}))
        info = a.distToShape(b)
        dist = info[0]
        pts = info[1][0] if len(info) > 1 and info[1] else None
        result = {"distance": round(dist, 5)}
        if pts:
            p0, p1 = pts
            result["from"] = [round(p0.x, 4), round(p0.y, 4), round(p0.z, 4)]
            result["to"] = [round(p1.x, 4), round(p1.y, 4), round(p1.z, 4)]
        return result

    def cap_render_views(self, params: dict[str, Any]) -> Any:
        gui = _gui()
        app = _app()
        out_dir = params.get("out_dir") or os.path.join(
            os.path.dirname(_active_doc().FileName or os.getcwd()), "orion_renders"
        )
        os.makedirs(out_dir, exist_ok=True)
        width = int(params.get("width", 640))
        height = int(params.get("height", 480))
        views = params.get("views") or ["isometric", "front", "top", "right", "rear", "bottom"]

        if gui is None or getattr(app, "GuiUp", 0) != 1:
            return {"renders": [], "headless": True, "note": "render requires GUI mode"}

        view = gui.ActiveDocument.ActiveView
        gui.ActiveDocument.ActiveView.fitAll()
        renders = []
        for v in views:
            setter = {
                "isometric": view.viewIsometric,
                "front": view.viewFront,
                "rear": view.viewRear,
                "top": view.viewTop,
                "bottom": view.viewBottom,
                "left": view.viewLeft,
                "right": view.viewRight,
            }.get(v)
            if setter is None:
                continue
            setter()
            view.fitAll()
            path = os.path.join(out_dir, f"view_{v}.png")
            view.saveImage(path, width, height, "White")
            renders.append({"view": v, "path": path})
        return {"renders": renders, "headless": False}

    def cap_get_model_tier(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        return {"tier": self._classify_tier(doc), "rationale": self._tier_rationale(doc)}

    # ---- mutate (used by Modify pillar / Phase 5) --------------------- #
    def cap_begin_transaction(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        doc.openTransaction(params.get("label", "OrionFlow edit"))
        return {"open": True}

    def cap_commit_transaction(self, params: dict[str, Any]) -> Any:
        _active_doc().commitTransaction()
        return {"committed": True}

    def cap_abort_transaction(self, params: dict[str, Any]) -> Any:
        _active_doc().abortTransaction()
        return {"aborted": True}

    def cap_set_parameter(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        obj = doc.getObject(params.get("name"))
        if obj is None:
            raise CapabilityError(ErrorCode.OBJECT_NOT_FOUND, f"No object {params.get('name')!r}")
        prop = params.get("property")
        value = params.get("value")
        if prop not in obj.PropertiesList:
            raise CapabilityError(ErrorCode.BAD_REQUEST, f"{obj.Name} has no property {prop!r}")
        before = self._coerce(getattr(obj, prop))
        setattr(obj, prop, value)
        doc.recompute()
        if self._has_errors(doc):
            raise CapabilityError(ErrorCode.RECOMPUTE_FAILED, self._error_report(doc))
        return {"name": obj.Name, "property": prop, "before": before, "after": value}

    def cap_edit_feature(self, params: dict[str, Any]) -> Any:
        """Set multiple properties on a feature, then recompute."""
        doc = _active_doc()
        obj = doc.getObject(params.get("name"))
        if obj is None:
            raise CapabilityError(ErrorCode.OBJECT_NOT_FOUND, f"No object {params.get('name')!r}")
        changes = params.get("properties", {})
        applied = {}
        for prop, value in changes.items():
            if prop in obj.PropertiesList:
                applied[prop] = {"before": self._coerce(getattr(obj, prop)), "after": value}
                setattr(obj, prop, value)
        doc.recompute()
        if self._has_errors(doc):
            raise CapabilityError(ErrorCode.RECOMPUTE_FAILED, self._error_report(doc))
        return {"name": obj.Name, "applied": applied}

    def cap_import_shape(self, params: dict[str, Any]) -> Any:
        """Import a STEP/BREP artifact produced by the sandbox into the document.

        Unlike read capabilities, this one *creates* geometry — so when there is
        no open document (e.g. a Generate request from a blank session) we open
        a fresh one instead of failing with NO_DOCUMENT.
        """
        import Part  # type: ignore
        app = _app()
        doc = app.ActiveDocument or app.newDocument("OrionFlow")
        path = params.get("path")
        label = params.get("label", "OrionResult")
        replace = params.get("replace")
        if not path or not os.path.exists(path):
            raise CapabilityError(ErrorCode.BAD_REQUEST, f"Artifact not found: {path}")
        shape = Part.Shape()
        shape.read(path)
        if replace:
            obj = doc.getObject(replace)
            if obj is not None and hasattr(obj, "Shape"):
                obj.Shape = shape
                doc.recompute()
                return {"replaced": replace}
        feat = doc.addObject("Part::Feature", label)
        feat.Shape = shape
        doc.recompute()
        gui = _gui()
        if gui is not None:
            try:
                gui.ActiveDocument.ActiveView.fitAll()
            except Exception:  # noqa: BLE001
                pass
        return {"created": feat.Name}

    def cap_select(self, params: dict[str, Any]) -> Any:
        gui = _gui()
        if gui is None:
            return {"selected": False, "headless": True}
        gui.Selection.clearSelection()
        for ref in params.get("refs", []):
            obj = _active_doc().getObject(ref.get("name"))
            if obj is None:
                continue
            if ref.get("sub"):
                gui.Selection.addSelection(obj, ref["sub"])
            else:
                gui.Selection.addSelection(obj)
        return {"selected": True}

    def cap_highlight(self, params: dict[str, Any]) -> Any:
        return self.cap_select(params)

    def cap_undo(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        doc.undo()
        doc.recompute()
        return {"undone": True}

    def cap_redo(self, params: dict[str, Any]) -> Any:
        doc = _active_doc()
        doc.redo()
        doc.recompute()
        return {"redone": True}

    def cap_export(self, params: dict[str, Any]) -> Any:
        import Part  # type: ignore
        doc = _active_doc()
        names = params.get("names") or [o.Name for o in doc.Objects if _shape_of(o) is not None]
        path = params.get("path")
        if not path:
            raise CapabilityError(ErrorCode.BAD_REQUEST, "export requires a path")
        shapes = [_shape_of(doc.getObject(n)) for n in names]
        shapes = [s for s in shapes if s is not None]
        Part.export([doc.getObject(n) for n in names if doc.getObject(n)], path) \
            if path.lower().endswith((".step", ".stp")) else shapes[0].exportStl(path)
        return {"path": path, "objects": names}

    def cap_execute_code(self, params: dict[str, Any]) -> Any:
        """Reserved: the harness runs code in its sandbox, then calls import_shape.

        Direct code execution into the live document is intentionally not
        supported here — generated code never runs in FreeCAD's interpreter.
        """
        raise CapabilityError(
            ErrorCode.NOT_PERMITTED,
            "execute_code runs in the harness sandbox; use import_shape to bring results in",
        )

    # ------------------------------------------------------------------ #
    # Tier classification (§4)
    # ------------------------------------------------------------------ #
    def _source_sidecar(self, doc) -> Optional[str]:
        fn = doc.FileName
        if not fn:
            return None
        candidate = os.path.splitext(fn)[0] + ".orion.py"
        return candidate if os.path.exists(candidate) else None

    def _is_parametric(self, obj) -> bool:
        tid = obj.TypeId
        if tid.startswith(("PartDesign::", "Sketcher::")):
            return True
        # A feature with a non-empty history / sources counts as parametric.
        if getattr(obj, "OutList", None):
            if any(s.TypeId.startswith(("Sketcher::", "PartDesign::")) for s in obj.OutList):
                return True
        return False

    def _classify_tier(self, doc) -> str:
        if not doc.Objects:
            return ModelTier.EMPTY
        if self._source_sidecar(doc):
            return ModelTier.CODE_NATIVE
        if any(self._is_parametric(o) for o in doc.Objects):
            return ModelTier.FEATURE_TREE
        has_shape = any(_shape_of(o) is not None for o in doc.Objects)
        if has_shape:
            return ModelTier.DUMB_BREP
        return ModelTier.UNKNOWN

    def _tier_rationale(self, doc) -> str:
        if not doc.Objects:
            return "document is empty"
        if self._source_sidecar(doc):
            return f"Build123d source attached: {os.path.basename(self._source_sidecar(doc))}"
        if any(self._is_parametric(o) for o in doc.Objects):
            kinds = sorted({o.TypeId for o in doc.Objects if self._is_parametric(o)})
            return f"live feature history present: {', '.join(kinds)}"
        return "imported B-rep solids with no parametric history"

    # ------------------------------------------------------------------ #
    @staticmethod
    def _has_errors(doc) -> bool:
        for obj in doc.Objects:
            state = getattr(obj, "State", [])
            if "Error" in state or "Invalid" in state:
                return True
        return False

    @staticmethod
    def _error_report(doc) -> str:
        bad = [o.Name for o in doc.Objects if "Error" in getattr(o, "State", [])]
        return f"recompute errors on: {', '.join(bad) or 'unknown'}"

    @staticmethod
    def _coerce(value) -> Any:
        """Make a FreeCAD property JSON-serialisable."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        # Quantity (e.g. length with units)
        if hasattr(value, "Value") and hasattr(value, "Unit"):
            return {"value": float(value.Value), "unit": str(value.Unit)}
        if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
            return [round(value.x, 5), round(value.y, 5), round(value.z, 5)]
        if isinstance(value, (list, tuple)):
            return [Capabilities._coerce(v) for v in value]
        return str(value)
