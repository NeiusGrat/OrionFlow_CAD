"""Document lifecycle, object deletion and the stock parts library.

These are the capabilities the agent previously lacked: it could fill a
document but not start one, create objects but not remove them, and had no way
to reach a real fastener. The FreeCAD-side behaviour is exercised against a
live interpreter; what is checked here is the wiring that must not silently
desync — contract, dispatch, and the tool surface the model actually sees.
"""

import pytest

from orion_agent.addon.capabilities import Capabilities
from orion_agent.harness.tools.registry import build_registry
from orion_agent.shared.contract import Capability


NEW_TOOLS = [
    "list_documents", "new_document", "open_document", "activate_document",
    "reload_document", "delete_object", "list_library_parts",
    "insert_library_part",
]


class RecordingBridge:
    """Captures the call the tool made, and replays a canned result."""

    def __init__(self, **results):
        self.results = results
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.results.get(name, {})
        return call


def registry(**results):
    return build_registry(RecordingBridge(**results), None)


# --------------------------------------------------------------------------- #
# contract <-> handler symmetry
# --------------------------------------------------------------------------- #

def test_every_capability_has_a_handler():
    """A capability named in the contract but not implemented is a runtime
    UNKNOWN_CAPABILITY that no test would otherwise catch."""
    missing = [c for c in sorted(Capability.ALL)
               if not hasattr(Capabilities, f"cap_{c}")]
    assert missing == []


def test_no_orphan_handlers():
    orphans = [m[4:] for m in dir(Capabilities)
               if m.startswith("cap_") and m[4:] not in Capability.ALL]
    assert orphans == []


@pytest.mark.parametrize("cap", [
    Capability.LIST_DOCUMENTS, Capability.NEW_DOCUMENT,
    Capability.OPEN_DOCUMENT, Capability.ACTIVATE_DOCUMENT,
    Capability.RELOAD_DOCUMENT, Capability.DELETE_OBJECT,
    Capability.LIST_LIBRARY_PARTS, Capability.INSERT_LIBRARY_PART,
])
def test_new_capabilities_declared(cap):
    assert cap in Capability.ALL


def test_mutating_capabilities_are_not_read_only():
    """READ_ONLY gates the pillar router; a mutator leaking into it would let
    a read-only session modify the user's document."""
    for cap in (Capability.NEW_DOCUMENT, Capability.OPEN_DOCUMENT,
                Capability.ACTIVATE_DOCUMENT, Capability.RELOAD_DOCUMENT,
                Capability.DELETE_OBJECT, Capability.INSERT_LIBRARY_PART):
        assert cap not in Capability.READ_ONLY
    for cap in (Capability.LIST_DOCUMENTS, Capability.LIST_LIBRARY_PARTS):
        assert cap in Capability.READ_ONLY


# --------------------------------------------------------------------------- #
# tool surface
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", NEW_TOOLS)
def test_tool_registered_with_schema(name):
    tool = registry()._tools[name]
    schema = tool.schema()["function"]
    assert schema["name"] == name
    assert schema["description"].strip()
    assert schema["parameters"]["type"] == "object"


def test_delete_object_is_flagged_destructive():
    """The permission layer keys off these flags; an unflagged delete would
    skip confirmation entirely."""
    tool = registry()._tools["delete_object"]
    assert tool.mutating and tool.destructive and tool.doc_mutating


@pytest.mark.parametrize("name,mutating", [
    ("new_document", True), ("open_document", True), ("reload_document", True),
    ("activate_document", True), ("insert_library_part", True),
    ("list_documents", False), ("list_library_parts", False),
])
def test_mutation_flags(name, mutating):
    assert registry()._tools[name].mutating is mutating


# --------------------------------------------------------------------------- #
# executor behaviour
# --------------------------------------------------------------------------- #

def test_delete_object_forwards_names_and_cascade():
    bridge = RecordingBridge(delete_object={"removed": ["Pad"], "failed": []})
    reg = build_registry(bridge, None)
    reg._tools["delete_object"].executor({"name": "Pad"})
    assert bridge.calls[-1] == ("delete_object", (["Pad"], False), {})
    reg._tools["delete_object"].executor({"names": ["A", "B"], "cascade": True})
    assert bridge.calls[-1] == ("delete_object", (["A", "B"], True), {})


def test_delete_object_without_a_target_fails_without_calling_freecad():
    bridge = RecordingBridge()
    reg = build_registry(bridge, None)
    result = reg._tools["delete_object"].executor({})
    assert not result.ok
    assert bridge.calls == []


def test_delete_object_surfaces_failures():
    reg = registry(delete_object={"removed": ["A"],
                                  "failed": [{"name": "B", "error": "locked"}]})
    out = reg._tools["delete_object"].executor({"names": ["A", "B"]})
    assert "A" in out.content and "locked" in out.content


def test_list_library_parts_reports_the_missing_library_as_a_hint():
    """An empty result must explain itself, or the model retries the search
    forever instead of modelling the part."""
    hint = "No parts library found. Install 'parts_library' ..."
    reg = registry(list_library_parts={"roots": [], "parts": [], "count": 0,
                                       "hint": hint})
    out = reg._tools["list_library_parts"].executor({})
    assert out.ok and hint in out.content


def test_list_library_parts_lists_paths():
    reg = registry(list_library_parts={
        "roots": ["/lib"], "count": 2, "truncated": False,
        "parts": [{"path": "fasteners/iso4762_M6x20.FCStd"},
                  {"path": "bearings/608zz.FCStd"}]})
    out = reg._tools["list_library_parts"].executor({"query": "m6"})
    assert "iso4762_M6x20.FCStd" in out.content and "608zz" in out.content


def test_list_library_parts_marks_truncation():
    reg = registry(list_library_parts={
        "roots": ["/lib"], "count": 900, "truncated": True,
        "parts": [{"path": "a.FCStd"}]})
    out = reg._tools["list_library_parts"].executor({})
    assert "truncated" in out.content


def test_list_documents_marks_the_active_one():
    reg = registry(list_documents={"active": "b", "documents": [
        {"name": "a", "label": "part_a", "object_count": 3,
         "modified": False, "active": False},
        {"name": "b", "label": "part_b", "object_count": 7,
         "modified": True, "active": True}]})
    out = reg._tools["list_documents"].executor({})
    lines = out.content.splitlines()
    assert lines[0].startswith("  ") and "part_a" in lines[0]
    assert lines[1].startswith("* ") and "part_b" in lines[1]
    assert "modified" in lines[1]


def test_list_documents_empty():
    reg = registry(list_documents={"active": None, "documents": []})
    assert "no documents" in reg._tools["list_documents"].executor({}).content


def test_new_document_passes_the_label_through():
    bridge = RecordingBridge(new_document={"name": "jaw", "label": "jaw",
                                           "created": True})
    reg = build_registry(bridge, None)
    out = reg._tools["new_document"].executor({"label": "jaw"})
    assert bridge.calls[-1] == ("new_document", ("jaw",), {})
    assert "jaw" in out.content


def test_insert_library_part_forwards_the_exact_path():
    bridge = RecordingBridge(insert_library_part={"label": "bolt"})
    reg = build_registry(bridge, None)
    reg._tools["insert_library_part"].executor(
        {"path": "fasteners/iso4762_M6x20.FCStd", "label": "bolt"})
    assert bridge.calls[-1] == (
        "insert_library_part", ("fasteners/iso4762_M6x20.FCStd", "bolt"), {})
