from __future__ import annotations

import logging
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
    QVBoxLayout,
)

from ..config.station_config import StationConfig
from ..protocol.client import STSClient
from ..protocol.models import BahnsteigInfo

logger = logging.getLogger(__name__)

_PLACEHOLDER_LABEL = "Verbinde mit StellwerkSim …"


class _PlaceholderView(QWidget):
    """Shown while no platforms have been selected yet."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class ZZAMainWindow(QMainWindow):
    """
    Top-level application window.

    Hosts a QStackedWidget with:
      index 0 — placeholder while connecting / awaiting platform selection
      index 1 — (Phase 3) passenger ZZA view
      index 2 — (Phase 3) dispatcher table view

    Reacts to STSClient signals and orchestrates platform selection.
    """

    def __init__(self, client: STSClient, config: StationConfig, parent=None) -> None:
        super().__init__(parent)
        self._client = client
        self._config = config
        self._selected_platforms: List[str] = []
        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_config(self, config: StationConfig) -> None:
        self._config = config
        self.setWindowTitle(f"STS ZZA — {config.station_name}")

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("STS ZZA — Zugzielanzeiger")
        self.setMinimumSize(900, 500)

        menu_bar = self.menuBar()

        view_menu = menu_bar.addMenu("Ansicht")
        self._action_fahrgast = view_menu.addAction("Fahrgast-Ansicht")
        self._action_fdl = view_menu.addAction("Fdl-Ansicht")
        self._action_fahrgast.setEnabled(False)
        self._action_fdl.setEnabled(False)

        tools_menu = menu_bar.addMenu("Werkzeuge")
        self._action_editor = tools_menu.addAction("Analyse && Editor")
        self._action_editor.setEnabled(False)

        self._stack = QStackedWidget()
        self._placeholder = _PlaceholderView(_PLACEHOLDER_LABEL)
        self._stack.addWidget(self._placeholder)
        self.setCentralWidget(self._stack)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Verbinde …")

    def _connect_signals(self) -> None:
        self._client.connected.connect(self._on_connected)
        self._client.sig_anlageninfo.connect(self._on_anlageninfo)
        self._client.sig_bahnsteigliste.connect(self._on_bahnsteigliste)

        self._action_fahrgast.triggered.connect(lambda: self._stack.setCurrentIndex(1))
        self._action_fdl.triggered.connect(lambda: self._stack.setCurrentIndex(2))

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
        dlg = PlatformSelectorDialog(bahnsteige, self)
        if dlg.exec():
            self._selected_platforms = dlg.selected_platforms()
            self._config.bahnsteige = self._selected_platforms
            self._config.save()
            self.statusBar().showMessage(
                f"{len(self._selected_platforms)} Bahnsteig(e) ausgewählt"
            )
            self._action_fahrgast.setEnabled(True)
            self._action_fdl.setEnabled(True)
            self._action_editor.setEnabled(True)
            logger.info("Selected platforms: %s", self._selected_platforms)
        else:
            self.statusBar().showMessage("Keine Bahnsteige ausgewählt.")
