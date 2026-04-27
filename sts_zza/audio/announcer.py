from __future__ import annotations

import logging
import math
import queue
import re
import struct
import threading
import wave
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYTTSX3_AVAILABLE = False
    logger.warning("pyttsx3 not installed — Ansagen sind deaktiviert.")

try:
    import winsound
    _WINSOUND_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WINSOUND_AVAILABLE = False


# ── Gong-Erzeugung ───────────────────────────────────────────────────────────
# Wir synthetisieren beim ersten Start einmalig eine WAV-Datei mit dem
# klassischen 3-Ton-Aufmerksamkeitssignal (Triton-artig: H-Fis-D, fallend).
# Jeder Ton ist eine Glocke aus Grundton + Obertönen mit exponentiellem
# Abklingen — klingt wie ein echter Gong, kein Piepser.

_SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"
_GONG_PATH = _SOUNDS_DIR / "gong.wav"

_SAMPLE_RATE = 44100

# (Frequenz Hz, Startzeit s, Dauer s, Anschlagslautstärke)
_GONG_NOTES = [
    (659.25, 0.00, 1.30, 0.85),   # E5
    (523.25, 0.32, 1.40, 0.80),   # C5
    (392.00, 0.66, 1.80, 0.95),   # G4
]
# Obertonstruktur einer weichen Glocke (Faktor, relative Lautstärke, Decay)
_PARTIALS = [
    (1.0,  1.00, 1.0),
    (2.0,  0.55, 1.4),
    (3.0,  0.30, 1.9),
    (4.2,  0.18, 2.4),
    (5.4,  0.10, 3.0),
]
_TOTAL_DUR = 2.6   # Gesamtlänge der WAV in s


