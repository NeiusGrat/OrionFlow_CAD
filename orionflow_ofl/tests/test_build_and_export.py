"""OFL v0.1 build-and-export tests.

Executes each example script, verifies STEP output exists and is > 1000 bytes.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

EXAMPLES = [
    "nema17_mount.py",
    "flat_plate.py",
    "spacer.py",
    "four_hole_plate.py",
    "washer.py",
]


def _step_name(script_name: str) -> str:
    return script_name.replace(".py", ".step")


@pytest.mark.parametrize("script", EXAMPLES)
def test_example_produces_valid_step(script):
    """Run an OFL example and verify the STEP file it produces."""
    example_path = EXAMPLES_DIR / script
    assert example_path.exists(), f"Example not found: {example_path}"

    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(example_path)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0, (
            f"{script} failed (exit {result.returncode}):\n{result.stderr}"
        )

        step_file = Path(tmpdir) / _step_name(script)
        assert step_file.exists(), f"STEP file not created: {step_file.name}"

        size = step_file.stat().st_size
        assert size > 1000, f"STEP file too small: {size} bytes"
