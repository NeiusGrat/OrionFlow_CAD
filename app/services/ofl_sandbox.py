"""Execute OFL code strings safely in a subprocess.

Security: subprocess with timeout, restricted imports, isolated output dir.
"""

import os
import sys
import uuid
import shutil
import subprocess
import re
import ast
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "data", "ofl_outputs")


class OFLSandbox:
    """Execute OFL code safely and collect output files."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        os.makedirs(OUTPUT_BASE, exist_ok=True)

    def execute(self, ofl_code: str) -> dict:
        """Execute OFL code in subprocess. Returns result dict."""
        validation = self._validate_code(ofl_code)
        if not validation["safe"]:
            return {
                "success": False, "output_dir": "", "step_file": None,
                "stl_file": None, "error": validation["reason"],
                "stdout": "", "stderr": "",
            }

        request_id = uuid.uuid4().hex[:12]
        output_dir = os.path.join(OUTPUT_BASE, request_id)
        os.makedirs(output_dir, exist_ok=True)

        modified_code = self._rewrite_export_paths(ofl_code, output_dir)

        script_path = os.path.join(output_dir, "_generate.py")
        with open(script_path, "w") as f:
            f.write(modified_code)

        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")

            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True,
                timeout=self.timeout, cwd=output_dir, env=env,
            )

            step_files = list(Path(output_dir).glob("*.step"))
            stl_files = list(Path(output_dir).glob("*.stl"))
            step_file = str(step_files[0]) if step_files else None
            stl_file = str(stl_files[0]) if stl_files else None

            success = result.returncode == 0 and step_file is not None

            return {
                "success": success,
                "output_dir": output_dir,
                "step_file": step_file,
                "stl_file": stl_file,
                "error": result.stderr[:500] if not success else None,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False, "output_dir": output_dir,
                "step_file": None, "stl_file": None,
                "error": f"Execution timed out ({self.timeout}s)",
                "stdout": "", "stderr": "",
            }
        except Exception as e:
            return {
                "success": False, "output_dir": output_dir,
                "step_file": None, "stl_file": None,
                "error": str(e), "stdout": "", "stderr": "",
            }

    def _validate_code(self, code: str) -> dict:
        """Check code for dangerous imports/calls before execution."""
        blocked_imports = {
            "import os", "import sys", "import subprocess", "import shutil",
            "import socket", "import http", "import urllib", "import requests",
            "from os", "from sys", "from subprocess", "from shutil",
            "import pathlib", "__import__",
        }

        blocked_calls = [
            "open(", "exec(", "eval(", "compile(", "getattr(",
            "setattr(", "delattr(", "globals(", "locals(",
        ]

        code_lower = code.lower()
        for blocked in blocked_imports:
            if blocked.lower() in code_lower:
                return {"safe": False, "reason": f"Blocked import: {blocked}"}

        for line in code.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("import ") or (stripped.startswith("from ") and "import" in stripped):
                if "orionflow_ofl" not in stripped and "math" not in stripped:
                    return {"safe": False, "reason": f"Blocked import: {stripped}"}

        for blocked in blocked_calls:
            if blocked in code:
                return {"safe": False, "reason": f"Blocked call: {blocked}"}

        try:
            ast.parse(code)
        except SyntaxError as e:
            return {"safe": False, "reason": f"Syntax error: {e}"}

        return {"safe": True, "reason": "OK"}

    def _rewrite_export_paths(self, code: str, output_dir: str) -> str:
        """Rewrite export() paths to output_dir and ensure STL is also generated."""
        def replace_export(match):
            var_name = match.group(1)
            filename = match.group(2)
            basename = os.path.basename(filename)
            new_path = os.path.join(output_dir, basename).replace("\\", "/")
            return f'export({var_name}, "{new_path}")'

        code = re.sub(
            r"""export\s*\(\s*(\w+)\s*,\s*["']([^"']+)["']\s*\)""",
            replace_export,
            code,
        )

        # Auto-add STL export alongside STEP
        step_match = re.search(r'export\((\w+),\s*"([^"]+\.step)"\)', code)
        if step_match and ".stl" not in code:
            var_name = step_match.group(1)
            step_path = step_match.group(2)
            stl_path = step_path.replace(".step", ".stl")
            code += f'\nexport({var_name}, "{stl_path}")'

        return code

    def cleanup(self, output_dir: str):
        """Remove output directory after files are served."""
        try:
            if output_dir and output_dir.startswith(OUTPUT_BASE):
                shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass
