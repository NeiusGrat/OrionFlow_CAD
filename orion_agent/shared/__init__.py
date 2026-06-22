"""Shared, versioned contracts between the FreeCAD addon and the harness.

Nothing in here may import FreeCAD or any heavy ML dependency: both the
embedded-Python addon and the modern-Python harness import this package.
"""

from orion_agent.shared.config import OrionConfig, get_config

__all__ = ["OrionConfig", "get_config"]
