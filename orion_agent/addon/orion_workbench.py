"""OrionFlow FreeCAD workbench: docks the chat panel and manages the bridge.

Importing this module is side-effect free; the workbench is registered by
``InitGui.py``. ``Activated`` lazily builds the dock panel, installs the
GUI-thread task-queue driver, and auto-starts the bridge server.
"""


from __future__ import annotations

import os
import FreeCADGui


_LOGO = os.path.join(os.path.dirname(__file__), "resources", "orionflow_logo.png")


class OrionFlowWorkbench(FreeCADGui.Workbench):
    """Registered via ``FreeCADGui.addWorkbench``."""

    MenuText = "OrionFlow"
    ToolTip = "OrionFlow — AI CAD copilot (k2v2 think)"
    Icon = _LOGO if os.path.exists(_LOGO) else ""

    def __init__(self):
        self._dock = None
        self._panel = None

    # FreeCAD lifecycle ------------------------------------------------- #
    def Initialize(self):
        # Commands/toolbars could be registered here; the panel carries the UI.
        pass

    def Activated(self):
        self._ensure_panel()
        if self._dock is not None:
            self._dock.setVisible(True)

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    # internals --------------------------------------------------------- #
    def _ensure_panel(self):
        if self._dock is not None:
            return
        try:
            from PySide6 import QtCore, QtWidgets  # type: ignore
        except ImportError:
            try:
                from PySide2 import QtCore, QtWidgets  # type: ignore
            except ImportError:
                from PySide import QtCore, QtWidgets  # type: ignore

        import FreeCADGui  # type: ignore
        from orion_agent.addon.chat_panel import OrionChatPanel
        from orion_agent.addon.task_queue import get_task_queue
        from orion_agent.addon.bridge_server import start_bridge

        # Marshal geometry ops onto the GUI thread.
        get_task_queue().install_driver()

        main = FreeCADGui.getMainWindow()
        dock = QtWidgets.QDockWidget("OrionFlow Copilot", main)
        dock.setObjectName("OrionFlowDock")
        panel = OrionChatPanel(dock)
        dock.setWidget(panel)
        dock.setMinimumWidth(340)
        main.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

        self._dock = dock
        self._panel = panel

        # Auto-start the bridge so the harness can connect immediately.
        try:
            start_bridge()
            panel._refresh_status()
        except Exception:  # noqa: BLE001
            pass
