"""GUI-thread task queue for the FreeCAD addon.

All geometry- and GUI-touching work must happen on FreeCAD's main thread. The
bridge HTTP server runs handler callbacks on worker threads, so every
capability that touches the document is funnelled through here:

  * **GUI up**   — the worker thread enqueues a callable and blocks on an
    Event; a QTimer installed on the GUI thread drains the queue, runs the
    callable, and signals completion.
  * **Headless** — there is no Qt event loop (``freecadcmd``), so callables run
    inline on the calling thread. FreeCAD document mutation is safe there
    because there is no competing GUI thread.

This indirection is the mitigation for the GUI-thread deadlock risk in the
build plan: nothing geometry-related is ever called off the main thread when a
GUI is present.
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable, Optional


class _Task:
    __slots__ = ("fn", "event", "result", "error")

    def __init__(self, fn: Callable[[], Any]):
        self.fn = fn
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


class GuiTaskQueue:
    def __init__(self) -> None:
        self._q: "queue.Queue[_Task]" = queue.Queue()
        self._gui_mode = False
        self._timer = None  # QTimer, set by install_driver

    # ---- called from the GUI thread once, at panel/workbench startup ----- #
    def install_driver(self, interval_ms: int = 30) -> bool:
        """Install a QTimer that drains the queue on the GUI thread."""
        try:
            from PySide import QtCore  # noqa
        except ImportError:
            try:
                from PySide2 import QtCore  # type: ignore  # noqa
            except ImportError:
                from PySide6 import QtCore  # type: ignore  # noqa

        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._drain)
        self._timer.start(interval_ms)
        self._gui_mode = True
        return True

    def _drain(self) -> None:
        # Drain whatever is queued without blocking the GUI.
        while True:
            try:
                task = self._q.get_nowait()
            except queue.Empty:
                return
            self._run(task)

    @staticmethod
    def _run(task: _Task) -> None:
        try:
            task.result = task.fn()
        except BaseException as exc:  # noqa: BLE001 - reported to caller
            task.error = exc
        finally:
            task.event.set()

    # ---- called from any (worker) thread --------------------------------- #
    def submit(self, fn: Callable[[], Any], timeout: float = 60.0) -> Any:
        """Run ``fn`` on the GUI thread (or inline if headless) and return its result."""
        if not self._gui_mode:
            # Headless: no event loop to marshal onto; run inline.
            return fn()

        task = _Task(fn)
        self._q.put(task)
        if not task.event.wait(timeout=timeout):
            raise TimeoutError("GUI task timed out")
        if task.error is not None:
            raise task.error
        return task.result

    def is_gui(self) -> bool:
        return self._gui_mode


# Module-level singleton shared by the bridge server and the panel.
_QUEUE: Optional[GuiTaskQueue] = None


def get_task_queue() -> GuiTaskQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = GuiTaskQueue()
    return _QUEUE


def format_exc(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()
