from __future__ import annotations

import logging
from typing import Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..config.station_config import ZugEintrag
from ..logic.train_manager import ZugManager, _is_dienstfahrt
from ..protocol.models import ZugDetails

# Stellwerk-interne Bereichs-/Gleisnamen, die als von/nach unbrauchbar sind.
_INTERNAL_AREA_HINTS = (
    "stammstrecke", "pasing aulido", "pasing fernbahn",
    "kanal landshut", "laim rbf", "münchen süd", "muenchen sued",
    "vn",
)

logger = logging.getLogger(__name__)

_COLS = ["Zugname", "Von", "Nach", "Via (kommagetrennt)"]

_COL_NAME   = 0
_COL_VON    = 1
_COL_NACH   = 2
_COL_VIA    = 3


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
            'Fehlende Angaben ergänzen und auf "Speichern" klicken.'
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
        hdr.setSectionResizeMode(_COL_VIA,  QHeaderView.ResizeMode.Stretch)

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

            self._table.setItem(row, _COL_VON,  QTableWidgetItem(details.von))
            self._table.setItem(row, _COL_NACH, QTableWidgetItem(details.nach))
            via_text = ", ".join(getattr(details, "via", []) or [])
            self._table.setItem(row, _COL_VIA,  QTableWidgetItem(via_text))

    @staticmethod
    def _validate_row(name: str, von: str, nach: str) -> str | None:
        """Returns reason string if invalid, sonst None."""
        if _is_dienstfahrt(name):
            return "Dienst-/Leerfahrt"
        if not von or not nach:
            return "Von oder Nach leer"
        low_n = nach.lower()
        low_v = von.lower()
        if low_n.startswith("gleis ") or low_v.startswith("gleis "):
            return "Gleis-Bezeichnung statt Bahnhof"
        for hint in _INTERNAL_AREA_HINTS:
            if hint in low_n or hint in low_v:
                return f"Stellwerks-interner Bereich ({hint})"
        return None

    def _save_selected(self) -> None:
        saved = 0
        skipped: list[tuple[str, str]] = []
        for row in range(self._table.rowCount()):
            name    = self._table.item(row, _COL_NAME).text()
            von     = self._table.item(row, _COL_VON).text().strip()
            nach    = self._table.item(row, _COL_NACH).text().strip()
            via_raw = self._table.item(row, _COL_VIA).text()
            via     = [v.strip() for v in via_raw.split(",") if v.strip()]

            reason = self._validate_row(name, von, nach)
            if reason is not None:
                skipped.append((name, reason))
                logger.info("Skip capture-save %s: %s", name, reason)
                continue

            entry = ZugEintrag(name=name, von=von, nach=nach, via=via)
            self._zug_manager._config.zuege[name] = entry
            saved += 1

        if saved:
            self._zug_manager._config.save()
            self._changes_made = True
        logger.info("Saved %d train entries from capture list (%d skipped)",
                    saved, len(skipped))

        # User-Feedback
        msg = f"{saved} Zug-Einträge gespeichert."
        if skipped:
            preview = "\n".join(f"  • {n} — {r}" for n, r in skipped[:10])
            extra = "" if len(skipped) <= 10 else f"\n  … +{len(skipped)-10} weitere"
            msg += (f"\n\n{len(skipped)} Einträge übersprungen "
                    f"(ungültige Daten):\n{preview}{extra}")
        QMessageBox.information(self, "Speichern", msg)

        self._populate()

    def has_changes(self) -> bool:
        return self._changes_made
