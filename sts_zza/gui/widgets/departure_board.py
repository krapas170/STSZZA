from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...logic.train_manager import DisplayEntry
from ...utils.time_utils import delay_str, ms_to_hhmm

# ── Klassische ZZA-Farbpalette (amber auf dunkelblau) ────────────────────────
_BG_BOARD    = "#0a0e1a"
_BG_HEADER   = "#0d1520"
_BG_MAIN     = "#0d1520"
_BG_NEXT     = "#080c14"
_BG_DIVIDER  = "#1a2a40"

_FG_AMBER    = "#ffb300"   # Hauptfarbe: amber/orange
_FG_AMBER_DIM = "#996800"  # gedämpft für Nebeninfos
_FG_WHITE    = "#e8eaf0"
_FG_GLEIS    = "#00c8ff"   # helles Cyan für Gleisanzeige
_FG_DELAY    = "#ff4444"   # Rot für Verspätung
_FG_DIM      = "#3a4a5a"
_FG_NEW      = "#44ff88"   # Grün für unbekannte Züge


def _lbl(text: str, color: str, size: int = 11, bold: bool = False,
         align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
         wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(align)
    style = f"color:{color}; font-size:{size}pt; background:transparent;"
    if bold:
        style += " font-weight:bold;"
    lbl.setStyleSheet(style)
    lbl.setWordWrap(wrap)
    lbl.setContentsMargins(0, 0, 0, 0)
    return lbl


class _Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color:{_BG_DIVIDER}; border:none;")


class _MainTrainWidget(QWidget):
    """Zeigt den nächsten Zug groß an — klassische ZZA-Hauptanzeige."""

    def __init__(self, entry: DisplayEntry, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color:{_BG_MAIN};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # ── Zeile 1: Abfahrtszeit + Zugname ──────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        ab = ms_to_hhmm(entry.ab)
        time_lbl = _lbl(ab, _FG_AMBER, size=22, bold=True)
        time_lbl.setFixedWidth(80)
        row1.addWidget(time_lbl)

        name_color = _FG_NEW if entry.is_new else _FG_WHITE
        name_lbl = _lbl(entry.name, name_color, size=15, bold=True)
        row1.addWidget(name_lbl, stretch=1)

        # Verspätung
        if entry.verspaetung > 0:
            delay_lbl = _lbl(delay_str(entry.verspaetung), _FG_DELAY,
                             size=11, bold=True)
            row1.addWidget(delay_lbl)

        layout.addLayout(row1)

        # ── Zeile 2: Ziel ─────────────────────────────────────────────────────
        nach = entry.nach or "–"
        nach_lbl = _lbl(f"▶  {nach}", _FG_AMBER, size=14, bold=True)
        layout.addWidget(nach_lbl)

        # ── Zeile 3: Von (Herkunft) ───────────────────────────────────────────
        if entry.von:
            von_lbl = _lbl(f"   von {entry.von}", _FG_AMBER_DIM, size=10)
            layout.addWidget(von_lbl)


class _NextTrainRow(QWidget):
    """Kompakte Zeile für einen der folgenden Züge."""

    def __init__(self, entry: DisplayEntry, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color:{_BG_NEXT};")
        self.setFixedHeight(26)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        time_lbl = _lbl(ms_to_hhmm(entry.ab), _FG_AMBER_DIM, size=10, bold=True)
        time_lbl.setFixedWidth(44)
        layout.addWidget(time_lbl)

        name_lbl = _lbl(entry.name, _FG_DIM, size=10)
        name_lbl.setFixedWidth(80)
        layout.addWidget(name_lbl)

        nach_lbl = _lbl(entry.nach or "–", _FG_DIM, size=10)
        layout.addWidget(nach_lbl, stretch=1)

        if entry.verspaetung > 0:
            d = _lbl(delay_str(entry.verspaetung), _FG_DELAY, size=9)
            layout.addWidget(d)


class DepartureBoardWidget(QWidget):
    """
    Klassische Zugzielanzeige für ein einzelnes Gleis.

    Layout:
    ┌─────────────────────────────┐
    │  GLEIS X                    │  ← Kopfzeile
    ├─────────────────────────────┤
    │  08:42  IC 2012             │
    │  ▶  München Hbf             │  ← Nächster Zug (groß)
    │     von Oberstdorf          │
    ├─────────────────────────────┤
    │  09:15  RE 57  Ulm Hbf      │  ← Folgende Züge (klein)
    │  10:03  ALX    Oberstdorf   │
    └─────────────────────────────┘
    """

    _MAX_NEXT = 4  # max. Folge-Züge anzeigen

    def __init__(self, platform: str, parent=None) -> None:
        super().__init__(parent)
        self._platform = platform
        self.setMinimumWidth(260)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color:{_BG_BOARD};")
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # ── Kopfzeile ─────────────────────────────────────────────────────────
        header = QWidget()
        header.setStyleSheet(f"background-color:{_BG_HEADER};")
        header.setFixedHeight(36)
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(12, 0, 12, 0)
        h_row.addWidget(_lbl("GLEIS", _FG_DIM, size=9))
        h_row.addWidget(_lbl(f" {self._platform}", _FG_GLEIS, size=14, bold=True))
        h_row.addStretch()
        self._outer.addWidget(header)
        self._outer.addWidget(_Divider())

        # ── Hauptbereich (nächster Zug) ───────────────────────────────────────
        self._main_area = QWidget()
        self._main_area.setStyleSheet(f"background-color:{_BG_MAIN};")
        self._main_layout = QVBoxLayout(self._main_area)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        self._outer.addWidget(self._main_area)

        # ── "Keine Züge"-Label ────────────────────────────────────────────────
        self._empty_lbl = _lbl(
            "Kein Zug angekündigt", _FG_DIM, size=10,
            align=Qt.AlignmentFlag.AlignCenter,
        )
        self._empty_lbl.setContentsMargins(0, 20, 0, 20)
        self._outer.addWidget(self._empty_lbl)

        self._outer.addStretch()

    def refresh(self, entries: List[DisplayEntry]) -> None:
        # Alten Inhalt entfernen
        while self._main_layout.count():
            item = self._main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not entries:
            self._main_area.hide()
            self._empty_lbl.show()
            return

        self._empty_lbl.hide()
        self._main_area.show()

        # Nächster Zug — groß
        main_widget = _MainTrainWidget(entries[0])
        self._main_layout.addWidget(main_widget)

        # Folgende Züge — kompakt
        following = entries[1:1 + self._MAX_NEXT]
        if following:
            self._main_layout.addWidget(_Divider())
            for entry in following:
                self._main_layout.addWidget(_NextTrainRow(entry))

        self._main_layout.addStretch()
