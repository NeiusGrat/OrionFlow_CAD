"""Isolated execution of generated CAD code.

Generated Build123d / FreeCAD-Python code never runs in the harness process or
in FreeCAD's interpreter. It runs in a separate, resource-capped, network-less
subprocess; only the resulting artifacts (STEP/STL/GLB) are handed back and
imported into the live document by the addon.
"""

from orion_agent.harness.sandbox.manager import SandboxManager, SandboxResult

__all__ = ["SandboxManager", "SandboxResult"]
