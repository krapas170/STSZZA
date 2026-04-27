from __future__ import annotations

import logging
import os
import sys
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
    QVBoxLayout,
)

from ..audio.announcer import (
    Announcer,
    text_ankunft,
    text_durchfahrt,
    text_einfahrt,
    text_endet_hier,
    text_verspaetung,
)
from ..config.station_config import StationConfig
from ..logic.train_manager import ZugManager
from ..protocol.client import STSClient
from ..protocol.models import BahnsteigInfo
from .dispatcher_view import DispatcherView
from .passenger_view import PassengerView

logger = logging.getLogger(__name__)

_IDX_PLACEHOLDER  = 0
_IDX_PASSENGER    = 1
_IDX_DISPATCHER   = 2

_REFRESH_INTERVAL_MS = 30_000  # poll zugliste every 30 s


class _PlaceholderView(QWidget):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #8899aa; font-size: 13pt;")
        layout.addWidget(label)
        self.setStyleSheet("background-color: #000000;")


class ZZAMainWindow(QMainWindow):
    """
    Hauptfenster. Verwaltet drei Stacked-Views:
      0 — Platzhalter (während Verbindungsaufbau / Gleisauswahl)
      1 — Fahrgast-Ansicht (grafische ZZA-Boards)
      2 — Fdl-Ansicht (Tabelle)

    Empfängt STSClient-Signale, hält ZugManager auf dem aktuellen Stand
    und löst alle 30 s einen Zuglistenabgleich aus.
    """

    def __init__(self,
                 client: STSClient,
                 config: StationConfig,
                 zug_manager: ZugManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._client = client
        self._config = config
        self._zug_manager = zug_manager
        self._selected_platforms: List[str] = []

        self._announcer = Announcer()
        self._zug_manager.event_listener = self._on_train_event

        self._setup_ui()
        self._connect_signals()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._poll_zugliste)

        # Debounce-Timer für UI-Refresh: bündelt viele schnell aufeinander
        # folgende Detail-Antworten (München Hbf: hunderte Züge gleichzeitig)
        # zu einem einzigen UI-Rebuild.
        self._view_refresh_timer = QTimer(self)
        self._view_refresh_timer.setSingleShot(True)
        self._view_refresh_timer.setInterval(250)
        self._view_refresh_timer.timeout.connect(self._do_refresh_views)

    # ------------------------------------------------------------------
    # Public API (called from app.py)
    # ------------------------------------------------------------------

    def set_config(self, config: StationConfig) -> None:
        self._config = config
        self._zug_manager._config = config
        self.setWindowTitle(f"STS ZZA — {config.station_name}")

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("STS ZZA — Zugzielanzeiger")
        self.setMinimumSize(960, 560)

        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(
            "QMenuBar { background-color: #1b2838; color: #f0f4f8; }"
            "QMenuBar::item:selected { background-color: #2a4060; }"
            "QMenu { background-color: #1b2838; color: #f0f4f8; }"
            "QMenu::item:selected { background-color: #2a4060; }"
        )

        view_menu = menu_bar.addMenu("Ansicht")
        self._action_fahrgast = view_menu.addAction("Fahrgast-Ansicht")
        self._action_fdl      = view_menu.addAction("Fdl-Ansicht")
        self._action_fahrgast.setEnabled(False)
        self._action_fdl.setEnabled(False)

        tools_menu = menu_bar.addMenu("Werkzeuge")
        self._action_editor = tools_menu.addAction("Analyse && Editor")
        self._action_editor.setEnabled(False)

        tools_menu.addSeparator()
        self._action_announcements = tools_menu.addAction("Ansagen aktiv")
        self._action_announcements.setCheckable(True)
        self._action_announcements.setChecked(self._announcer.enabled)
        self._action_announcements.toggled.connect(
            self._announcer.set_enabled)

        tools_menu.addSeparator()
        self._action_restart = tools_menu.addAction("Neustart")
        self._action_restart.setShortcut("Ctrl+R")
        self._action_restart.triggered.connect(self._restart_app)

        self._stack = QStackedWidget()
        self._placeholder    = _PlaceholderView("Verbinde mit StellwerkSim …")
        self._passenger_view = PassengerView()
        self._dispatcher_view = DispatcherView()

        self._stack.addWidget(self._placeholder)      # index 0
        self._stack.addWidget(self._passenger_view)   # index 1
        self._stack.addWidget(self._dispatcher_view)  # index 2
        self.setCentralWidget(self._stack)

        status_bar = QStatusBar()
        status_bar.setStyleSheet(
            "QStatusBar { background-color: #111111; color: #8899aa; }")
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("Verbinde …")

    def _connect_signals(self) -> None:
        self._client.connected.connect(self._on_connected)
        self._client.sig_anlageninfo.connect(self._on_anlageninfo)
        self._client.sig_bahnsteigliste.connect(self._on_bahnsteigliste)
        self._client.sig_zugliste.connect(self._on_zugliste)
        self._client.sig_zugdetails.connect(self._on_zugdetails)
        self._client.sig_zugfahrplan.connect(self._on_zugfahrplan)

        self._action_fahrgast.triggered.connect(
            lambda: self._stack.setCurrentIndex(_IDX_PASSENGER))
        self._action_fdl.triggered.connect(
            lambda: self._stack.setCurrentIndex(_IDX_DISPATCHER))
        self._action_editor.triggered.connect(self._open_editor)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        self.statusBar().showMessage("Verbunden — lade Anlageninformationen …")
        self._client.request_anlageninfo()
        self._client.request_bahnsteigliste()

    def _on_anlageninfo(self, info) -> None:
        self.setWindowTitle(f"STS ZZA — {info.name}")
        self.statusBar().showMessage(f"Verbunden mit: {info.name}")
        logger.info("Anlage: %s (AID=%s)", info.name, info.aid)

    def _on_bahnsteigliste(self, bahnsteige: List[BahnsteigInfo]) -> None:
        from .platform_selector import PlatformSelectorDialog
        dlg = PlatformSelectorDialog(bahnsteige, self._config.bahnsteige, self)
        if not dlg.exec():
            self.statusBar().showMessage("Keine Bahnsteige ausgewählt.")
            return

        self._selected_platforms = dlg.selected_platforms()
        self._config.bahnsteige = self._selected_platforms
        self._config.save()

        self._passenger_view.set_platforms(self._selected_platforms)

        self._action_fahrgast.setEnabled(True)
        self._action_fdl.setEnabled(True)
        self._action_editor.setEnabled(True)

        # Default: Fahrgast-Ansicht
        self._stack.setCurrentIndex(_IDX_PASSENGER)
        self.statusBar().showMessage(
            f"{len(self._selected_platforms)} Gleis(e) ausgewählt — lade Züge …")

        self._poll_zugliste()
        self._refresh_timer.start()

    def _on_zugliste(self, zl: dict) -> None:
        new_zids = self._zug_manager.update_zugliste(zl)
        # 1) Neue Züge: vollständige Details holen.
        for zid in new_zids:
            self._client.request_zugdetails(zid)
        # 2) Bekannte Züge: nur die auf ausgewählten Gleisen refreshen
        #    (für Verspätungs-/Gleisänderungen). Alles andere zu pollen
        #    skaliert nicht bei großen Stellwerken (München Hbf).
        if self._selected_platforms:
            sel = set(self._selected_platforms)
            for zid, record in self._zug_manager._zuege.items():
                if zid in new_zids:
                    continue
                d = record.details
                if d and (d.gleis in sel or d.plangleis in sel):
                    self._client.request_zugdetails(zid)

    def _on_zugdetails(self, zid: int, details) -> None:
        logger.debug(
            "[STS] zugdetails  zid=%-6s name=%-18s gleis=%-6s plangleis=%-6s "
            "sichtbar=%-5s amgleis=%-5s vsp=%+d  von=%r  nach=%r  "
            "usertext=%r  hinweistext=%r",
            zid, details.name, details.gleis, details.plangleis,
            details.sichtbar, details.amgleis, details.verspaetung,
            details.von, details.nach, details.usertext, details.hinweistext,
        )
        changed = self._zug_manager.update_details(zid, details)
        if changed:
            self._client.request_zugfahrplan(zid)
        self._refresh_views()

    def _on_zugfahrplan(self, zid: int, plan) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            for z in plan.zeilen:
                logger.debug(
                    "[STS] fahrplan    zid=%-6s  plan=%-8s  name=%-8s  "
                    "an=%-7s  ab=%-7s  flags=%r  hinweis=%r",
                    plan.zid, z.plan, z.name,
                    z.an, z.ab, z.flags, z.hinweistext,
                )
        self._zug_manager.update_fahrplan(zid, plan)
        self._refresh_views()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _poll_zugliste(self) -> None:
        self._client.request_zugliste()

    def _refresh_views(self) -> None:
        # Statt sofort zu rebuilden: 250ms-Debounce, damit beim Initial-Load
        # nicht hunderte Refreshes hintereinander laufen.
        if not self._view_refresh_timer.isActive():
            self._view_refresh_timer.start()

    def _do_refresh_views(self) -> None:
        idx = self._stack.currentIndex()
        if idx == _IDX_PASSENGER:
            self._passenger_view.refresh(self._zug_manager)
        elif idx == _IDX_DISPATCHER:
            self._dispatcher_view.refresh(self._zug_manager)

    def _on_train_event(self, event_type: str, **kwargs) -> None:
        """
        Wird vom ZugManager bei Statuswechseln gerufen und reicht eine
        passende Ansage an den zentralen Announcer weiter.
        """
        platform = kwargs.get("platform", "")
        # Nur Ansagen für ausgewählte Bahnsteige
        if platform and platform not in self._selected_platforms:
            return

        if event_type == "einfahrt":
            if kwargs.get("is_durchfahrt"):
                text = text_durchfahrt(platform, kwargs["name"],
                                       kwargs["nach"], kwargs.get("via"))
            elif kwargs.get("is_terminating"):
                text = text_endet_hier(platform, kwargs["name"])
            else:
                text = text_einfahrt(platform, kwargs["name"],
                                     kwargs["nach"], kwargs.get("via"))
        elif event_type == "ankunft":
            text = text_ankunft(
                station=kwargs.get("station", ""),
                platform=platform,
                name=kwargs["name"],
                von=kwargs.get("von", ""),
                anschluesse=self._build_anschluesse(kwargs["name"]),
            )
        elif event_type == "endet_hier":
            text = text_endet_hier(platform, kwargs["name"])
        elif event_type == "verspaetung":
            text = text_verspaetung(kwargs["name"], kwargs["nach"],
                                    kwargs["minuten"])
        else:
            return

        self._announcer.announce(text, platform=platform)

    def _build_anschluesse(self, exclude_name: str,
                           limit: int = 3) -> List[str]:
        """
        Liefert die nächsten `limit` Abfahrten von den ausgewählten Gleisen
        als kurze Stichworte für die Willkommens-Ansage.
        """
        if not self._selected_platforms:
            return []
        entries = self._zug_manager.get_all_display_data(
            self._selected_platforms)
        out: List[str] = []
        for e in entries:
            if e.name == exclude_name:
                continue
            if e.ab is None:
                continue
            hh = (e.ab // 3_600_000) % 24
            mm = (e.ab % 3_600_000) // 60_000
            out.append(
                f"{e.name} nach {e.nach} um {hh:02d}:{mm:02d} "
                f"von Gleis {e.plangleis}")
            if len(out) >= limit:
                break
        return out

    def closeEvent(self, event) -> None:
        try:
            self._announcer.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    def _restart_app(self) -> None:
        """
        Startet das Plugin neu — ohne dass der Nutzer es vorher schließen
        muss. Schritte:
          1) kurze Bestätigung,
          2) STS-Verbindung sauber trennen, Announcer stoppen,
          3) den Python-Interpreter mit denselben Argumenten erneut
             starten und das aktuelle Fenster schließen.

        Auf Windows ist `os.execv` zickig (Pfade mit Leerzeichen, frozen
        exes), deshalb wird ein neuer Prozess via `QProcess.startDetached`
        gestartet und der aktuelle danach via `quit()` beendet.
        """
        if QMessageBox.question(
            self, "Neustart",
            "Programm neu starten? Aktuelle Verbindung wird getrennt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            return

        # Sauberes Herunterfahren — Announcer-Worker, STS-Socket
        try:
            self._announcer.shutdown()
        except Exception as exc:
            logger.debug("announcer shutdown failed: %s", exc)
        try:
            self._client.disconnect()
        except Exception as exc:
            logger.debug("client disconnect failed: %s", exc)

        # Neuen Prozess starten
        from PyQt6.QtCore import QProcess
        prog = sys.executable
        args = sys.argv[:]
        # Wenn das Skript direkt ausgeführt wurde (python main.py), liegt
        # das Skript in args[0]. Wenn als „frozen" exe (PyInstaller),
        # ist sys.argv[0] die exe — dann genügt prog = exe-Pfad ohne args.
        if getattr(sys, "frozen", False):
            QProcess.startDetached(prog, args[1:])
        else:
            QProcess.startDetached(prog, args)

        logger.info("Restart requested — quitting current process")
        QApplication.instance().quit()

    def _open_editor(self) -> None:
        from .editor_dialog import EditorDialog
        dlg = EditorDialog(self._zug_manager, self)
        dlg.exec()
        # After saving, re-check all trains against updated config
        for record in self._zug_manager.get_all_records():
            self._zug_manager.update_details(
                record.details.zid, record.details)
        self._refresh_views()
