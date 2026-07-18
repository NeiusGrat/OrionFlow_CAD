"""PhysicalAIAgent — the Physical AI design harness.

ReAct-style pipeline over the existing OrionFlow infrastructure:

    intent → source_parts → design_reasoning → generate_ofl (LLM)
    → validate_geometry + self_repair (existing service) → analyze (DFM)
    → simulate (URDF / SDF with real inertia)

Every phase appends to a trace, so the caller sees WHY each number exists,
not just the final geometry.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

from .analyze import analyze_part
from .knowledge import KnowledgeBase, get_knowledge_base
from .reasoning import design_reasoning, plan_to_brief
from .simulate import generate_sdf, generate_urdf, mass_properties
from .sourcing import source_parts

logger = logging.getLogger(__name__)

_INTENT_RULES = [
    ("edit", ("edit", "change", "make it", "thicker", "thinner", "resize")),
    ("analyze", ("analyze", "check", "will this", "stress", "strong enough")),
    ("simulate", ("urdf", "sdf", "mujoco", "isaac", "gazebo", "simulate")),
]


def classify_intent(prompt: str) -> str:
    p = prompt.lower()
    for intent, keywords in _INTENT_RULES:
        if any(k in p for k in keywords):
            return intent
    return "generate"


class PhysicalAIAgent:
    """Single-part design agent: prompt in, simulation-ready bundle out."""

    def __init__(
        self,
        generation_service=None,
        kb: Optional[KnowledgeBase] = None,
        use_llm_reasoning: bool = True,
    ):
        self._service = generation_service
        self.kb = kb or get_knowledge_base()
        self.use_llm_reasoning = use_llm_reasoning

    @property
    def service(self):
        if self._service is None:
            from app.services.ofl_generation_service import OFLGenerationService

            self._service = OFLGenerationService(require_llm=True)
        return self._service

    # ── main entry ───────────────────────────────────────────────

    def design(
        self,
        prompt: str,
        material: Optional[str] = None,
        max_repairs: int = 2,
    ) -> dict:
        t0 = time.time()
        trace: list[dict] = []

        def step(phase: str, **data):
            trace.append({"phase": phase, "t_ms": round((time.time() - t0) * 1000), **data})

        # 1. Intent
        intent = classify_intent(prompt)
        step("intent", intent=intent)

        # 2. Source standard parts (deterministic catalog lookup)
        parts = source_parts(prompt, self.kb)
        step(
            "source",
            parts=[{"part_id": p["part_id"], "matched": p["matched_text"]} for p in parts],
        )

        # 3. Design reasoning (LLM plan, deterministic fallback)
        llm = None
        if self.use_llm_reasoning:
            try:
                llm = self.service.llm
            except Exception as e:
                logger.warning(f"reasoning LLM unavailable: {e}")
        plan = design_reasoning(prompt, parts, self.kb, llm=llm)
        if material:
            plan["material"] = material
        step("reason", mode=plan.get("reasoning_mode"), plan=plan)

        # 4-5. Generate OFL with grounded brief; validate + self-repair inside
        brief = plan_to_brief(prompt, plan, parts, self.kb)
        step("design", status="generating", brief=brief)
        response = self.service.generate_from_prompt(brief, max_repairs=max_repairs)
        step(
            "design",
            status="success" if response.success else "failed",
            repair_attempts=response.repair_attempts,
            error=response.error,
        )

        bundle: dict = {
            "success": response.success,
            "intent": intent,
            "prompt": prompt,
            "reasoning": plan,
            "sourced_parts": parts,
            "ofl_code": response.ofl_code,
            "files": response.files.model_dump() if response.files else {},
            "stats": response.stats.model_dump() if response.stats else None,
            "repair_attempts": response.repair_attempts,
            "error": response.error,
            "analysis": None,
            "urdf": None,
            "sdf": None,
            "trace": trace,
            "generation_time_ms": round((time.time() - t0) * 1000),
        }
        if not response.success:
            return bundle

        # 6. Analyze + simulate from the produced STL
        stl_path = self._local_artifact_path(response.files.stl)
        if stl_path is None:
            step("simulate", status="skipped", reason="local STL not found")
            bundle["generation_time_ms"] = round((time.time() - t0) * 1000)
            return bundle

        material_key = plan.get("material") or "aluminum_6061_t6"
        try:
            analysis = analyze_part(stl_path, material_key, self.kb)
            step(
                "analyze",
                score=analysis["manufacturability_score"],
                issues=len(analysis["issues"]),
            )
            bundle["analysis"] = analysis
        except Exception as e:
            logger.warning(f"analysis failed: {e}")
            step("analyze", status="failed", error=str(e))

        try:
            density = self.kb.material(material_key)["density_g_cm3"]
            props = mass_properties(stl_path, density)
            part_name = plan.get("part_name") or "part"
            part_name = re.sub(r"[^A-Za-z0-9_]", "_", part_name)
            mesh_name = os.path.basename(stl_path)
            urdf = generate_urdf(
                part_name, mesh_name, mesh_name, props,
                material_name=material_key, joints=plan.get("joints") or [],
            )
            sdf = generate_sdf(part_name, mesh_name, mesh_name, props)
            bundle["urdf"] = urdf
            bundle["sdf"] = sdf
            bundle["mass_properties"] = props

            urdf_path, sdf_path = self._write_sim_files(stl_path, part_name, urdf, sdf)
            out_dir = os.path.basename(os.path.dirname(stl_path))
            if urdf_path:
                bundle["files"]["urdf"] = (
                    f"/api/v1/ofl/download/{out_dir}/{os.path.basename(urdf_path)}"
                )
            if sdf_path:
                bundle["files"]["sdf"] = (
                    f"/api/v1/ofl/download/{out_dir}/{os.path.basename(sdf_path)}"
                )
            step("simulate", status="success", mass_kg=round(props["mass_kg"], 4))
        except Exception as e:
            logger.warning(f"simulation export failed: {e}")
            step("simulate", status="failed", error=str(e))

        bundle["generation_time_ms"] = round((time.time() - t0) * 1000)
        return bundle

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _local_artifact_path(stl_url: Optional[str]) -> Optional[str]:
        """Map /api/v1/ofl/download/<request_id>/<name> back to the sandbox dir."""
        if not stl_url:
            return None
        m = re.search(r"/download/([^/]+)/([^/?]+)", stl_url)
        if not m:
            return None
        from app.services.ofl_sandbox import OUTPUT_BASE

        path = os.path.join(OUTPUT_BASE, m.group(1), m.group(2))
        return path if os.path.exists(path) else None

    @staticmethod
    def _write_sim_files(stl_path: str, part_name: str, urdf: str, sdf: str):
        """Write URDF/SDF next to the meshes (relative refs resolve there);
        publish to durable storage when configured."""
        out_dir = os.path.dirname(stl_path)
        urdf_path = os.path.join(out_dir, f"{part_name}.urdf")
        sdf_path = os.path.join(out_dir, f"{part_name}.sdf")
        try:
            with open(urdf_path, "w", encoding="utf-8") as f:
                f.write(urdf)
            with open(sdf_path, "w", encoding="utf-8") as f:
                f.write(sdf)
        except OSError as e:
            logger.warning(f"could not write sim files: {e}")
            return None, None

        try:
            from app.config import settings

            if settings.is_s3_configured:
                from pathlib import Path

                from app.services.storage import get_storage

                storage = get_storage()
                request_id = os.path.basename(out_dir)
                for path in (urdf_path, sdf_path):
                    storage.publish(
                        Path(path), key=f"ofl/{request_id}/{os.path.basename(path)}"
                    )
        except Exception as e:
            logger.warning(f"sim file upload failed: {e}")
        return urdf_path, sdf_path
