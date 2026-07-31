"""The MCP surface is a door onto the products, not a reimplementation.

What matters is that it exposes the same tools the studio and copilot use, that
the protocol is well-formed enough for a real client, and that a failing tool
comes back as an error rather than as a plausible-looking success.
"""

import json

import pytest

from orion_agent.mcp_server import MCPServer, build_surface, call_tool


@pytest.fixture(scope="module")
def server():
    return MCPServer()


def test_surface_carries_knowledge_design_and_calculators():
    _, schemas = build_surface()
    names = {s["name"] for s in schemas}
    # the fine-tuned model, reachable from any client
    assert "design_part" in names
    # knowledge, none of which needs FreeCAD
    assert {"lookup_nasa_requirement", "lookup_standard",
            "check_sheet_metal_dfm"} <= names
    # deterministic arithmetic
    assert {"calc_thread_engagement", "calc_beam_bending"} <= names
    # geometry editing needs a live document; an MCP client has none
    assert not names & {"set_parameter", "edit_feature", "inspect_topology"}


def test_every_tool_declares_a_usable_schema():
    _, schemas = build_surface()
    for s in schemas:
        assert s["name"] and s["description"], s
        params = s["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("properties"), dict)


def test_initialize_and_list(server):
    reply = server.handle({"jsonrpc": "2.0", "id": 1,
                           "method": "initialize", "params": {}})
    assert reply["result"]["serverInfo"]["name"] == "orionflow"
    assert "tools" in reply["result"]["capabilities"]

    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = listed["result"]["tools"]
    assert tools and all("inputSchema" in t for t in tools)
    assert "design_part" in {t["name"] for t in tools}


def test_notifications_get_no_reply(server):
    """A JSON-RPC notification has no id; replying to one breaks clients."""
    assert server.handle({"jsonrpc": "2.0",
                          "method": "notifications/initialized"}) is None


def test_unknown_method_is_an_error_not_a_crash(server):
    reply = server.handle({"jsonrpc": "2.0", "id": 9, "method": "nope"})
    assert reply["error"]["code"] == -32601


def test_a_knowledge_call_returns_a_real_citation(server):
    reply = server.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "lookup_nasa_requirement",
                   "arguments": {"query": "locking feature"}}})
    result = reply["result"]
    assert result["isError"] is False
    assert "NASA-STD" in result["content"][0]["text"]


def test_a_calculator_call_returns_numbers(server):
    reply = server.handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "calc_thread_engagement",
                   "arguments": {"d_mm": 8.0, "pitch_mm": 1.25,
                                 "bolt_uts_mpa": 800.0,
                                 "nut_material": "aluminium_6061_t6"}}})
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert payload["min_engagement_mm"] > 0
    # steel needs less engagement than aluminium; the formula must produce that
    steel = json.loads(call_tool(
        server.registry, "calc_thread_engagement",
        {"d_mm": 8.0, "pitch_mm": 1.25, "bolt_uts_mpa": 800.0,
         "nut_material": "steel_1018"})[0])
    assert steel["min_engagement_mm"] < payload["min_engagement_mm"]


def test_a_bad_call_is_flagged_as_an_error(server):
    """A tool that fails must not come back looking like a result."""
    reply = server.handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "calc_material",
                   "arguments": {"name": "unobtainium"}}})
    assert reply["result"]["isError"] is True

    missing = server.handle({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "no_such_tool", "arguments": {}}})
    assert missing["result"]["isError"] is True


def test_design_part_requires_a_request(server):
    """Reached without hitting the endpoint: the guard is local."""
    reply = server.handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "design_part", "arguments": {"request": "  "}}})
    assert reply["result"]["isError"] is True
    assert "required" in reply["result"]["content"][0]["text"]
