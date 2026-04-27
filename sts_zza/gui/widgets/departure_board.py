from __future__ import annotations

import datetime
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

# ── Echte DB-ZZA-Optik (Großformat, modernes Monitorbild) ────────────────────
_BG_BLUE      = "#1a3a8e"   # Haupt-Blau (etwas heller, näher am Foto)
_BG_DARK      = "#0e225a"   # dunklerer Trenner zwischen den Zonen
_FG_WHITE     = "#ffffff"
_FG_DIM       = "#cfdcff"   # leicht abgesetztes Weiß für Nebentext
_INFO_BG      = "#ffffff"   # weißer Info-Banner-Hintergrund
_INFO_FG      = "#1a3a8e"   # blauer Text auf Weiß
_WARN_BG      = "#d11317"   # DB-Rot für Durchfahrt-Warnung
_WARN_FG      = "#ffffff"   # weißer Text auf Rot

# Schrift wie auf echten DB-Monitoren — geometrische Sans-Serif
_FONT = "'Segoe UI', 'Helvetica Neue', 'Helvetica', 'Arial', sans-serif"


def _short_platform(platform: str) -> str:
    """
    Reduziert STS-Gleisnamen auf die reine Bahnsteig-Nummer für die
    Großanzeige. Beispiele:
      "MM 1"   → "1"
      "Gl. 3a" → "3a"
      "5"      → "5"
    Strategie: bei Leerzeichen den letzten Teil nehmen, sonst führende
    Buchstaben/Punkte abschneiden.
    """
    p = platform.strip()
    if " " in p:
        p = p.rsplit(" ", 1)[-1]
    # führende Nicht-Ziffern abschneiden ("Gl.3" → "3")
    i = 0
    while i < len(p) and not p[i].isdigit():
        i += 1
    return p[i:] if i < len(p) else p


def _style(color: str = _FG_WHITE,
           size: int = 11,
           bold: bool = False) -> str:
    s = (f"color:{color}; font-size:{size}pt; background:transparent; "
         f"font-family:{_FONT};")
    if bold:
        s += " font-weight:700;"
    return s


def _lbl(text: str,
         color: str = _FG_WHITE,
         size: int = 11,
         bold: bool = False,
         align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
         wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(align)
    lbl.setStyleSheet(_style(color, size, bold))
    lbl.setWordWrap(wrap)
    lbl.setContentsMargins(0, 0, 0, 0)
    return lbl


class _HSep(QFrame):
    def __init__(self, parent=None, height: int = 2,
                 color: str = _BG_DARK):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(height)
        self.setStyleSheet(f"background-color:{color}; border:none;")


class _InfoBanner(QLabel):
    """Weißer Info-Banner mit blauem Text — z. B. 'Hält nicht in …'."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter
                          | Qt.AlignmentFlag.AlignLeft)
        self.setStyleSheet(
            f"background-color:{_INFO_BG}; color:{_INFO_FG}; "
            f"font-size:10pt; font-weight:600; "
            f"padding:1px 8px; font-family:{_FONT};"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)


class _WarnBanner(QLabel):
    """Roter Warn-Banner — Zugdurchfahrt."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter
                          | Qt.AlignmentFlag.AlignLeft)
        self.setStyleSheet(
            f"background-color:{_WARN_BG}; color:{_WARN_FG}; "
            f"font-size:11pt; font-weight:700; "
            f"padding:2px 8px; font-family:{_FONT};"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)


