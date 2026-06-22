"""OrionFlow harness — the out-of-process agent service.

Runs a modern Python interpreter, independent of FreeCAD. Hosts the agent
loop, the LLM client abstraction, the tool registry, the sandbox manager and
the trajectory logger. Talks to the addon over the bridge contract and to the
LLM backend over an OpenAI-compatible interface.
"""
