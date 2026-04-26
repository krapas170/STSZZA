from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..logic.train_manager import ZugManager
from ..utils.time_utils import delay_str, ms_to_hhmm

_COLS = ["Gleis", "Abfahrt", "Ankunft", "Zug", "Von", "Nach", "Verspätung", "Status"]

_COL_GLEIS   = 0
_COL_AB      = 1
_COL_AN      = 2
_COL_NAME    = 3
_COL_VON     = 4
_COL_NACH    = 5
_COL_DELAY   = 6
_COL_STATUS  = 7

_COLOR_DELAY  = QColor("#ef233c")
_COLOR_NEW    = QColor("#2d4a1e")
_COLOR_NORMAL = QColor("#1e2d3d")


class DispatcherView(QWidget):
    """
    Fdl-Ansicht — strukturierte Tabellenansicht aller Züge im Simulator,
    sortiert nach Abfahrtszeit.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_NACH, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_VON,  QHeaderView.ResizeMode.Stretch)

        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #0d1b2a;
                color: #f0f4f8;
                gridline-color: #1e3050;
                font-size: 11pt;
            }
            QTableWidget::item:selected {
                background-color: #2a5080;
            }
            QHeaderView::section {
                background-color: #1b2838;
                color: #aabbcc;
                font-size: 10pt;
                padding: 4px;
                border: none;
                border-bottom: 1px solid #2a4060;
            }
        """)

        layout.addWidget(self._table)

    def refresh(self, zug_manager: ZugManager) -> None:
        entries = zug_manager.get_all_trains_display()

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(entries))

        for row, e in enumerate(entries):
            bg = _COLOR_NEW if e.is_new else _COLOR_NORMAL

            def cell(text: str, align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setBackground(bg)
                item.setTextAlignment(int(align))
                return item

            center = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter

            self._table.setItem(row, _COL_GLEIS,  cell(e.plangleis, center))
            self._table.setItem(row, _COL_AB,     cell(ms_to_hhmm(e.ab), center))
            self._table.setItem(row, _COL_AN,     cell(ms_to_hhmm(e.an), center))
            self._table.setItem(row, _COL_NAME,   cell(e.name))
            self._table.setItem(row, _COL_VON,    cell(e.von))
            self._table.setItem(row, _COL_NACH,   cell(e.nach))

            delay_item = cell(delay_str(e.verspaetung), center)
            if e.verspaetung > 0:
                delay_item.setForeground(_COLOR_DELAY)
            self._table.setItem(row, _COL_DELAY, delay_item)

            status = "Neu (unbekannt)" if e.is_new else ""
            self._table.setItem(row, _COL_STATUS, cell(status))

        self._table.setSortingEnabled(True)
