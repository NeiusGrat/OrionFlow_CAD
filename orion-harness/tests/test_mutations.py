"""§13.2: each gate has a deliberately broken oracle that must fail that
specific gate, and no other. A mutation that fails the wrong gate (or
passes) means the gate is not checking what its name claims.
"""

import pytest

from conftest import ORACLES_ROOT

from orion_harness.runner.errors import TaskOutcome
from orion_harness.runner.jobs import run_build_job

MUTATIONS_DIR = ORACLES_ROOT / "mutations"

STANDARD_GATES = [
    {"name": "schema_valid", "verifier": "tier0.schema", "kind": "gate", "params": {}},
    {"name": "single_solid", "verifier": "tier1.single_solid", "kind": "gate", "params": {}},
    {"name": "watertight", "verifier": "tier1.watertight", "kind": "gate", "params": {}},
    {
        "name": "rebuild_deterministic",
        "verifier": "tier1.rebuild_deterministic",
        "kind": "gate",
        "params": {},
    },
]


def _source(name: str) -> str:
    return (MUTATIONS_DIR / f"{name}.ofl.py").read_text(encoding="utf-8")


def test_schema_invalid_is_parse_error_not_a_gate_failure():
    with pytest.raises(TaskOutcome) as exc_info:
        run_build_job("ofl", _source("schema_invalid"), STANDARD_GATES)
    assert exc_info.value.code == "parse_error"


def test_single_solid_fails_and_nothing_else_runs():
    result = run_build_job("ofl", _source("single_solid_fails"), STANDARD_GATES)
    gates = {g["name"]: g["passed"] for g in result["gates"]}
    assert gates["schema_valid"] is True
    assert gates["single_solid"] is False
    assert "watertight" not in gates
    assert "rebuild_deterministic" not in gates
    assert result["skipped"] == ["watertight", "rebuild_deterministic"]


def test_watertight_fails_and_rebuild_check_is_skipped():
    result = run_build_job("ofl", _source("watertight_fails"), STANDARD_GATES)
    gates = {g["name"]: g["passed"] for g in result["gates"]}
    assert gates["schema_valid"] is True
    assert gates["single_solid"] is True  # single body -- the shell just isn't closed
    assert gates["watertight"] is False
    assert "rebuild_deterministic" not in gates
    assert result["skipped"] == ["rebuild_deterministic"]


def test_nondeterministic_dimension_fails_rebuild_check():
    result = run_build_job("ofl", _source("nondeterministic"), STANDARD_GATES)
    gates = {g["name"]: g["passed"] for g in result["gates"]}
    assert gates["schema_valid"] is True
    assert gates["single_solid"] is True
    assert gates["watertight"] is True
    assert gates["rebuild_deterministic"] is False


def test_oversized_fillet_is_exec_crash_not_a_gate_failure():
    with pytest.raises(TaskOutcome) as exc_info:
        run_build_job("ofl", _source("exec_crash_fillet"), STANDARD_GATES)
    assert exc_info.value.code == "exec_crash"


TAG_STABILITY_GATES = STANDARD_GATES[:-1] + [
    {
        "name": "mount_hole_present",
        "verifier": "tier1.hole_present",
        "kind": "gate",
        "params": {"at": [30, 0], "diameter": 8, "tolerance": 0.5},
    },
    STANDARD_GATES[-1],
]


def test_drifted_hole_fails_hole_present_and_nothing_upstream():
    result = run_build_job(
        "ofl", _source("tag_stability_hole_moved"), TAG_STABILITY_GATES
    )
    gates = {g["name"]: g["passed"] for g in result["gates"]}
    assert gates["schema_valid"] is True
    assert gates["single_solid"] is True
    assert gates["watertight"] is True
    assert gates["mount_hole_present"] is False
    assert "rebuild_deterministic" not in gates
    assert result["skipped"] == ["rebuild_deterministic"]
