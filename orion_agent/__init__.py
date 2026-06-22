"""OrionFlow Agent Harness.

An AI copilot that lives inside FreeCAD and can query, modify, generate and
reason over existing parametric CAD models from natural language.

Three cooperating processes:
  * ``orion_agent.addon``   — thin FreeCAD workbench (chat dock + bridge server)
  * ``orion_agent.harness`` — out-of-process agent loop, LLM client, sandbox
  * ``orion_agent.shared``  — the versioned contracts shared by both halves

See ``orion_agent.shared.contract`` for the bridge contract and
``orion_agent.shared.trajectory`` for the v1.0 trajectory schema.
"""

__version__ = "0.1.0"
