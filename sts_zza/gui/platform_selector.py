from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..protocol.models import BahnsteigInfo


class PlatformSelectorDialog(QDialog):
    """
    Startup dialog that lets the user choose which platforms (Bahnsteige)
    should appear on the ZZA boards.

    Platforms with haltepunkt=True are pre-checked.
    """

    def __init__(self, bahnsteige: List[BahnsteigInfo], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bahnsteig-Auswahl")
        self.setMinimumSize(360, 480)
        self._setup_ui(bahnsteige)

    def _setup_ui(self, bahnsteige: List[BahnsteigInfo]) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Bitte die anzuzeigenden Bahnsteige auswählen.\n"
            "Vorausgewählt sind alle Haltepunkte."
        ))

        self._list = QListWidget()
        for b in sorted(bahnsteige, key=lambda x: x.name):
            item = QListWidgetItem(b.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = Qt.CheckState.Checked if b.haltepunkt else Qt.CheckState.Unchecked
            item.setCheckState(state)
            self._list.addItem(item)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_all = QPushButton("Alle")
        btn_none = QPushButton("Keine")
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._select_none)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_all(self) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Checked)

    def _select_none(self) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def selected_platforms(self) -> List[str]:
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result
