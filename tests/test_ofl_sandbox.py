"""Tests for OFL sandbox execution and security."""


def test_sandbox_valid_code():
    from app.services.ofl_sandbox import OFLSandbox

    sandbox = OFLSandbox()
    code = (
        "from orionflow_ofl import *\n"
        "part = Sketch(Plane.XY).rect(50, 50).extrude(5)\n"
        'export(part, "test.step")'
    )
    result = sandbox.execute(code)
    assert result["success"], f"Sandbox failed: {result['error']}"
    assert result["step_file"] is not None
    # Cleanup
    sandbox.cleanup(result["output_dir"])


def test_sandbox_blocks_os_import():
    from app.services.ofl_sandbox import OFLSandbox

    sandbox = OFLSandbox()
    result = sandbox.execute("import os; os.system('rm -rf /')")
    assert not result["success"]
    assert "Blocked" in result["error"]


def test_sandbox_blocks_subprocess():
    from app.services.ofl_sandbox import OFLSandbox

    sandbox = OFLSandbox()
    result = sandbox.execute("import subprocess; subprocess.run(['ls'])")
    assert not result["success"]


def test_sandbox_blocks_eval():
    from app.services.ofl_sandbox import OFLSandbox

    sandbox = OFLSandbox()
    result = sandbox.execute('eval("1+1")')
    assert not result["success"]
    assert "Blocked" in result["error"]


def test_sandbox_syntax_error():
    from app.services.ofl_sandbox import OFLSandbox

    sandbox = OFLSandbox()
    result = sandbox.execute("def foo(:\n  pass")
    assert not result["success"]
    assert "Syntax error" in result["error"]


def test_parameter_extraction():
    from app.services.ofl_generation_service import OFLGenerationService

    svc = OFLGenerationService.__new__(OFLGenerationService)
    code = (
        "from orionflow_ofl import *\n"
        "width = 60\n"
        "thickness = 6\n"
        "part = Sketch(Plane.XY).rect(width, width).extrude(thickness)"
    )
    params = svc._extract_parameters(code)
    assert len(params) == 2
    assert params[0].name == "width"
    assert params[0].value == 60
    assert params[1].name == "thickness"
    assert params[1].value == 6


def test_rule_based_bolt_edit():
    from app.services.ofl_generation_service import OFLGenerationService

    svc = OFLGenerationService.__new__(OFLGenerationService)
    code = 'bolt_dia = 5.5\npart -= Hole(bolt_dia).at(0,0).through().label("M5_mount")'
    edited = svc._try_rule_based_edit(code, "change M5 holes to M6")
    assert edited is not None
    assert "6.6" in edited
    assert "M6_mount" in edited


def test_rule_based_thickness_edit():
    from app.services.ofl_generation_service import OFLGenerationService

    svc = OFLGenerationService.__new__(OFLGenerationService)
    code = "thickness = 6\npart = Sketch(Plane.XY).rect(50, 50).extrude(thickness)"
    edited = svc._try_rule_based_edit(code, "set thickness to 10")
    assert edited is not None
    assert "thickness = 10" in edited


def test_the_user_code_budget_is_not_spent_on_importing_the_kernel():
    """``timeout`` bounds submitted code; it is not a bet on machine speed.

    The two were one number, and that made the limit mean two unrelated things
    at once. Importing build123d pulls in ~540 OCP modules — about six seconds
    on an idle machine and several times that on a loaded runner — all of it
    before the first submitted statement runs. So a plate that renders in a
    fraction of a second failed at 30 seconds, and the security control fired on
    load rather than on the thing it exists to bound.

    Asserted on the arithmetic rather than by timing anything, so the test does
    not itself become a machine-speed measurement.
    """
    from app.services.ofl_sandbox import OFLSandbox

    sandbox = OFLSandbox(timeout=30)
    assert sandbox.timeout == 30, "the user-code budget is what callers set"
    assert sandbox._process_timeout == 30 + OFLSandbox.STARTUP_ALLOWANCE_S
    assert sandbox._process_timeout > sandbox.timeout, (
        "the process budget must leave room for the kernel import, or the "
        "limit fires on startup instead of on the submitted code"
    )
    # A caller tightening the user budget must not lose the startup allowance.
    assert OFLSandbox(timeout=1)._process_timeout > OFLSandbox.STARTUP_ALLOWANCE_S
