from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from ..logic.train_manager import ZugManager
from .widgets.departure_board import DepartureBoardWidget

_MIN_BOARD_WIDTH = 260


class PassengerView(QWidget):
    """
    Fahrgast-Ansicht — grafische ZZA-Optik.

    Zeigt für jede ausgewählte Plattform ein DepartureBoardWidget in einem
    responsiven Raster. Die Spaltenanzahl passt sich automatisch an die
    Fensterbreite an; gescrollt wird nur vertikal.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._boards: Dict[str, DepartureBoardWidget] = {}
        self._platforms: List[str] = []
        self._current_cols: int = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #001199;")

        from PyQt6.QtWidgets import QVBoxLayout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("border: none; background-color: #001199;")

        self._container = QWidget()
        self._container.setStyleSheet("background-color: #001199;")
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(4)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_platforms(self, platforms: List[str]) -> None:
        """Rebuild boards for the given platform list."""
        for board in self._boards.values():
            board.deleteLater()
        self._boards.clear()
        self._platforms = list(platforms)
        self._current_cols = 0   # force rebuild
        self._rebuild_grid()

    def refresh(self, zug_manager: ZugManager) -> None:
        for platform, board in self._boards.items():
            entries = zug_manager.get_display_data_for_platform(platform)
            board.refresh(entries)

    # ------------------------------------------------------------------
    # Resize handling
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._platforms:
            n = self._desired_cols()
            if n != self._current_cols:
                self._rebuild_grid()

    def _desired_cols(self) -> int:
        avail = self._scroll.viewport().width() if self._scroll.viewport() else self.width()
        return max(1, min(avail // _MIN_BOARD_WIDTH, len(self._platforms)))

    def _rebuild_grid(self) -> None:
        n_cols = self._desired_cols()
        self._current_cols = n_cols

        # Remove all items from grid (keep widgets alive via _boards)
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)  # type: ignore[arg-type]

        # Clear stretch factors
        for c in range(self._grid.columnCount() + n_cols + 1):
            self._grid.setColumnStretch(c, 0)
        for r in range(self._grid.rowCount() + 10):
            self._grid.setRowStretch(r, 0)

        # (Re)create boards and populate grid
        for i, platform in enumerate(self._platforms):
            if platform not in self._boards:
                board = DepartureBoardWidget(platform)
                board.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self._boards[platform] = board
            row, col = divmod(i, n_cols)
            self._grid.addWidget(self._boards[platform], row, col)

        # Equal column widths
        for c in range(n_cols):
            self._grid.setColumnStretch(c, 1)

        # Equal row heights
        n_rows = max(1, (len(self._platforms) + n_cols - 1) // n_cols)
        for r in range(n_rows):
            self._grid.setRowStretch(r, 1)