def _synthesize_gong(path: Path) -> None:
    n_samples = int(_SAMPLE_RATE * _TOTAL_DUR)
    buf = [0.0] * n_samples

    for freq, t0, dur, amp in _GONG_NOTES:
        start = int(t0 * _SAMPLE_RATE)
        length = int(dur * _SAMPLE_RATE)
        for i in range(length):
            if start + i >= n_samples:
                break
            t = i / _SAMPLE_RATE
            # leichter Einschwinger (5 ms), dann exp. Abklingen
            attack = min(1.0, t / 0.005)
            sample = 0.0
            for mult, p_amp, p_decay in _PARTIALS:
                env = math.exp(-p_decay * t / dur * 4.0)
                sample += p_amp * env * math.sin(
                    2.0 * math.pi * freq * mult * t)
            buf[start + i] += amp * attack * sample * 0.18

    # Normalisieren auf -1..1
    peak = max(abs(s) for s in buf) or 1.0
    scale = 0.95 / peak
    pcm = b"".join(
        struct.pack("<h", max(-32768, min(32767, int(s * scale * 32767))))
        for s in buf
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(pcm)
    logger.info("Gong-WAV erzeugt: %s", path)


def _ensure_gong_file() -> Optional[Path]:
    try:
        if not _GONG_PATH.exists() or _GONG_PATH.stat().st_size < 1000:
            _synthesize_gong(_GONG_PATH)
        return _GONG_PATH
    except Exception as exc:
        logger.warning("Konnte Gong nicht erzeugen: %s", exc)
        return None


def _play_gong() -> None:
    """Spielt den Aufmerksamkeits-Gong (blockierend) vor einer Ansage."""
    if not _WINSOUND_AVAILABLE:
        return
    path = _ensure_gong_file()
    if path is None:
        return
    try:
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_NODEFAULT,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("Gong fehlgeschlagen: %s", exc)


class Announcer:
    """
    Zentraler Bahnhofs-Announcer.

    Eine einzige TTS-Stimme für den ganzen Bahnhof. Texte werden in eine
    Queue gelegt und seriell vom Worker-Thread vorgelesen — auch wenn
    mehrere Trigger zeitgleich ausgelöst werden, hört man sie nacheinander.

    Per `enabled = False` lässt sich die Sprachausgabe komplett stummschalten.
    Mit `set_platform_enabled(platform, on)` kann man einzelne Gleise
    von Ansagen ausschließen.
    """

    def __init__(self) -> None:
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._enabled: bool = _PYTTSX3_AVAILABLE
        self._enabled_platforms: Optional[Set[str]] = None  # None = alle

        if _PYTTSX3_AVAILABLE:
            self._start_worker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> None:
        """Globale An/Aus-Schaltung. Bei Aus wird die Queue geleert."""
        self._enabled = on and _PYTTSX3_AVAILABLE
        if not self._enabled:
            self._drain_queue()

    def set_platform_enabled(self, platform: str, on: bool) -> None:
        """Einzelnes Gleis von Ansagen ausnehmen oder wieder einschließen."""
        if self._enabled_platforms is None:
            # bisher 'alle' — initialisiere mit voller Liste minus dem aus
            self._enabled_platforms = set()
        if on:
            self._enabled_platforms.add(platform)
        else:
            self._enabled_platforms.discard(platform)

    def is_platform_enabled(self, platform: str) -> bool:
        if self._enabled_platforms is None:
            return True
        return platform in self._enabled_platforms

    def announce(self, text: str, platform: Optional[str] = None) -> None:
        """
        Reiht eine Ansage in die Queue ein.
        Wenn `platform` angegeben ist und für dieses Gleis Ansagen
        deaktiviert sind, wird die Ansage verworfen.
        """
        if not self._enabled or not text.strip():
            return
        if platform is not None and not self.is_platform_enabled(platform):
            return
        self._queue.put(text)

    def shutdown(self) -> None:
        """Worker-Thread sauber beenden (beim App-Exit aufrufen)."""
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _start_worker(self) -> None:
        self._worker = threading.Thread(
            target=self._worker_loop, name="Announcer", daemon=True)
        self._worker.start()

    def _configure_engine(self, engine) -> None:
        """Deutsche Stimme + Tempo/Volume setzen."""
        try:
            for v in engine.getProperty("voices"):
                lang = (getattr(v, "languages", []) or [""])[0]
                name = (v.name or "").lower()
                if "german" in name or "deutsch" in name or b"de" in (
                        lang if isinstance(lang, bytes) else lang.encode()):
                    engine.setProperty("voice", v.id)
                    if not self._voice_logged:
                        logger.info("TTS-Stimme: %s", v.name)
                        self._voice_logged = True
                    break
        except Exception:
            pass
        engine.setProperty("rate", 165)
        engine.setProperty("volume", 1.0)

    def _worker_loop(self) -> None:
        # Pro Ansage wird die Engine neu erzeugt — vermeidet einen bekannten
        # pyttsx3-SAPI-Bug, bei dem nach dem ersten runAndWait() folgende
        # say()-Aufrufe stumm bleiben (queue läuft ins Leere).
        self._voice_logged = False
        while True:
            text = self._queue.get()
            if text is None:
                break
            if not self._enabled:
                continue
            try:
                _play_gong()
                engine = pyttsx3.init()
                self._configure_engine(engine)
                engine.say(_normalize_for_tts(text))
                engine.runAndWait()
                try:
                    engine.stop()
                except Exception:
                    pass
                del engine
            except Exception as exc:
                logger.warning("TTS-Fehler: %s", exc)

    def _drain_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass


# ── TTS-Normalisierung ───────────────────────────────────────────────────────
#
# SAPI/Hedda spricht "Gleis 4." als "Gleis vierte" aus, weil der Punkt direkt
# nach der Zahl als Ordnungszahl interpretiert wird. Daher in den Bausteinen
# unten konsequent Komma oder Gedankenstrich nach Zahlen, kein Punkt.
#
# Außerdem ersetzen wir typische Bahn-Abkürzungen (Hbf → Hauptbahnhof) und
# entfernen Klammern (z. B. "Kempten (Allgäu)" → "Kempten Allgäu"), damit
# die Sprachausgabe natürlich klingt.

_TTS_REPLACEMENTS = [
    # Bahnhofs-Abkürzungen
    (re.compile(r"\bHbf\b", re.IGNORECASE), "Hauptbahnhof"),
    (re.compile(r"\bBhf\b", re.IGNORECASE), "Bahnhof"),
    (re.compile(r"\bHp\b"), "Haltepunkt"),
    (re.compile(r"\bBw\b"), "Betriebswerk"),
    # Zug-Gattungen — die deutsche TTS-Stimme spricht "ICE" sonst als
    # Wort ("Eis"), "IC" als "Ick", "EC" als "Eck" usw. Wir ersetzen die
    # Kürzel deshalb durch ihre offiziellen DB-Langformen, wenn sie als
    # Zug-Gattung (vor einer Nummer) auftreten.
    (re.compile(r"\bICE\b(?=\s*\d)"), "Intercity-Express"),
    (re.compile(r"\bIC\b(?=\s*\d)"),  "Intercity"),
    (re.compile(r"\bEC\b(?=\s*\d)"),  "Eurocity"),
    (re.compile(r"\bECE\b(?=\s*\d)"), "Eurocity-Express"),
    (re.compile(r"\bIRE\b(?=\s*\d)"), "Interregio-Express"),
    (re.compile(r"\bRE\b(?=\s*\d)"),  "Regional-Express"),
    (re.compile(r"\bRB\b(?=\s*\d)"),  "Regionalbahn"),
    (re.compile(r"\bRJ\b(?=\s*\d)"),  "Railjet"),
    (re.compile(r"\bRJX\b(?=\s*\d)"), "Railjet-Express"),
    (re.compile(r"\bNJ\b(?=\s*\d)"),  "Nightjet"),
    (re.compile(r"\bEN\b(?=\s*\d)"),  "EuroNight"),
    (re.compile(r"\bCNL\b(?=\s*\d)"), "CityNightLine"),
    (re.compile(r"\bTGV\b(?=\s*\d)"), "T G V"),
    # S-Bahn explizit als "S-Bahn", nicht als Buchstabe "Es"
    (re.compile(r"\bS\b(?=\s*\d)"),   "S-Bahn"),
]


def _short_platform(platform: str) -> str:
    """Reduziert "MM 2" → "2", "Gl.3a" → "3a" für die Sprachausgabe."""
    p = (platform or "").strip()
    if " " in p:
        p = p.rsplit(" ", 1)[-1]
    i = 0
    while i < len(p) and not p[i].isdigit():
        i += 1
    return p[i:] if i < len(p) else p


def _normalize_for_tts(text: str) -> str:
    for pat, rep in _TTS_REPLACEMENTS:
        text = pat.sub(rep, text)
    # Klammern weg, Inhalt behalten: "Kempten (Allgäu)" → "Kempten Allgäu"
    text = re.sub(r"\s*\(([^)]*)\)", r" \1", text)
    # doppelte Leerzeichen aufräumen
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Textbausteine ────────────────────────────────────────────────────────────

def text_einfahrt(platform: str, name: str, nach: str,
                  via: Optional[list] = None) -> str:
    """
    Einfahrt-Ansage ~1 min vor planmäßiger Ankunft:
    Gleis, Zug, Ziel, Via, Vorsicht-Hinweis.
    """
    via_part = f" über {', '.join(via)}" if via else ""
    return (f"Gleis {_short_platform(platform)} — Einfahrt {name} "
            f"nach {nach}{via_part}. "
            f"Vorsicht bei der Einfahrt. Bitte zurückbleiben.")


def text_ankunft(station: str, platform: str, name: str, von: str,
                 anschluesse: Optional[List[str]] = None) -> str:
    """
    Willkommens-Ansage, wenn der Zug am Bahnsteig steht.
    Optional: Anschlussübersicht.
    """
    von_part = f" aus {von}" if von else ""
    base = (f"Auf Gleis {_short_platform(platform)}, {name}{von_part}. "
            f"Willkommen in {station}. Wir wünschen Ihnen "
            f"einen angenehmen Aufenthalt.")
    if anschluesse:
        base += " Weitere Reisemöglichkeiten: " + " — ".join(anschluesse) + "."
    return base


def text_verspaetung(name: str, nach: str, minuten: int) -> str:
    return (f"Information zu {name} nach {nach}: "
            f"Dieser Zug hat heute voraussichtlich circa {minuten} Minuten "
            f"Verspätung. Wir bitten um Verständnis.")


def text_durchfahrt(platform: str, name: str, nach: str,
                    via: Optional[list] = None) -> str:
    """
    Durchfahrt-Ansage: Zug fährt ohne Halt durch.
    Klassisch DB: Vorsicht-Hinweis + Bitte zurücktreten.
    """
    via_part = f" über {', '.join(via)}" if via else ""
    return (f"Achtung an Gleis {_short_platform(platform)} — "
            f"Durchfahrt {name} nach {nach}{via_part}. "
            f"Vorsicht bei der Durchfahrt. "
            f"Bitte vom Bahnsteig zurücktreten.")


def text_endet_hier(platform: str, name: str) -> str:
    return (f"Gleis {_short_platform(platform)} — {name} endet hier. "
            f"Bitte alle aussteigen, nicht mehr einsteigen.")


# Rückwärtskompatibilität (falls irgendwo noch text_abfahrt referenziert wird)
def text_abfahrt(platform: str, name: str, nach: str) -> str:
    return (f"Auf Gleis {_short_platform(platform)} — {name} nach {nach}. "
            f"Bitte zurückbleiben.")
