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

_MIN_BOARD_WIDTH = 800   # entspricht DepartureBoardWidget._BOARD_W
_BOARD_GAP = 8


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
        self._platforms: List[str] = []          # ursprüngliche Reihenfolge
        self._display_order: List[str] = []      # aktuell angezeigte Reihenfolge
        self._current_cols: int = 0
        self._sort_by_next_departure: bool = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #000000;")

        from PyQt6.QtWidgets import QVBoxLayout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("border: none; background-color: #000000;")

        self._container = QWidget()
        self._container.setStyleSheet("background-color: #000000;")
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(8)

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
        self._display_order = list(platforms)
        self._current_cols = 0   # force rebuild
        self._rebuild_grid()

    def set_sort_by_next_departure(self, enabled: bool) -> None:
        """Schaltet die dynamische Sortierung nach nächster Abfahrt um."""
        if enabled == self._sort_by_next_departure:
            return
        self._sort_by_next_departure = enabled
        if not enabled:
            self._display_order = list(self._platforms)
            self._rebuild_grid()

    def refresh(self, zug_manager: ZugManager) -> None:
        # Pro Plattform die Einträge holen und gleichzeitig die nächste
        # *Abfahrtszeit* ermitteln (nur ab, kein an-Fallback — terminierende
        # Züge dürfen ihren Bahnsteig nicht nach vorne ziehen).
        next_dep: Dict[str, int] = {}
        sim_now = zug_manager.sim_now_ms()
        for platform, board in self._boards.items():
            entries = zug_manager.get_display_data_for_platform(platform)
            board.refresh(entries, sim_now_ms=sim_now)
            soonest = None
            for e in entries:
                if e.ab is None:
                    continue
                if soonest is None or e.ab < soonest:
                    soonest = e.ab
            # Plattformen ohne aktive Abfahrt landen am Ende.
            next_dep[platform] = soonest if soonest is not None else 10**12

        if self._sort_by_next_departure:
            # Sekundär-Sortierung numerisch (Gleis "5" vor "10"),
            # mit Fallback auf String, falls kein Zahlname.
            def _name_key(p: str):
                try:
                    return (0, int(p))
                except ValueError:
                    return (1, p)

            new_order = sorted(
                self._platforms,
                key=lambda p: (next_dep.get(p, 10**12), _name_key(p)),
            )
            if new_order != self._display_order:
                self._display_order = new_order
                self._rebuild_grid()

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
        avail = (self._scroll.viewport().width()
                 if self._scroll.viewport() else self.width())
        # Verfügbare Breite ÷ (Boardbreite + Spalt) — min. 1 Spalte
        per_col = _MIN_BOARD_WIDTH + _BOARD_GAP
        return max(1, min(avail // per_col, len(self._platforms)))

    def _rebuild_grid(self) -> None:
        n_cols = self._desired_cols()
        self._current_cols = n_cols

        # Remove all items from grid (keep widgets alive via _boards)
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)  # type: ignore[arg-type]

        # Alle Spalten-/Zeilen-Stretches zurücksetzen
        for c in range(self._grid.columnCount() + n_cols + 1):
            self._grid.setColumnStretch(c, 0)
        for r in range(self._grid.rowCount() + 1):
            self._grid.setRowStretch(r, 0)

        # Boards anlegen / wiederverwenden — feste Größe, keine Streckung
        order = self._display_order or self._platforms
        for i, platform in enumerate(order):
            if platform not in self._boards:
                board = DepartureBoardWidget(platform)
                self._boards[platform] = board
            row, col = divmod(i, n_cols)
            self._grid.addWidget(
                self._boards[platform], row, col,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Letzte (leere) Spalte/Zeile dehnt sich, damit Kacheln links-oben
        # bleiben statt zentriert zu schweben.
        self._grid.setColumnStretch(n_cols, 1)
        n_rows = (len(order) + n_cols - 1) // n_cols
        self._grid.setRowStretch(n_rows, 1)
