
"""Headless launcher for the OrionFlow bridge.

Run inside FreeCAD's console interpreter so the eval harness / CI can drive a
real FreeCAD document without a GUI:

    freecadcmd orion_agent/addon/freecad_headless.py [document.FCStd]

Optionally opens a document passed as the first argument, then starts the
bridge and blocks. With no GUI, the task queue runs capabilities inline.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def run() -> None:
    try:
        import FreeCAD  # type: ignore
    except ImportError:
        print("[orion] must be run inside FreeCAD (freecadcmd)")  # noqa: T201
        return

    args = [a for a in sys.argv[1:] if a.endswith((".FCStd", ".fcstd"))]
    if args and os.path.exists(args[0]):
        FreeCAD.open(args[0])
        print(f"[orion] opened {args[0]}")  # noqa: T201

    from orion_agent.addon.bridge_server import serve_headless
    serve_headless()


if __name__ == "__main__":
    run()
