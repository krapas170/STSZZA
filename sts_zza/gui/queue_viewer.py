from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
)

if TYPE_CHECKING:
    from ..audio.announcer import Announcer


class AnnouncementQueueViewer(QDialog):
    """
    Kleines, nicht-modales Fenster, das die aktuell laufende und die
    wartenden Ansagen des Announcers zeigt. Pollt 2× pro Sekunde.
    """

    def __init__(self, announcer: "Announcer", parent=None) -> None:
        super().__init__(parent)
        self._announcer = announcer

        self.setWindowTitle("Ansage-Warteschlange")
        self.setMinimumSize(440, 280)
        # Fenster ohne Modal-Sperre — der Nutzer soll parallel die ZZA
        # weiter beobachten können.
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.setStyleSheet(
            "QDialog { background-color: #111418; color: #e6ecf2; }"
            "QLabel { color: #e6ecf2; }"
            "QListWidget { background-color: #1b2028; color: #e6ecf2; "
            "  border: 1px solid #2a3440; }"
            "QListWidget::item { padding: 4px; }"
            "QPushButton { background-color: #2a3440; color: #e6ecf2; "
            "  border: 1px solid #3a4a5e; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #3a4a5e; }"
        )

        layout = QVBoxLayout(self)

        self._lbl_current = QLabel("Aktuell: —")
        self._lbl_current.setWordWrap(True)
        self._lbl_current.setStyleSheet(
            "font-weight: bold; color: #ffd866; padding: 4px;")
        layout.addWidget(self._lbl_current)

        layout.addWidget(QLabel("Wartet:"))
        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        self._lbl_count = QLabel("0 Ansagen in der Warteschlange.")
        self._lbl_count.setStyleSheet("color: #8899aa;")
        layout.addWidget(self._lbl_count)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _refresh(self) -> None:
        current, pending = self._announcer.snapshot()
        self._lbl_current.setText(
            f"Aktuell: {current}" if current else "Aktuell: —")

        # Inhalt nur neu setzen, wenn sich etwas geändert hat — verhindert
        # Flackern und Verlust einer evtl. Auswahl.
        existing = [self._list.item(i).text()
                    for i in range(self._list.count())]
        if existing != pending:
            self._list.clear()
            for text in pending:
                self._list.addItem(QListWidgetItem(text))

        n = len(pending)
        self._lbl_count.setText(
            f"{n} Ansage{'n' if n != 1 else ''} in der Warteschlange.")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
