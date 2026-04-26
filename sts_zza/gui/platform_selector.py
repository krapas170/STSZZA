from __future__ import annotations

from typing import List, Set

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

    Pre-selection priority:
    1. Saved config (config_bahnsteige) if not empty → restore last selection
    2. Otherwise nothing pre-selected → user decides from scratch

    Note: STS sends haltepunkt=true for *neighbouring* stops outside the
    station (e.g. "A - Biessenhofen"), NOT for the numbered station tracks.
    We therefore ignore the haltepunkt flag for pre-selection.
    """

    def __init__(self,
                 bahnsteige: List[BahnsteigInfo],
                 config_bahnsteige: List[str] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bahnsteig-Auswahl")
        self.setMinimumSize(360, 480)
        self._setup_ui(bahnsteige, set(config_bahnsteige or []))

    def _setup_ui(self, bahnsteige: List[BahnsteigInfo],
                  saved: Set[str]) -> None:
        layout = QVBoxLayout(self)

        if saved:
            hint = "Vorausgewählt: zuletzt gespeicherte Auswahl."
        else:
            hint = "Erstauswahl — bitte die anzuzeigenden Gleise wählen."

        layout.addWidget(QLabel(
            "Bitte die anzuzeigenden Bahnsteige auswählen.\n" + hint
        ))

        self._list = QListWidget()
        for b in sorted(bahnsteige, key=lambda x: x.name):
            item = QListWidgetItem(b.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = (Qt.CheckState.Checked
                     if b.name in saved
                     else Qt.CheckState.Unchecked)
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
