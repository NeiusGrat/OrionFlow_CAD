"""FreeCAD GUI entry point for the OrionFlow addon.

FreeCAD executes ``InitGui.py`` of every addon in its ``Mod`` path at GUI
startup. We make ``orion_agent`` importable (it lives at the repo root during
development) and register the workbench.

Two FreeCAD-specific quirks are handled here:

* FreeCAD 1.1 does NOT always define ``__file__`` when it execs this script,
  so we fall back to resolving the addon's ``Mod`` folder via the FreeCAD API.
* In a dev checkout the ``Mod/OrionFlow`` entry is a directory *junction* to
  ``orion_agent/addon``; plain ``abspath`` keeps the junction path (which is
  two levels under ``Mod``, not the repo), so we ``realpath`` it to reach the
  real ``orion_agent/`` parent and put the repo root on ``sys.path``.
"""

import os
import sys


def _addon_dir():
    """Real (junction-resolved) directory that holds this InitGui.py."""
    try:
        return os.path.dirname(os.path.realpath(__file__))
    except NameError:
        pass
    # __file__ missing: ask FreeCAD where its Mod folders are and find ours.
    try:
        import FreeCAD  # type: ignore

        bases = []
        for getter in ("getUserAppDataDir", "getResourceDir", "getHomePath"):
            fn = getattr(FreeCAD, getter, None)
            if fn:
                try:
                    bases.append(fn())
                except Exception:  # noqa: BLE001
                    pass
        for base in bases:
            cand = os.path.join(base, "Mod", "OrionFlow")
            if os.path.isfile(os.path.join(cand, "InitGui.py")):
                return os.path.realpath(cand)
    except Exception:  # noqa: BLE001
        pass
    return None


_HERE = _addon_dir()
if _HERE:
    # _HERE == <repo>/orion_agent/addon ; repo root is two levels up. The second
    # candidate covers a flat Mod/OrionFlow layout where addon files sit beside
    # the orion_agent package.
    for _candidate in (
        os.path.abspath(os.path.join(_HERE, "..", "..")),
        os.path.abspath(os.path.join(_HERE, "..")),
    ):
        if os.path.isdir(os.path.join(_candidate, "orion_agent")) and _candidate not in sys.path:
            sys.path.insert(0, _candidate)
            break

try:
    import FreeCADGui  # type: ignore
    from orion_agent.addon.orion_workbench import OrionFlowWorkbench

    FreeCADGui.addWorkbench(OrionFlowWorkbench())
except Exception as exc:  # noqa: BLE001
    import FreeCAD  # type: ignore

    FreeCAD.Console.PrintError(f"[OrionFlow] failed to register workbench: {exc}\n")
    import traceback

    FreeCAD.Console.PrintError(traceback.format_exc() + "\n")
