from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from ..logic.train_manager import ZugManager
from .widgets.departure_board import DepartureBoardWidget


class PassengerView(QWidget):
    """
    Fahrgast-Ansicht — grafische ZZA-Optik.

    Zeigt für jedes ausgewählte Gleis ein eigenes DepartureBoardWidget
    nebeneinander in einer horizontalen, scrollbaren Leiste.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._boards: Dict[str, DepartureBoardWidget] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #001199;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("border: none; background-color: #001199;")

        self._container = QWidget()
        self._container.setStyleSheet("background-color: #001199;")
        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)
        self._layout.addStretch()

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

    def set_platforms(self, platforms: List[str]) -> None:
        """Rebuild boards for the given platform list."""
        # Clear existing boards
        for board in self._boards.values():
            board.deleteLater()
        self._boards.clear()

        # Remove stretch, add boards, re-add stretch
        while self._layout.count():
            self._layout.takeAt(0)

        for platform in platforms:
            board = DepartureBoardWidget(platform)
            board.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            self._boards[platform] = board
            self._layout.addWidget(board)

        self._layout.addStretch()

    def refresh(self, zug_manager: ZugManager) -> None:
        for platform, board in self._boards.items():
            entries = zug_manager.get_display_data_for_platform(platform)
            board.refresh(entries)
