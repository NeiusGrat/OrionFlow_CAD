"""Core orchestrator: text prompt → OFL code → STEP/STL/GLB files."""

import os
import re
import time
import logging
from typing import Optional

from app.domain.ofl_models import OFLGenerateResponse, OFLFileLinks, OFLParameter
from app.services.ofl_llm_client import OFLLLMClient
from app.services.ofl_sandbox import OFLSandbox
from app.services.stl_to_glb import stl_to_glb

logger = logging.getLogger(__name__)


class OFLGenerationService:
    """Orchestrates: prompt → LLM → code → sandbox → files."""

    def __init__(self, require_llm: bool = True):
        self._llm = None
        self._llm_fallback = None
        self.sandbox = OFLSandbox(timeout=30)
        if require_llm:
            self._llm = OFLLLMClient()

    @property
    def llm(self) -> OFLLLMClient:
        if self._llm is None:
            self._llm = OFLLLMClient()
        return self._llm

    def _llm_call(self, method: str, *args) -> str:
        """Call the primary LLM; on failure retry once on the fallback provider."""
        from app.config import settings

        try:
            return getattr(self.llm, method)(*args)
        except Exception as primary_exc:
            fallback = settings.ofl_llm_fallback_provider
            if not fallback or fallback == self.llm.provider:
                raise
            if self._llm_fallback is None:
                self._llm_fallback = OFLLLMClient(provider=fallback)
            logger.warning(
                f"OFL primary LLM ({self.llm.provider}) failed: {primary_exc}; "
                f"retrying on {fallback}"
            )
            return getattr(self._llm_fallback, method)(*args)

    def generate_from_prompt(
        self, prompt: str, max_repairs: int = 2
    ) -> OFLGenerateResponse:
        """Full pipeline: text → code → STEP/STL/GLB, with LLM self-repair."""
        t0 = time.time()
        try:
            ofl_code = self._llm_call("generate", prompt)
        except Exception as e:
            return OFLGenerateResponse(
                success=False,
                error=f"LLM error: {e}",
                generation_time_ms=(time.time() - t0) * 1000,
            )
        return self._execute_with_repair(ofl_code, prompt, t0, max_repairs)

    def rebuild_from_code(self, ofl_code: str) -> OFLGenerateResponse:
        """Re-execute edited OFL code (no LLM call, no repair — the user
        edited this code and wants their own error back)."""
        return self._execute_and_respond(ofl_code, time.time())

    def edit_from_instruction(
        self, current_code: str, edit_instruction: str
    ) -> OFLGenerateResponse:
        """Apply NL edit to existing code, re-execute."""
        t0 = time.time()
        edited = self._try_rule_based_edit(current_code, edit_instruction)
        if edited is None:
            try:
                edited = self._llm_call("generate_edit", current_code, edit_instruction)
            except Exception as e:
                return OFLGenerateResponse(
                    success=False,
                    error=f"Edit LLM error: {e}",
                    generation_time_ms=(time.time() - t0) * 1000,
                )
            return self._execute_with_repair(edited, edit_instruction, t0)
        return self._execute_and_respond(edited, t0)

    def _execute_with_repair(
        self, ofl_code: str, prompt: str, t0: float, max_repairs: int = 2
    ) -> OFLGenerateResponse:
        """Execute code; on failure feed the error back to the LLM and retry."""
        result = self.sandbox.execute(ofl_code)
        repairs = 0
        for attempt in range(max_repairs):
            if result["success"]:
                break
            logger.info(
                f"OFL execution failed (repair attempt {attempt + 1}): "
                f"{result['error']}"
            )
            try:
                ofl_code = self._llm_call(
                    "repair", ofl_code, result["error"] or "", prompt
                )
            except Exception as e:
                logger.warning(f"OFL repair LLM call failed: {e}")
                break
            repairs += 1
            result = self.sandbox.execute(ofl_code)
        return self._respond_from_result(ofl_code, result, t0, repair_attempts=repairs)

    def _execute_and_respond(self, ofl_code: str, t0: float) -> OFLGenerateResponse:
        result = self.sandbox.execute(ofl_code)
        return self._respond_from_result(ofl_code, result, t0)

    def _respond_from_result(
        self, ofl_code: str, result: dict, t0: float, repair_attempts: int = 0
    ) -> OFLGenerateResponse:
        if not result["success"]:
            return OFLGenerateResponse(
                success=False,
                ofl_code=ofl_code,
                error=result["error"],
                generation_time_ms=(time.time() - t0) * 1000,
                repair_attempts=repair_attempts,
            )

        # Convert STL → GLB for viewer
        glb_path = None
        if result["stl_file"]:
            glb_path = stl_to_glb(result["stl_file"])

        # Build download links
        request_id = os.path.basename(result["output_dir"])
        files = OFLFileLinks()
        if result["step_file"]:
            files.step = f"/api/v1/ofl/download/{request_id}/{os.path.basename(result['step_file'])}"
        if result["stl_file"]:
            files.stl = f"/api/v1/ofl/download/{request_id}/{os.path.basename(result['stl_file'])}"
        if glb_path:
            files.glb = (
                f"/api/v1/ofl/download/{request_id}/{os.path.basename(glb_path)}"
            )

        # Durable copies: per-request output dirs are ephemeral on
        # scale-to-zero hosts; the download route redirects to storage
        # when the local file is gone.
        from app.config import settings

        if settings.is_s3_configured:
            from pathlib import Path

            from app.services.storage import get_storage

            storage = get_storage()
            for path in (result["step_file"], result["stl_file"], glb_path):
                if path and os.path.exists(path):
                    try:
                        storage.publish(
                            Path(path),
                            key=f"ofl/{request_id}/{os.path.basename(path)}",
                        )
                    except Exception as e:
                        logger.warning(f"OFL artifact upload failed: {e}")

        parameters = self._extract_parameters(ofl_code)
        stats = self._measure_geometry(result["stl_file"])

        return OFLGenerateResponse(
            success=True,
            ofl_code=ofl_code,
            files=files,
            parameters=parameters,
            generation_time_ms=(time.time() - t0) * 1000,
            repair_attempts=repair_attempts,
            stats=stats,
        )

    @staticmethod
    def _measure_geometry(stl_path):
        """Validation evidence for the response: watertightness, volume, bbox."""
        if not stl_path:
            return None
        try:
            import trimesh

            from app.domain.ofl_models import OFLGeometryStats

            mesh = trimesh.load(stl_path)
            extent = mesh.bounds[1] - mesh.bounds[0]
            return OFLGeometryStats(
                watertight=bool(mesh.is_watertight),
                volume_mm3=round(float(mesh.volume), 1),
                bbox_mm=[round(float(v), 1) for v in extent],
                triangles=int(len(mesh.faces)),
            )
        except Exception as e:
            logger.warning(f"geometry measurement failed: {e}")
            return None

    def _extract_parameters(self, code: str) -> list[OFLParameter]:
        """Extract named numeric variables from OFL code."""
        params = []
        for i, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("from "):
                continue
            match = re.match(
                r"^([a-z_][a-z0-9_]*)\s*=\s*([0-9]+\.?[0-9]*)\s*(?:#.*)?$", stripped
            )
            if match:
                params.append(
                    OFLParameter(
                        name=match.group(1),
                        value=float(match.group(2)),
                        line_number=i,
                    )
                )
            elif stripped.startswith("part") or stripped.startswith("export"):
                break
        return params

    def _try_rule_based_edit(self, code: str, instruction: str) -> Optional[str]:
        """Try simple edits without LLM (bolt sizes, thickness)."""
        instruction_lower = instruction.lower()

        bolt_clearances = {
            "m2": 2.4,
            "m3": 3.4,
            "m4": 4.5,
            "m5": 5.5,
            "m6": 6.6,
            "m8": 8.4,
            "m10": 10.5,
            "m12": 13.0,
            "m14": 15.0,
            "m16": 17.5,
        }

        bolt_match = re.search(
            r"change\s+(m\d+)\s+(?:holes?\s+)?to\s+(m\d+)", instruction_lower
        )
        if bolt_match:
            old_bolt, new_bolt = bolt_match.group(1), bolt_match.group(2)
            if old_bolt in bolt_clearances and new_bolt in bolt_clearances:
                old_dia = bolt_clearances[old_bolt]
                new_dia = bolt_clearances[new_bolt]
                code = re.sub(
                    rf"(\w+_dia\s*=\s*){re.escape(str(old_dia))}",
                    rf"\g<1>{new_dia}",
                    code,
                )
                code = code.replace(f'"{old_bolt.upper()}_', f'"{new_bolt.upper()}_')
                return code

        thickness_match = re.search(
            r"(?:change|set)\s+thickness\s+to\s+(\d+\.?\d*)", instruction_lower
        )
        if thickness_match:
            new_val = thickness_match.group(1)
            code = re.sub(r"(thickness\s*=\s*)\d+\.?\d*", rf"\g<1>{new_val}", code)
            return code

        return None
