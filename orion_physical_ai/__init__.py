"""Orion Physical AI — the design harness that turns a natural-language brief
into a simulation-ready part: OFL code, validated geometry, DFM analysis, and
URDF/SDF with real mass properties.

Public API:
    PhysicalAIAgent      — prompt → full design bundle (the harness loop)
    KnowledgeBase        — materials, standards, heuristics, DFM, parts catalog
    source_parts()       — detect standard parts in a brief (catalog-grounded)
    design_reasoning()   — structured engineering plan before any code
    generate_urdf() / generate_sdf() / mass_properties() — simulation export
    analyze_part()       — deterministic DFM checks + manufacturability score
"""

from .agent import PhysicalAIAgent, classify_intent
from .analyze import analyze_part
from .knowledge import KnowledgeBase, get_knowledge_base
from .reasoning import design_reasoning, knowledge_context, plan_to_brief
from .simulate import generate_sdf, generate_urdf, mass_properties
from .sourcing import source_parts

__all__ = [
    "PhysicalAIAgent",
    "KnowledgeBase",
    "get_knowledge_base",
    "classify_intent",
    "source_parts",
    "design_reasoning",
    "knowledge_context",
    "plan_to_brief",
    "analyze_part",
    "generate_urdf",
    "generate_sdf",
    "mass_properties",
]

__version__ = "0.1.0"
