"""OrionFlow FreeCAD addon (embedded-Python side of the bridge).

Stdlib + FreeCAD + PySide only. Nothing here may import the harness package or
any modern-Python-only dependency, because this runs inside FreeCAD's embedded
interpreter. The only shared code it touches is ``orion_agent.shared`` (which
is itself stdlib-only).
"""
