"""Locate a Python interpreter that can ``import FreeCAD``.

There were three copies of this logic — ``orion/forge.py``,
``orion/gate_sidetype.py`` and ``app/services/blueprint_service.py`` — and each
hardcoded ``C:/Program Files/FreeCAD 1.1/bin/python.exe``. A literal version in
a path is a pin nobody declared: install 1.2 beside 1.1 and every one of those
call sites keeps silently building on the old kernel, which is exactly the
class of drift ``deploy/modal_builder.FREECAD_VERSION`` exists to prevent on the
cloud side.

Two of the three also disagreed about precedence, and ``gate_sidetype`` had it
backwards: it consulted the hardcoded path *before* ``ORION_FREECAD_PYTHON``,
so on any box with a Program Files install the override was dead and there was
no way to point the gate at a different kernel — including for the purpose of
testing an upgrade.

Resolution order, one place, highest-version-first:

1. ``ORION_FREECAD_PYTHON`` — an explicit choice always wins.
2. This very interpreter, if it can already import FreeCAD (the container case,
   where FreeCAD is installed into the running environment).
3. Windows ``Program Files`` installs, newest version first.
4. ``freecadcmd`` / ``FreeCADCmd`` on PATH (Linux distro and conda installs).
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import sys

#: Where FreeCAD's Windows installer puts things. Globbed rather than listed so
#: a new release is found the day it is installed.
_WINDOWS_GLOBS = (
    r"C:/Program Files/FreeCAD*/bin/python.exe",
    r"C:/Program Files (x86)/FreeCAD*/bin/python.exe",
)


def _version_key(path: str) -> tuple:
    """Sort key ordering ``FreeCAD 1.10`` above ``FreeCAD 1.9`` above ``1.1``.

    Numeric-aware on purpose: a plain string sort puts "1.10" before "1.9",
    which would quietly select an older kernel the moment a two-digit minor
    ships.
    """
    nums = tuple(int(n) for n in re.findall(r"\d+", path))
    return (nums, path)


def candidates() -> list[str]:
    """Every interpreter this box offers, best first. Exposed for diagnostics —
    ``/health`` and the upgrade harness both want to show what was *available*,
    not just what was chosen."""
    found: list[str] = []

    env = os.environ.get("ORION_FREECAD_PYTHON")
    if env and os.path.exists(env):
        found.append(env)

    try:
        import FreeCAD  # noqa: F401,PLC0415

        found.append(sys.executable)
    except ImportError:
        pass

    windows: list[str] = []
    for pattern in _WINDOWS_GLOBS:
        windows.extend(p for p in glob.glob(pattern) if os.path.exists(p))
    found.extend(sorted(set(windows), key=_version_key, reverse=True))

    for exe in ("freecadcmd", "FreeCADCmd"):
        which = shutil.which(exe)
        if which:
            found.append(which)

    seen, ordered = set(), []
    for p in found:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def freecad_python() -> str:
    """The interpreter to build with, or raise if the box has none."""
    for path in candidates():
        return path
    raise RuntimeError(
        "no FreeCAD interpreter found; set ORION_FREECAD_PYTHON to one that "
        "can `import FreeCAD`"
    )
