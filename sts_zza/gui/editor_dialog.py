from __future__ import annotations

import logging
from typing import Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..config.station_config import ZugEintrag
from ..logic.train_manager import ZugManager
from ..protocol.models import ZugDetails

logger = logging.getLogger(__name__)

_COLS = ["Zugname", "Gleis (plan)", "Von", "Nach", "Via (kommagetrennt)"]

_COL_NAME   = 0
_COL_GLEIS  = 1
_COL_VON    = 2
_COL_NACH   = 3
_COL_VIA    = 4


class EditorDialog(QDialog):
    """
    Analyse & Editor — zeigt Züge aus der Capture-Liste.

    Der Nutzer kann Von/Nach/Via/Plangleis ergänzen und per Knopfdruck
    dauerhaft in die XML-Konfiguration übernehmen.
    """

    def __init__(self, zug_manager: ZugManager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Analyse & Editor — Neue Züge")
        self.setMinimumSize(750, 420)
        self._zug_manager = zug_manager
        self._changes_made = False
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "Die folgenden Züge wurden im Spiel erkannt, "
            "sind aber noch nicht in der Konfiguration.\n"
            "Fehlende Angaben ergänzen und auf „Speichern" klicken."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_NACH, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._table)

        save_btn = QPushButton("Auswahl dauerhaft in Konfiguration speichern")
        save_btn.clicked.connect(self._save_selected)
        layout.addWidget(save_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self) -> None:
        capture: Dict[str, ZugDetails] = self._zug_manager.get_capture_list()
        self._table.setRowCount(len(capture))

        for row, (name, details) in enumerate(sorted(capture.items())):
            # Zugname (read-only)
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, _COL_NAME, name_item)

            self._table.setItem(row, _COL_GLEIS, QTableWidgetItem(details.plangleis or ""))
            self._table.setItem(row, _COL_VON,   QTableWidgetItem(details.von))
            self._table.setItem(row, _COL_NACH,  QTableWidgetItem(details.nach))
            self._table.setItem(row, _COL_VIA,   QTableWidgetItem(""))

    def _save_selected(self) -> None:
        saved = 0
        for row in range(self._table.rowCount()):
            name      = self._table.item(row, _COL_NAME).text()
            plangleis = self._table.item(row, _COL_GLEIS).text().strip()
            von       = self._table.item(row, _COL_VON).text().strip()
            nach      = self._table.item(row, _COL_NACH).text().strip()
            via_raw   = self._table.item(row, _COL_VIA).text()
            via       = [v.strip() for v in via_raw.split(",") if v.strip()]

            entry = ZugEintrag(
                name=name, von=von, nach=nach, via=via, plangleis=plangleis)
            self._zug_manager._config.zuege[name] = entry
            saved += 1

        self._zug_manager._config.save()
        self._changes_made = True
        logger.info("Saved %d train entries from capture list", saved)
        self._populate()

    def has_changes(self) -> bool:
        return self._changes_made
