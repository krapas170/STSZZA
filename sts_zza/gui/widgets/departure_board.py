from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt, QTimer
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

# ── Klassische ZuDis-Farbpalette ─────────────────────────────────────────────
_BG_BLUE      = "#0033cc"   # Kobaltblau — Haupthintergrund
_BG_DARK      = "#002299"   # etwas dunkler für Header / Trennzeile
_BG_NEXT      = "#002aaa"   # Folge-Züge-Bereich
_FG_WHITE     = "#ffffff"
_FG_DIM       = "#8899dd"   # gedämpft für Nebeninfos
_FG_DELAY     = "#ffdd00"   # Gelb für Verspätung (gut sichtbar auf Blau)
_SEP          = "#001888"   # Trennlinie


def _lbl(text: str,
         color: str = _FG_WHITE,
         size: int = 11,
         bold: bool = False,
         align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
         wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(align)
    s = f"color:{color}; font-size:{size}pt; background:transparent;"
    if bold:
        s += " font-weight:bold;"
    lbl.setStyleSheet(s)
    lbl.setWordWrap(wrap)
    lbl.setContentsMargins(0, 0, 0, 0)
    return lbl


class _HSep(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color:{_SEP}; border:none;")


class _MainTrainWidget(QWidget):
    """Nächster Zug — große Zieldarstellung im ZuDis-Stil."""

    def __init__(self, entry: DisplayEntry, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color:{_BG_BLUE};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        # ── Zeile 1: Abfahrtszeit + Zugname ──────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        time_lbl = _lbl(ms_to_hhmm(entry.ab), size=18, bold=True)
        time_lbl.setFixedWidth(72)
        row1.addWidget(time_lbl)

        name_lbl = _lbl(entry.name, size=14, bold=True)
        row1.addWidget(name_lbl, stretch=1)

        if entry.verspaetung > 0:
            d_lbl = _lbl(delay_str(entry.verspaetung), _FG_DELAY,
                         size=11, bold=True)
            row1.addWidget(d_lbl)

        layout.addLayout(row1)

        # ── Zeile 2: Ziel (groß) ──────────────────────────────────────────────
        nach = entry.nach or "–"
        nach_lbl = _lbl(nach, size=20, bold=True, wrap=True)
        layout.addWidget(nach_lbl)

        # ── Zeile 3: Von ──────────────────────────────────────────────────────
        if entry.von:
            von_lbl = _lbl(f"von {entry.von}", _FG_DIM, size=9)
            layout.addWidget(von_lbl)


class _NextTrainRow(QWidget):
    """Kompakte Zeile für einen der folgenden Züge."""

    def __init__(self, entry: DisplayEntry, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color:{_BG_NEXT};")
        self.setFixedHeight(24)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        t = _lbl(ms_to_hhmm(entry.ab), _FG_DIM, size=9, bold=True)
        t.setFixedWidth(40)
        layout.addWidget(t)

        n = _lbl(entry.name, _FG_DIM, size=9)
        n.setFixedWidth(72)
        layout.addWidget(n)

        z = _lbl(entry.nach or "–", _FG_DIM, size=9)
        layout.addWidget(z, stretch=1)

        if entry.verspaetung > 0:
            layout.addWidget(_lbl(delay_str(entry.verspaetung), _FG_DELAY, size=8))


class _TickerWidget(QWidget):
    """Scrollender Infoband am unteren Rand — wie beim echten ZuDis."""

    _STEP_MS  = 30    # Pixel-Schritt-Intervall
    _STEP_PX  = 1     # Pixel pro Schritt
    _PAUSE_MS = 3000  # Pause am Anfang

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setStyleSheet(f"background-color:{_BG_DARK};")

        self._container = QWidget(self)
        self._container.setStyleSheet("background:transparent;")
        row = QHBoxLayout(self._container)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(40)

        self._lbl = QLabel()
        self._lbl.setStyleSheet(
            f"color:{_FG_DIM}; font-size:9pt; background:transparent;")
        row.addWidget(self._lbl)

        self._offset = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scroll)

    def set_text(self, text: str) -> None:
        self._lbl.setText(text)
        self._container.adjustSize()
        self._offset = 0
        self._container.move(0, 1)
        self._timer.stop()
        QTimer.singleShot(self._PAUSE_MS, self._timer.start)
        self._timer.setInterval(self._STEP_MS)

    def _scroll(self) -> None:
        self._offset += self._STEP_PX
        w = self._container.width()
        if self._offset > w + self.width():
            self._offset = -self.width()
        self._container.move(-self._offset, 1)


class DepartureBoardWidget(QWidget):
    """
    Klassische ZuDis-Zugzielanzeige für ein einzelnes Gleis.

    Kobaltblauer Hintergrund, weißer Text, große Zieldarstellung.
    Folge-Züge werden kompakt darunter aufgelistet.
    Am unteren Rand scrollt ein Infoband.
    """

    _MAX_NEXT = 3

    def __init__(self, platform: str, parent=None) -> None:
        super().__init__(parent)
        self._platform = platform
        self.setMinimumWidth(240)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color:{_BG_BLUE};")
        self._setup_ui()

    def _setup_ui(self) -> None:
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # ── Kopfzeile: Gleis ──────────────────────────────────────────────────
        header = QWidget()
        header.setStyleSheet(f"background-color:{_BG_DARK};")
        header.setFixedHeight(30)
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(10, 0, 10, 0)
        h_row.addWidget(_lbl("Gleis", _FG_DIM, size=9))
        h_row.addWidget(_lbl(f" {self._platform}", size=12, bold=True))
        h_row.addStretch()
        self._outer.addWidget(header)
        self._outer.addWidget(_HSep())

        # ── Hauptbereich (nächster Zug) ───────────────────────────────────────
        self._main_area = QWidget()
        self._main_area.setStyleSheet(f"background-color:{_BG_BLUE};")
        self._main_layout = QVBoxLayout(self._main_area)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        self._outer.addWidget(self._main_area)

        # ── "Kein Zug" placeholder ───────────────────────────────────────────
        self._empty_lbl = _lbl(
            "Kein Zug angekündigt", _FG_DIM, size=9,
            align=Qt.AlignmentFlag.AlignCenter,
        )
        self._empty_lbl.setContentsMargins(0, 16, 0, 16)
        self._outer.addWidget(self._empty_lbl)
        self._outer.addStretch()

        # ── Ticker ────────────────────────────────────────────────────────────
        self._outer.addWidget(_HSep())
        self._ticker = _TickerWidget()
        self._outer.addWidget(self._ticker)

    def refresh(self, entries: List[DisplayEntry]) -> None:
        while self._main_layout.count():
            item = self._main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not entries:
            self._main_area.hide()
            self._empty_lbl.show()
            self._ticker.set_text(
                f"Gleis {self._platform}  –  Kein Zug angekündigt")
            return

        self._empty_lbl.hide()
        self._main_area.show()

        # Nächster Zug
        self._main_layout.addWidget(_MainTrainWidget(entries[0]))

        # Folgende Züge
        following = entries[1:1 + self._MAX_NEXT]
        if following:
            self._main_layout.addWidget(_HSep())
            for e in following:
                self._main_layout.addWidget(_NextTrainRow(e))

        self._main_layout.addStretch()

        # Ticker-Text aus Einträgen zusammenstellen
        parts = []
        for e in entries:
            parts.append(
                f"{ms_to_hhmm(e.ab)}  {e.name}  {e.nach or '–'}"
                + (f"  {delay_str(e.verspaetung)}" if e.verspaetung > 0 else "")
            )
        self._ticker.set_text("     ·     ".join(parts))
