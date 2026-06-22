"""OrionFlow chat dock panel — the thin UI embedded in FreeCAD.

The panel is intentionally thin: it forwards the user's text to the harness
service over HTTP and renders the streamed answer, tool-call trace and any
rendered views. All intelligence lives in the harness.

Branded with the OrionFlow logo and a professional dark theme so it reads as a
first-class copilot side panel inside FreeCAD.

PySide is imported defensively (PySide / PySide2 / PySide6) to match whatever
Qt binding the host FreeCAD ships.
"""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.request
import uuid

# ---- Qt binding (match host FreeCAD) ------------------------------------- #
try:
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
    except ImportError:
        from PySide import QtCore, QtGui, QtWidgets  # type: ignore

from orion_agent.shared.config import get_config

_RES = os.path.join(os.path.dirname(__file__), "resources")
_LOGO = os.path.join(_RES, "orionflow_logo.png")

# ---- brand palette -------------------------------------------------------- #
BG = "#0d1117"
PANEL = "#161b22"
CARD = "#1c2330"
ACCENT = "#ff6b2c"          # Orion orange
ACCENT_DIM = "#b8501f"
TEXT = "#e6edf3"
MUTED = "#8b949e"
USER_BUBBLE = "#21304a"
TOOL_BUBBLE = "#15212b"


class _HarnessStarter(QtCore.QThread):
    """Ensures the harness service is up, spawning it if needed, off-GUI."""

    done = QtCore.Signal(bool, str)

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg

    def run(self):  # noqa: D401
        from orion_agent.addon import harness_launcher
        ok, msg = harness_launcher.ensure_harness(self._cfg)
        self.done.emit(ok, msg)


class _HarnessWorker(QtCore.QThread):
    """Runs one chat round-trip to the harness off the GUI thread."""

    finished_ok = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, cfg, url: str, payload: dict, timeout: float = 900.0):
        super().__init__()
        self._cfg = cfg
        self._url = url
        self._payload = payload
        self._timeout = timeout

    def run(self):  # noqa: D401
        try:
            self._post_chat()
        except urllib.error.URLError as exc:
            # Connection refused usually means the harness is not up yet — try
            # to start it once, then retry the request.
            if self._try_start_harness():
                try:
                    self._post_chat()
                    return
                except Exception as exc2:  # noqa: BLE001
                    self.failed.emit(str(exc2))
                    return
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _post_chat(self):
        data = json.dumps(self._payload).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        self.finished_ok.emit(body)

    def _try_start_harness(self) -> bool:
        try:
            from orion_agent.addon import harness_launcher
            ok, _ = harness_launcher.ensure_harness(self._cfg)
            return ok
        except Exception:  # noqa: BLE001
            return False


class OrionChatPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.session_id = uuid.uuid4().hex
        self._worker = None
        self._starter = None
        self._build_ui()
        self._apply_theme()
        self._greet()
        self._ensure_harness_async()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- header with logo + title -----------------------------------
        header = QtWidgets.QFrame()
        header.setObjectName("header")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)

        logo = QtWidgets.QLabel()
        if os.path.exists(_LOGO):
            pix = QtGui.QPixmap(_LOGO).scaledToHeight(
                34, QtCore.Qt.SmoothTransformation
            )
            logo.setPixmap(pix)
        else:
            logo.setText("◆")
        hl.addWidget(logo)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(0)
        title = QtWidgets.QLabel("OrionFlow Copilot")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("k2v2 think · reasoning CAD agent")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hl.addLayout(title_box)
        hl.addStretch(1)

        self.status_dot = QtWidgets.QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setToolTip("Bridge status")
        hl.addWidget(self.status_dot)
        root.addWidget(header)

        # --- pillar / tier strip ----------------------------------------
        strip = QtWidgets.QFrame()
        strip.setObjectName("strip")
        sl = QtWidgets.QHBoxLayout(strip)
        sl.setContentsMargins(12, 4, 12, 4)
        self.tier_label = QtWidgets.QLabel("Model: —")
        self.tier_label.setObjectName("stripLabel")
        self.pillar_label = QtWidgets.QLabel("Pillar: auto")
        self.pillar_label.setObjectName("stripLabel")
        sl.addWidget(self.tier_label)
        sl.addStretch(1)
        sl.addWidget(self.pillar_label)
        root.addWidget(strip)

        # --- transcript --------------------------------------------------
        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setObjectName("transcript")
        root.addWidget(self.transcript, 1)

        # --- input -------------------------------------------------------
        input_frame = QtWidgets.QFrame()
        input_frame.setObjectName("inputFrame")
        il = QtWidgets.QVBoxLayout(input_frame)
        il.setContentsMargins(10, 8, 10, 10)
        il.setSpacing(6)

        self.input = QtWidgets.QPlainTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText(
            "Ask about the open model, or request an edit…  (Ctrl+Enter to send)"
        )
        self.input.setFixedHeight(70)
        il.addWidget(self.input)

        btn_row = QtWidgets.QHBoxLayout()
        self.bridge_btn = QtWidgets.QPushButton("Start bridge")
        self.bridge_btn.setObjectName("ghostBtn")
        self.bridge_btn.clicked.connect(self._toggle_bridge)
        btn_row.addWidget(self.bridge_btn)
        btn_row.addStretch(1)
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(self.send_btn)
        il.addLayout(btn_row)
        root.addWidget(input_frame)

        # Ctrl+Enter to send
        send_sc = QtGui.QShortcut(
            QtGui.QKeySequence("Ctrl+Return"), self.input, self._on_send
        )
        send_sc.setContext(QtCore.Qt.WidgetShortcut)

        self._refresh_status()

    # ------------------------------------------------------------------ #
    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {BG}; color: {TEXT};
                       font-family: 'Segoe UI','Inter',sans-serif; font-size: 13px; }}
            #header {{ background: {PANEL}; border-bottom: 1px solid #21262d; }}
            #title {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
            #subtitle {{ font-size: 11px; color: {ACCENT}; }}
            #statusDot {{ font-size: 14px; color: #d9534f; }}
            #strip {{ background: {PANEL}; border-bottom: 1px solid #21262d; }}
            #stripLabel {{ color: {MUTED}; font-size: 11px; }}
            #transcript {{ background: {BG}; border: none; padding: 8px; }}
            #inputFrame {{ background: {PANEL}; border-top: 1px solid #21262d; }}
            #input {{ background: {CARD}; border: 1px solid #2a3340; border-radius: 8px;
                      padding: 6px; color: {TEXT}; }}
            #sendBtn {{ background: {ACCENT}; color: #1a1106; border: none;
                        border-radius: 7px; padding: 6px 18px; font-weight: 700; }}
            #sendBtn:hover {{ background: {ACCENT_DIM}; }}
            #ghostBtn {{ background: transparent; color: {MUTED};
                         border: 1px solid #2a3340; border-radius: 7px; padding: 6px 12px; }}
            #ghostBtn:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
        """)

    # ------------------------------------------------------------------ #
    # rendering helpers
    # ------------------------------------------------------------------ #
    def _append_html(self, fragment: str):
        self.transcript.append(fragment)
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _bubble(self, who: str, text: str, color: str, align: str):
        safe = html.escape(text).replace("\n", "<br>")
        self._append_html(
            f"""<table width="100%" cellspacing="0" cellpadding="0"><tr>
            <td align="{align}">
              <table cellpadding="8" cellspacing="0" style="background:{color};
                     border-radius:10px; max-width:430px;">
                <tr><td>
                  <div style="color:{MUTED};font-size:10px;margin-bottom:3px;">{who}</div>
                  <div style="color:{TEXT};">{safe}</div>
                </td></tr></table>
            </td></tr></table><br>"""
        )

    def _tool_trace(self, name: str, ok: bool, preview: str):
        icon = "✓" if ok else "✗"
        color = "#3fb950" if ok else "#f85149"
        safe = html.escape(preview)[:240]
        self._append_html(
            f"""<table width="100%"><tr><td align="left">
            <div style="background:{TOOL_BUBBLE};border-left:3px solid {ACCENT};
                 border-radius:6px;padding:6px 10px;max-width:430px;
                 font-family:Consolas,monospace;font-size:11px;color:{MUTED};">
              <span style="color:{color};">{icon}</span>
              <b style="color:{ACCENT};">{html.escape(name)}</b><br>
              <span>{safe}</span>
            </div></td></tr></table><br>"""
        )

    def _greet(self):
        self._append_html(
            f"""<div style="text-align:center;color:{MUTED};font-size:11px;
                 padding:14px;">OrionFlow copilot ready · grounded answers from real
                 topology, never guessed.<br>Open a model and ask a question.</div>"""
        )

    # ------------------------------------------------------------------ #
    def _ensure_harness_async(self):
        """Bring the harness service up in the background at panel startup."""
        self._starter = _HarnessStarter(self.cfg)
        self._starter.done.connect(self._on_harness_ready)
        self._starter.start()

    def _on_harness_ready(self, ok: bool, msg: str):
        if ok:
            self._append_html(
                f'<div style="text-align:center;color:{MUTED};font-size:10px;'
                f'padding:4px;">● harness connected · ready to answer</div>'
            )
        else:
            self._append_html(
                f'<div style="text-align:center;color:#d9534f;font-size:10px;'
                f'padding:4px;">⚠ harness not reachable: {html.escape(msg)}<br>'
                f'It will be retried on your next message.</div>'
            )

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #
    def _on_send(self):
        text = self.input.toPlainText().strip()
        if not text or (self._worker and self._worker.isRunning()):
            return
        self.input.clear()
        self._bubble("You", text, USER_BUBBLE, "right")
        self._bubble("OrionFlow", "Thinking…", CARD, "left")
        self.send_btn.setEnabled(False)

        cfg = self.cfg.harness
        url = f"http://{cfg.host}:{cfg.port}/chat"
        payload = {
            "message": text,
            "session_id": self.session_id,
            "document": self._active_doc_name(),
        }
        self._worker = _HarnessWorker(self.cfg, url, payload)
        self._worker.finished_ok.connect(self._on_reply)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_reply(self, body: dict):
        self.send_btn.setEnabled(True)
        for tc in body.get("tool_calls", []):
            self._tool_trace(
                tc.get("name", "tool"), tc.get("ok", True), tc.get("result_preview", "")
            )
        for art in body.get("artifacts", []):
            if art.get("kind") == "render" and os.path.exists(art.get("path", "")):
                self._append_html(
                    f'<img src="{art["path"]}" width="280"><br>'
                )
        answer = body.get("final_answer") or "(no answer)"
        self._bubble("OrionFlow", answer, CARD, "left")
        if body.get("pillar"):
            self.pillar_label.setText(f"Pillar: {body['pillar']}")
        if body.get("model_tier"):
            self.tier_label.setText(f"Model: Tier {body['model_tier']}")

    def _on_error(self, msg: str):
        self.send_btn.setEnabled(True)
        self._bubble(
            "OrionFlow", f"⚠ Could not reach the harness service.\n{msg}", CARD, "left"
        )

    def _toggle_bridge(self):
        try:
            from orion_agent.addon.bridge_server import get_server
            server = get_server()
            if server.running:
                server.stop()
            else:
                server.start()
        except Exception as exc:  # noqa: BLE001
            self._bubble("OrionFlow", f"Bridge error: {exc}", CARD, "left")
        self._refresh_status()

    def _refresh_status(self):
        try:
            from orion_agent.addon.bridge_server import get_server
            running = get_server().running
        except Exception:  # noqa: BLE001
            running = False
        self.status_dot.setStyleSheet(
            f"color: {'#3fb950' if running else '#d9534f'};"
        )
        self.status_dot.setToolTip("Bridge running" if running else "Bridge stopped")
        self.bridge_btn.setText("Stop bridge" if running else "Start bridge")

    @staticmethod
    def _active_doc_name() -> str:
        try:
            import FreeCAD  # type: ignore
            return FreeCAD.ActiveDocument.Name if FreeCAD.ActiveDocument else ""
        except Exception:  # noqa: BLE001
            return ""
