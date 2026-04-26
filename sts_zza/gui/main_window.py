from __future__ import annotations

import logging
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
    QVBoxLayout,
)

from ..config.station_config import StationConfig
from ..logic.train_manager import ZugManager
from ..protocol.client import STSClient
from ..protocol.models import BahnsteigInfo
from .dispatcher_view import DispatcherView
from .passenger_view import PassengerView

logger = logging.getLogger(__name__)

_IDX_PLACEHOLDER  = 0
_IDX_PASSENGER    = 1
_IDX_DISPATCHER   = 2

_REFRESH_INTERVAL_MS = 30_000  # poll zugliste every 30 s


class _PlaceholderView(QWidget):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #8899aa; font-size: 13pt;")
        layout.addWidget(label)
        self.setStyleSheet("background-color: #000000;")


class ZZAMainWindow(QMainWindow):
    """
    Hauptfenster. Verwaltet drei Stacked-Views:
      0 — Platzhalter (während Verbindungsaufbau / Gleisauswahl)
      1 — Fahrgast-Ansicht (grafische ZZA-Boards)
      2 — Fdl-Ansicht (Tabelle)

    Empfängt STSClient-Signale, hält ZugManager auf dem aktuellen Stand
    und löst alle 30 s einen Zuglistenabgleich aus.
    """

    def __init__(self,
                 client: STSClient,
                 config: StationConfig,
                 zug_manager: ZugManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._client = client
        self._config = config
        self._zug_manager = zug_manager
        self._selected_platforms: List[str] = []

        self._setup_ui()
        self._connect_signals()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._poll_zugliste)

    # ------------------------------------------------------------------
    # Public API (called from app.py)
    # ------------------------------------------------------------------

    def set_config(self, config: StationConfig) -> None:
        self._config = config
        self._zug_manager._config = config
        self.setWindowTitle(f"STS ZZA — {config.station_name}")

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("STS ZZA — Zugzielanzeiger")
        self.setMinimumSize(960, 560)

        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(
            "QMenuBar { background-color: #1b2838; color: #f0f4f8; }"
            "QMenuBar::item:selected { background-color: #2a4060; }"
            "QMenu { background-color: #1b2838; color: #f0f4f8; }"
            "QMenu::item:selected { background-color: #2a4060; }"
        )

        view_menu = menu_bar.addMenu("Ansicht")
        self._action_fahrgast = view_menu.addAction("Fahrgast-Ansicht")
        self._action_fdl      = view_menu.addAction("Fdl-Ansicht")
        self._action_fahrgast.setEnabled(False)
        self._action_fdl.setEnabled(False)

        tools_menu = menu_bar.addMenu("Werkzeuge")
        self._action_editor = tools_menu.addAction("Analyse && Editor")
        self._action_editor.setEnabled(False)

        self._stack = QStackedWidget()
        self._placeholder    = _PlaceholderView("Verbinde mit StellwerkSim …")
        self._passenger_view = PassengerView()
        self._dispatcher_view = DispatcherView()

        self._stack.addWidget(self._placeholder)      # index 0
        self._stack.addWidget(self._passenger_view)   # index 1
        self._stack.addWidget(self._dispatcher_view)  # index 2
        self.setCentralWidget(self._stack)

        status_bar = QStatusBar()
        status_bar.setStyleSheet(
            "QStatusBar { background-color: #111111; color: #8899aa; }")
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("Verbinde …")

    def _connect_signals(self) -> None:
        self._client.connected.connect(self._on_connected)
        self._client.sig_anlageninfo.connect(self._on_anlageninfo)
        self._client.sig_bahnsteigliste.connect(self._on_bahnsteigliste)
        self._client.sig_zugliste.connect(self._on_zugliste)
        self._client.sig_zugdetails.connect(self._on_zugdetails)
        self._client.sig_zugfahrplan.connect(self._on_zugfahrplan)

        self._action_fahrgast.triggered.connect(
            lambda: self._stack.setCurrentIndex(_IDX_PASSENGER))
        self._action_fdl.triggered.connect(
            lambda: self._stack.setCurrentIndex(_IDX_DISPATCHER))
        self._action_editor.triggered.connect(self._open_editor)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        self.statusBar().showMessage("Verbunden — lade Anlageninformationen …")
        self._client.request_anlageninfo()
        self._client.request_bahnsteigliste()

    def _on_anlageninfo(self, info) -> None:
        self.setWindowTitle(f"STS ZZA — {info.name}")
        self.statusBar().showMessage(f"Verbunden mit: {info.name}")
        logger.info("Anlage: %s (AID=%s)", info.name, info.aid)

    def _on_bahnsteigliste(self, bahnsteige: List[BahnsteigInfo]) -> None:
        from .platform_selector import PlatformSelectorDialog
        dlg = PlatformSelectorDialog(bahnsteige, self._config.bahnsteige, self)
        if not dlg.exec():
            self.statusBar().showMessage("Keine Bahnsteige ausgewählt.")
            return

        self._selected_platforms = dlg.selected_platforms()
        self._config.bahnsteige = self._selected_platforms
        self._config.save()

        self._passenger_view.set_platforms(self._selected_platforms)

        self._action_fahrgast.setEnabled(True)
        self._action_fdl.setEnabled(True)
        self._action_editor.setEnabled(True)

        # Default: Fahrgast-Ansicht
        self._stack.setCurrentIndex(_IDX_PASSENGER)
        self.statusBar().showMessage(
            f"{len(self._selected_platforms)} Gleis(e) ausgewählt — lade Züge …")

        self._poll_zugliste()
        self._refresh_timer.start()

    def _on_zugliste(self, zl: dict) -> None:
        new_zids = self._zug_manager.update_zugliste(zl)
        for zid in new_zids:
            self._client.request_zugdetails(zid)
        # Refresh all known trains too
        for zid in zl:
            self._client.request_zugdetails(zid)

    def _on_zugdetails(self, zid: int, details) -> None:
        changed = self._zug_manager.update_details(zid, details)
        if changed:
            self._client.request_zugfahrplan(zid)
        self._refresh_views()

    def _on_zugfahrplan(self, zid: int, plan) -> None:
        self._zug_manager.update_fahrplan(zid, plan)
        self._refresh_views()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _poll_zugliste(self) -> None:
        self._client.request_zugliste()

    def _refresh_views(self) -> None:
        idx = self._stack.currentIndex()
        if idx == _IDX_PASSENGER:
            self._passenger_view.refresh(self._zug_manager)
        elif idx == _IDX_DISPATCHER:
            self._dispatcher_view.refresh(self._zug_manager)

    def _open_editor(self) -> None:
        from .editor_dialog import EditorDialog
        dlg = EditorDialog(self._zug_manager, self)
        dlg.exec()
        # After saving, re-check all trains against updated config
        for record in self._zug_manager.get_all_records():
            self._zug_manager.update_details(
                record.details.zid, record.details)
        self._refresh_views()
