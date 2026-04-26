from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...logic.train_manager import DisplayEntry
from ...utils.time_utils import delay_str, ms_to_hhmm

# ── Colour palette ──────────────────────────────────────────────────────────
_BG_BOARD   = "#0d1b2a"   # deep navy — board background
_BG_HEADER  = "#1b2838"   # slightly lighter for header
_BG_ROW     = "#112233"   # normal row
_BG_ROW_ALT = "#0e1c2c"   # alternating row
_BG_NEW     = "#1a2a10"   # greenish tint for captured (unknown) trains
_FG_WHITE   = "#f0f4f8"
_FG_TIME    = "#ffd166"   # amber — departure time
_FG_DELAY   = "#ef233c"   # red — delay
_FG_GLEIS   = "#06d6a0"   # teal — track number
_FG_DIM     = "#8899aa"   # muted — "no data"


def _label(text: str, color: str, bold: bool = False,
           align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
           font_size: int = 11) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(align)
    style = f"color: {color}; font-size: {font_size}pt;"
    if bold:
        style += " font-weight: bold;"
    lbl.setStyleSheet(style)
    lbl.setContentsMargins(6, 2, 6, 2)
    return lbl


class _TrainRow(QFrame):
    def __init__(self, entry: DisplayEntry, bg: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {bg}; border: none;")
        self.setFixedHeight(32)

        ab_text  = ms_to_hhmm(entry.ab)
        del_text = delay_str(entry.verspaetung)
        nach_text = entry.nach or "–"
        gleis_text = entry.plangleis

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        # Abfahrtszeit
        time_lbl = _label(ab_text, _FG_TIME, bold=True, font_size=12)
        time_lbl.setFixedWidth(52)
        layout.addWidget(time_lbl)

        # Zugname
        name_lbl = _label(entry.name, _FG_WHITE, bold=True, font_size=11)
        name_lbl.setFixedWidth(90)
        layout.addWidget(name_lbl)

        # Ziel
        nach_lbl = _label(nach_text, _FG_WHITE, font_size=11)
        nach_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(nach_lbl)

        # Verspätung
        if del_text:
            delay_lbl = _label(del_text, _FG_DELAY, bold=True, font_size=10)
            delay_lbl.setFixedWidth(60)
            layout.addWidget(delay_lbl)

        # Gleisnummer
        gleis_lbl = _label(
            gleis_text, _FG_GLEIS, bold=True,
            align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            font_size=12,
        )
        gleis_lbl.setFixedWidth(36)
        layout.addWidget(gleis_lbl)

        if entry.is_new:
            self.setToolTip("Zug nicht in Konfiguration – in Capture-Liste")


class DepartureBoardWidget(QWidget):
    """
    Visual ZZA board for a single platform.

    Shows a dark-themed header with the platform name, followed by
    a scrollable list of upcoming departures.
    """

    def __init__(self, platform: str, parent=None) -> None:
        super().__init__(parent)
        self._platform = platform
        self.setMinimumWidth(320)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background-color: {_BG_BOARD};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──
        header = QWidget()
        header.setStyleSheet(f"background-color: {_BG_HEADER};")
        header.setFixedHeight(40)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)

        icon_lbl = _label("🚉", _FG_WHITE, font_size=14)
        icon_lbl.setFixedWidth(28)
        h_layout.addWidget(icon_lbl)

        title = _label(f"Gleis {self._platform}", _FG_WHITE,
                       bold=True, font_size=13)
        h_layout.addWidget(title)
        h_layout.addStretch()

        col_time  = _label("Ab", _FG_DIM, font_size=9)
        col_time.setFixedWidth(52)
        col_train = _label("Zug", _FG_DIM, font_size=9)
        col_train.setFixedWidth(90)
        col_dest  = _label("Ziel", _FG_DIM, font_size=9)
        h_layout.addWidget(col_time)
        h_layout.addWidget(col_train)
        h_layout.addWidget(col_dest)

        outer.addWidget(header)

        # ── Scroll area for train rows ──
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setStyleSheet(
            f"background-color: {_BG_BOARD}; border: none;")
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_widget = QWidget()
        self._rows_widget.setStyleSheet(f"background-color: {_BG_BOARD};")
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(1)
        self._rows_layout.addStretch()

        self._scroll_area.setWidget(self._rows_widget)
        outer.addWidget(self._scroll_area)

        # ── "keine Züge" placeholder ──
        self._empty_label = _label(
            "Keine Züge", _FG_DIM,
            align=Qt.AlignmentFlag.AlignCenter, font_size=10,
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._empty_label)

    def refresh(self, entries: List[DisplayEntry]) -> None:
        """Replace all rows with current entries."""
        # Remove old rows (keep the stretch at the end)
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not entries:
            self._empty_label.show()
            self._scroll_area.hide()
            return

        self._empty_label.hide()
        self._scroll_area.show()

        for i, entry in enumerate(entries):
            bg = _BG_ROW if i % 2 == 0 else _BG_ROW_ALT
            if entry.is_new:
                bg = _BG_NEW
            row = _TrainRow(entry, bg)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