class _DelayBox(QLabel):
    """Kleiner invertierter Kasten mit Ist-Abfahrtszeit (Verspätung)."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background-color:{_INFO_BG}; color:{_INFO_FG}; "
            f"font-size:10pt; font-weight:700; "
            f"padding:1px 5px; font-family:{_FONT};"
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum,
                           QSizePolicy.Policy.Fixed)


class _MainTrainWidget(QWidget):
    """
    Hauptzug-Block (oberer Bereich der ZZA):
      ┌──────┬──────────────┬──────────────────────────┐
      │      │ RE 3 / 3786  │ [Info-Banner]            │
      │  3   │              │ Chemnitz · Zwickau · Hof │
      │      │ 11:54 [11:59]│ Nürnberg Hbf             │
      └──────┴──────────────┴──────────────────────────┘
    """

    def __init__(self, entry: DisplayEntry, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color:{_BG_BLUE};")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        # Bei terminierenden Zügen mit bekanntem Startort: als Ankunft
        # darstellen ("Aus …" + Ankunftszeit). Der Folgezug-Bereich darunter
        # zeigt dann den nächsten Abfahrer ("Nicht einsteigen").
        as_arrival = (entry.is_terminating
                      and not entry.is_durchfahrt
                      and bool(entry.von))
        primary_time = entry.an if as_arrival and entry.an is not None else entry.ab

        # Querformat — zweispaltig wie auf großen DB-Bahnsteig-Monitoren:
        #   Links: Zugnummer (oben) · Zeit groß (unten) · Ist-Zeit-Kasten
        #   Rechts: Info-Banner (optional) · Via-Halte · Ziel RIESIG
        content = QHBoxLayout(self)
        content.setContentsMargins(12, 6, 12, 6)
        content.setSpacing(14)

        # ── Linke Inhaltsspalte ───────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(2)
        left.setContentsMargins(0, 0, 0, 0)

        left.addWidget(_lbl(entry.name, _FG_WHITE, size=10, bold=False))

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(6)
        time_lbl = _lbl(ms_to_hhmm(primary_time) or "--:--",
                        size=26, bold=True)
        time_row.addWidget(time_lbl)
        if entry.verspaetung > 0 and primary_time is not None:
            ist_t = primary_time + entry.verspaetung * 60_000
            time_row.addWidget(_DelayBox(ms_to_hhmm(ist_t) or ""))
        time_row.addStretch(1)
        left.addLayout(time_row)
        left.addStretch(1)

        left_holder = QWidget()
        left_holder.setLayout(left)
        left_holder.setStyleSheet("background:transparent;")
        left_holder.setSizePolicy(QSizePolicy.Policy.Fixed,
                                  QSizePolicy.Policy.Preferred)
        left_holder.setMinimumWidth(130)
        content.addWidget(left_holder)

        # ── Rechte Spalte ─────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(4)
        right.setContentsMargins(0, 0, 0, 0)

        # 1) Info-Banner (Verspätung / „Nicht einsteigen" / Durchfahrt /
        #    Ankunft — terminierende Züge bekommen einen eigenen Banner
        #    "Ankunft" statt "Nicht einsteigen!", damit klar erkennbar ist,
        #    dass dieser Zug HIER ENDET und nicht weiterfährt.)
        if entry.is_durchfahrt:
            right.addWidget(_WarnBanner(
                "+ + + Vorsicht — Zugdurchfahrt + + +"))
        else:
            info_text = self._build_info_text(entry, as_arrival)
            if info_text:
                right.addWidget(_InfoBanner(info_text))

        # 2) Via-Halte
        #    – Durchfahrt: entfällt (Zug hält nicht)
        #    – Ankunft (Endstation): Via zeigt die Strecke, AUS der der Zug
        #      kommt — informativ für wartende Fahrgäste, die ihn empfangen.
        if entry.via and not entry.is_durchfahrt:
            via_text = " · ".join(entry.via)
            right.addWidget(_lbl(via_text, _FG_DIM, size=10, wrap=True))

        # 3) Hauptzeile:
        #    – Durchfahrt:    "Zugdurchfahrt" (Richtung … klein darunter)
        #    – Endstation:    "Aus <Startort>"  (klar als Ankunft erkennbar)
        #    – Normal:         <Ziel> (Abfahrt)
        if entry.is_durchfahrt:
            right.addWidget(_lbl("Zugdurchfahrt", _FG_WHITE,
                                 size=24, bold=True))
            if entry.nach:
                right.addWidget(_lbl(f"Richtung {entry.nach}", _FG_DIM,
                                     size=11, wrap=True))
        elif as_arrival:
            # "Aus" als kleiner Vorsatz, dann Startort RIESIG
            right.addWidget(_lbl("Aus", _FG_DIM, size=11, bold=False))
            right.addWidget(_lbl(entry.von, _FG_WHITE,
                                 size=24, bold=True, wrap=True))
        else:
            nach_lbl = _lbl(entry.nach or "–", _FG_WHITE,
                            size=24, bold=True, wrap=True)
            right.addWidget(nach_lbl)
        right.addStretch(1)

        content.addLayout(right, stretch=1)

    @staticmethod
    def _build_info_text(entry: DisplayEntry, as_arrival: bool = False) -> str:
        parts = []
        if entry.verspaetung > 0:
            parts.append(f"+ + + ca. {entry.verspaetung} Minuten "
                         f"Verspätung + + +")
        if as_arrival:
            # Endstation mit erkanntem Startort → klar als Ankunft markieren
            parts.append("Ankunft — Zug endet hier")
        elif entry.is_terminating:
            # Endstation, Startort unbekannt → wenigstens nicht einsteigen
            parts.append("Nicht einsteigen!")
        return "   ".join(parts)


class _NextTrainRow(QWidget):
    """
    Folgezug-Zeile (unterer Bereich):
      Zeit  ·  Zugnummer  ·  Ziel  via …
    """

    def __init__(self, entry: DisplayEntry, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background-color:{_BG_BLUE};")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(14)

        t = _lbl(ms_to_hhmm(entry.ab) or "--:--",
                 _FG_WHITE, size=13, bold=True)
        t.setFixedWidth(60)
        layout.addWidget(t)

        n = _lbl(entry.name, _FG_WHITE, size=11)
        n.setFixedWidth(110)
        layout.addWidget(n)

        ziel = entry.nach or "–"
        if entry.via:
            ziel += "  via " + ", ".join(entry.via)
        z = _lbl(ziel, _FG_WHITE, size=13, bold=True)
        z.setSizePolicy(QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Preferred)
        layout.addWidget(z, stretch=1)

        if entry.is_durchfahrt:
            tag = QLabel("Durchfahrt")
            tag.setStyleSheet(
                f"background-color:{_WARN_BG}; color:{_WARN_FG}; "
                f"font-size:9pt; font-weight:700; padding:1px 6px; "
                f"font-family:{_FONT};"
            )
            layout.addWidget(tag)
        elif entry.is_terminating:
            tag = QLabel("Nicht einsteigen")
            tag.setStyleSheet(
                f"background-color:{_INFO_BG}; color:{_INFO_FG}; "
                f"font-size:9pt; font-weight:700; padding:1px 6px; "
                f"font-family:{_FONT};"
            )
            layout.addWidget(tag)

        if entry.verspaetung > 0 and entry.ab is not None:
            ist_ab = entry.ab + entry.verspaetung * 60_000
            layout.addWidget(_DelayBox(ms_to_hhmm(ist_ab) or ""))


class DepartureBoardWidget(QWidget):
    """
    DB-Bahnsteig-ZZA für ein einzelnes Gleis im modernen DB-Monitorstil.
    Aufbau:
      ┌─────────────────────────────────────────────┐
      │ HAUPTZUG (Zugnr/Zeit links · Banner/Via/Ziel)│
      ├─────────────────────────────────────────────┤
      │ Folgezug 1                                  │
      │ Folgezug 2                                  │
      └─────────────────────────────────────────────┘
    """

    _MAX_NEXT = 1

    # Feste Kachelgröße — alle Boards sind gleich groß und werden vom
    # Hauptfenster als Blöcke angeordnet (kein Strecken auf die Gridzelle).
    _BOARD_W = 800
    _BOARD_H = 200

    # Vorwarnzeit für die rot-blinkende Umrandung: wenn der nächste Abfahrer
    # innerhalb dieses Fensters losrollt (Sollabfahrt + Verspätung minus
    # System-Uhr), pulsiert der Rand. Hilfreich für den Fdl als visuelle
    # "gleich gehts los"-Erinnerung.
    _ALERT_LEAD_MS = 60_000      # 1 min vor Abfahrt
    _BLINK_INTERVAL_MS = 500     # 2 Hz Pulsfrequenz
    _ALERT_BORDER = "4px solid #ff1010"

    def __init__(self, platform: str, parent=None) -> None:
        super().__init__(parent)
        self._platform = platform
        self.setObjectName("ZzaBoard")
        self.setFixedSize(self._BOARD_W, self._BOARD_H)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # Wichtig: #ZzaBoard-Selektor — sonst erbt das Border alle Kinder
        # und wir bekommen Rahmen um jedes Label.
        self.setStyleSheet(
            f"#ZzaBoard {{ background-color:{_BG_BLUE}; border: 4px solid "
            f"transparent; }}"
        )

        self._alert_active = False
        self._blink_on = False
        self._last_entries: List[DisplayEntry] = []
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(self._BLINK_INTERVAL_MS)
        self._blink_timer.timeout.connect(self._on_blink)
        # Sekündlicher Tick — wertet den Alert auch zwischen STS-Updates
        # neu aus (sonst würde der Rand erst beim nächsten Server-Event
        # rot werden).
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(1000)
        self._watch_timer.timeout.connect(self._tick_alert)
        self._watch_timer.start()

        self._setup_ui()

    @staticmethod
    def _now_ms() -> int:
        n = datetime.datetime.now()
        return ((n.hour * 3600 + n.minute * 60 + n.second) * 1000
                + n.microsecond // 1000)

    def _evaluate_alert(self, entries: List[DisplayEntry]) -> bool:
        """True, wenn der nächste echte Abfahrer in <= 1 min losfährt."""
        now = self._now_ms()
        soonest_delta = None
        for e in entries:
            if e.ab is None or e.is_durchfahrt:
                continue
            t_eff = e.ab + (e.verspaetung or 0) * 60_000
            delta = t_eff - now
            if delta < -30_000:
                # schon mehr als 30 s überfällig → Zug ist eigentlich weg,
                # nicht mehr blinken.
                continue
            if soonest_delta is None or delta < soonest_delta:
                soonest_delta = delta
        return soonest_delta is not None and soonest_delta <= self._ALERT_LEAD_MS

    def _set_alert(self, on: bool) -> None:
        if on == self._alert_active:
            return
        self._alert_active = on
        if on:
            self._blink_on = True
            self._apply_border(True)
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_on = False
            self._apply_border(False)

    def _on_blink(self) -> None:
        self._blink_on = not self._blink_on
        self._apply_border(self._blink_on)

    def _tick_alert(self) -> None:
        """Re-bewertet den Alert jede Sekunde anhand der zuletzt bekannten
        Einträge — damit der Rahmen pünktlich rot wird, ohne auf das
        nächste STS-Event warten zu müssen."""
        self._set_alert(self._evaluate_alert(self._last_entries))

    def _apply_border(self, red: bool) -> None:
        border = self._ALERT_BORDER if red else "4px solid transparent"
        self.setStyleSheet(
            f"#ZzaBoard {{ background-color:{_BG_BLUE}; border: {border}; }}"
        )

    def _setup_ui(self) -> None:
        # Äußere Aufteilung: Gleisnummer links · Zugbereich rechts
        h_root = QHBoxLayout(self)
        h_root.setContentsMargins(0, 0, 0, 0)
        h_root.setSpacing(0)

        gleis_lbl = QLabel(_short_platform(self._platform))
        gleis_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gleis_lbl.setFixedWidth(100)
        gleis_lbl.setStyleSheet(
            f"background-color:{_BG_DARK}; color:{_FG_WHITE}; "
            f"font-family:{_FONT}; font-size:42pt; font-weight:700;"
        )
        h_root.addWidget(gleis_lbl)

        right_holder = QWidget()
        right_holder.setStyleSheet(f"background-color:{_BG_BLUE};")
        h_root.addWidget(right_holder, stretch=1)

        self._outer = QVBoxLayout(right_holder)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # Hauptzug-Bereich
        self._main_holder = QWidget()
        self._main_holder.setStyleSheet(f"background-color:{_BG_BLUE};")
        self._main_holder.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Expanding)
        self._main_layout = QVBoxLayout(self._main_holder)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        self._outer.addWidget(self._main_holder, stretch=3)

        # Trenner
        self._zone_sep = _HSep(height=3, color=_BG_DARK)
        self._outer.addWidget(self._zone_sep)

        # Folgezug-Bereich
        self._next_holder = QWidget()
        self._next_holder.setStyleSheet(f"background-color:{_BG_BLUE};")
        self._next_holder.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Expanding)
        self._next_layout = QVBoxLayout(self._next_holder)
        self._next_layout.setContentsMargins(0, 0, 0, 0)
        self._next_layout.setSpacing(0)
        self._outer.addWidget(self._next_holder, stretch=2)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def refresh(self, entries: List[DisplayEntry]) -> None:
        self._clear_layout(self._main_layout)
        self._clear_layout(self._next_layout)

        # Rot-blinkende Vorwarnung neu bewerten — auch wenn die Liste leer
        # ist (dann blinkt nichts). Snapshot speichern, damit der
        # Watch-Timer sekündlich nachprüft.
        self._last_entries = list(entries)
        self._set_alert(self._evaluate_alert(entries))

        if not entries:
            empty = _lbl("Kein Zug angekündigt", _FG_DIM, size=12,
                         align=Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 24, 0, 24)
            self._main_layout.addWidget(empty)
            self._main_layout.addStretch(1)
            self._zone_sep.hide()
            self._next_holder.hide()
            return

        # Hauptzug
        self._main_layout.addWidget(_MainTrainWidget(entries[0]))
        self._main_layout.addStretch(1)

        # Folgezüge
        following = entries[1:1 + self._MAX_NEXT]
        if following:
            self._zone_sep.show()
            self._next_holder.show()
            for i, e in enumerate(following):
                if i > 0:
                    self._next_layout.addWidget(
                        _HSep(height=1, color=_BG_DARK))
                self._next_layout.addWidget(_NextTrainRow(e))
            self._next_layout.addStretch(1)
        else:
            self._zone_sep.hide()
            self._next_holder.hide()
