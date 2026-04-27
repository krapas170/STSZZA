from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..config.station_config import StationConfig, ZugEintrag
from ..protocol.models import ZugDetails, ZugFahrplan

logger = logging.getLogger(__name__)

# STS-interne "Bahnhofsnamen", die in Wirklichkeit den aktuellen Bahnhof
# repräsentieren (Zug fährt aus/in die Abstellung, kommt aus dem Bw, …).
_INTERNAL_DEPOT_NAMES = {
    "abstellung", "abstellanlage", "abstellgleis",
    "bw", "betriebswerk",
}

# Wie lange ein abgefahrener Zug noch auf der ZZA bleiben darf, bevor wir
# ihn ausblenden (Sekunden ab amgleis 1→0).
_DEPARTED_HIDE_AFTER_S = 30.0

# Dienst-/Leerfahrten-Gattungen, die niemals in der Capture-Liste landen
# sollen. Suffix -D/-G/-E (Diesel/Güter/Elektro) wird automatisch toleriert.
_DIENST_BASE_GATTUNGEN = {
    "DPN", "DPF", "DLr", "DLt", "DGS",
    "Lok", "Lr", "Lt", "Rf",
}


def _is_dienstfahrt(zugname: str) -> bool:
    """True wenn der Zugname eine Dienst-/Leerfahrt-Gattung trägt.

    Erkennt nur die echten Dienst-Bases (DPN, DPF, DLr, DLt, DGS, Lok, Lr,
    Lt, Rf), auch mit Suffix wie -D/-G/-E.

    Hinweis: Suffixe `-D`/`-G`/`-E` an regulären Gattungen (RE-D, RB-G, …)
    bedeuten Doppeltraktion / Sandbox-Variante, NICHT Dienstfahrt — diese
    Züge fahren regulären Linienverkehr und werden nicht gefiltert.
    """
    if not zugname:
        return False
    gat = zugname.split(" ", 1)[0]
    base = gat.split("-", 1)[0]
    return base in _DIENST_BASE_GATTUNGEN


# Stellwerks-interne Bereichs-/Gleis-/Hilfsnamen, die als Reise-Ziel
# unbrauchbar sind. Wenn ein Zug nach Config-Anwendung immer noch dorthin
# fährt, blenden wir ihn auf der Fahrgast-ZZA aus.
_INTERNAL_AREA_NACH = (
    "stammstrecke", "pasing aulido", "pasing fernbahn",
    "kanal landshut", "kanal ingolstadt",
    "laim rbf", "münchen süd", "muenchen sued",
    "vn", "vs ",
)


def _is_internal_area(value: str) -> bool:
    """True wenn `value` ein Stellwerks-interner Bereich/Gleisname ist."""
    if not value:
        return False
    low = value.strip().lower()
    if low.startswith("gleis "):
        return True
    for hint in _INTERNAL_AREA_NACH:
        if hint == low or low.startswith(hint):
            return True
    return False


def _is_betriebsbahnhof(value: str) -> bool:
    """
    True wenn `value` ein Betriebsbahnhof (Bbf) / Abstellbahnhof ist.

    Solche Ziele sind keine echten Fahrgast-Bahnhöfe — der Zug rollt nur
    zur Abstellung weiter. Auf der ZZA muss daher „Nicht einsteigen!"
    stehen, auch wenn der Zug formal noch nicht endet.
    """
    if not value:
        return False
    low = value.strip().lower()
    # Endet auf "Bbf" / "Betriebsbahnhof" oder enthält " Bbf" als Wort.
    if low.endswith(" bbf") or low == "bbf":
        return True
    if "betriebsbahnhof" in low:
        return True
    return False


# STS-Hinweistext liefert oft einen Streckenstring der Form
#   "Zuglänge: 156 m | RE 70 München Hbf - Lindau-Reutin via Kempten"
#   "Zuglänge: 278 m | Saarbrücken Hbf - Graz Hbf (AT)"
#   "Betriebliche Abfahrtszeit: 10:47 Uhr | Zuglänge: 346 m | Innsbruck - Berlin Gesundbrunnen via Frankfurt"
# Pipes trennen Segmente; das Strecken-Segment enthält " - " zwischen
# zwei Bahnhofsnamen, evtl. mit führender Linien-Kennung und
# nachgestelltem "via <Ort>[, <Ort>]".
_RE_LINIE_PREFIX = re.compile(
    r"^"
    # optional Verkehrsbetreiber-Kürzel ("BRB", "BOB", "BLB", "VIA" …)
    r"(?:(?:BRB|BOB|BEX|BLB|MEX|ALX|VIA|FLX|FEX|GoA|DLB|WFB)\s+)?"
    # Linien-Gattung + Nummer(n)
    r"(?:RE|RB|R|S|IRE|IC|ICE|EC|ECE|RJ|RJX|NJ|EN|TGV)\s*\d+(?:[/]\d+)*"
    r"\s+",
    re.IGNORECASE,
)
_RE_VIA = re.compile(r"\s+via\s+", re.IGNORECASE)


def _parse_hinweistext(text: str) -> Optional[tuple[str, str, list[str]]]:
    """Parst STS-Hinweistext → (von, nach, via_list).

    Liefert None, wenn kein Strecken-Segment erkannt wurde.
    """
    if not text or " - " not in text:
        return None
    for raw_seg in text.split("|"):
        seg = raw_seg.strip()
        if " - " not in seg:
            continue
        # Segmente, die nur Zusatzinfo enthalten, ausschließen.
        low = seg.lower()
        if (low.startswith("zuglänge")
                or low.startswith("betriebliche")
                or low.startswith("zuglaenge")
                or "km/h" in low
                or low.startswith("bemerkung")):
            continue
        # Optionale Linien-Kennung am Anfang abschneiden ("RE 70 ", "RB 40 …")
        seg2 = _RE_LINIE_PREFIX.sub("", seg, count=1)
        # via abtrennen
        via_parts: list[str] = []
        m = _RE_VIA.search(seg2)
        if m:
            via_str = seg2[m.end():].strip()
            seg2 = seg2[:m.start()].strip()
            via_parts = [v.strip() for v in via_str.split(",") if v.strip()]
        if " - " not in seg2:
            continue
        von, _, nach = seg2.rpartition(" - ")
        von = von.strip()
        nach = nach.strip()
        if not von or not nach:
            continue
        # Trailing Land-Kürzel "(AT)", "(IT)" am Ziel entfernen
        nach = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", nach).strip()
        return (von, nach, via_parts)
    return None


def _clean_station_name(raw: str) -> str:
    """Entfernt typische Suffixe wie '2010', '(Sandbox)' aus dem Stations-Namen."""
    s = re.sub(r"\s+\d{4}\s*$", "", raw).strip()
    return s


def _replace_depot(value: str, station_name: str) -> str:
    """Ersetzt Abstellung/Bw/etc. durch den aktuellen Bahnhofsnamen."""
    if not value:
        return value
    if value.strip().lower() in _INTERNAL_DEPOT_NAMES:
        return station_name
    return value


# „Fernbahn", „Fernverkehr" etc. sind keine Bahnhöfe, sondern STS-Sprech
# für „irgendwo außerhalb der simulierten Gleise". Wenn ein Zug von dort
# kommt oder dorthin fährt, ist die genaue Strecke unbekannt — wir blenden
# den Wert aus, damit auf der ZZA kein „Aus Fernbahn" / „Richtung Fernbahn"
# steht.
_VIRTUAL_EDGE_NAMES = {
    "fernbahn", "fernverkehr",
}


def _is_virtual_edge(value: str) -> bool:
    if not value:
        return False
    return value.strip().lower() in _VIRTUAL_EDGE_NAMES


@dataclass
class ZugRecord:
    """Live state for one train, combined with config data."""
    details: ZugDetails
    fahrplan: Optional[ZugFahrplan] = None
    config_eintrag: Optional[ZugEintrag] = None
    is_new: bool = False
    # Monotone Sekunden-Marke, ab der dieser Zug das Gleis verlassen hat
    # (amgleis-Flanke True→False). 30 s danach blenden wir den Eintrag
    # auf der ZZA aus, damit „durchgefahrene" Züge nicht ewig stehen
    # bleiben, bis der nächste Zugliste-Poll sie offiziell löscht.
    departed_at_monotonic: Optional[float] = None


@dataclass
class DisplayEntry:
    """Ready-to-render data for one train on a ZZA board."""
    zid: int
    name: str
    von: str
    nach: str
    plangleis: str
    verspaetung: int
    ab: Optional[int]   # departure ms since midnight
    an: Optional[int]   # arrival ms since midnight
    via: List[str] = field(default_factory=list)
    is_new: bool = False
    is_terminating: bool = False  # endet hier → "Nicht einsteigen!"
    is_durchfahrt: bool = False   # fährt ohne Halt durch → "Zugdurchfahrt"
    # Ursprünglich geplantes Gleis, wenn der Fdl umgeleitet hat. Leer,
    # wenn der Zug auf seinem geplanten Gleis steht.
    gleis_changed_from: str = ""


class ZugManager:
    """
    Central in-memory state for all active trains.

    Coordinates between live STS data and the static station XML config.
    New trains (not in config) are added to the capture list automatically.
    """

    def __init__(self, config: StationConfig) -> None:
        self._config = config
        self._zuege: Dict[int, ZugRecord] = {}
        self._capture_list: Dict[str, ZugDetails] = {}
        # event_listener(event_type: str, **kwargs) wird vom MainWindow gesetzt
        # und an den Announcer weitergeleitet. Mögliche Events:
        #   "einfahrt"   → name, nach, via, platform, is_terminating
        #                  (gefeuert bei sichtbar 0→1, ≈ 1 min vor Ankunft)
        #   "ankunft"    → name, von, platform, station
        #                  (gefeuert bei amgleis 0→1, Zug steht am Bahnsteig)
        #   "endet_hier" → name, platform
        #   "verspaetung"→ name, nach, minuten, platform
        self.event_listener: Optional[Callable[..., None]] = None

        # Sim-Zeit-Tracking. Wir merken uns den letzten vom Server gemeldeten
        # Sim-ms-Wert zusammen mit dem monotonen Zeitpunkt der Antwort und
        # interpolieren von dort linear weiter — so haben wir auch zwischen
        # zwei <simzeit/>-Anfragen eine sekundengenaue Sim-Uhr für die ZZA.
        self._sim_anchor_ms: Optional[int] = None
        self._sim_anchor_monotonic: Optional[float] = None

    @property
    def _station_display(self) -> str:
        """Anzeige-/Ansagename: bevorzugt aus Config, sonst aus station_name."""
        return (
            self._config.anzeige_name.strip()
            or _clean_station_name(self._config.station_name)
        )

    # ------------------------------------------------------------------
    # Updates from STS signals
    # ------------------------------------------------------------------

    def update_zugliste(self, zl: Dict[int, str]) -> List[int]:
        """
        Sync local state against the server train list.
        Returns ZIDs of trains that are new and need zugdetails requested.
        """
        current_zids = set(zl.keys())
        for zid in list(self._zuege):
            if zid not in current_zids:
                del self._zuege[zid]
        return [zid for zid in current_zids if zid not in self._zuege]

    def update_details(self, zid: int, details: ZugDetails) -> bool:
        """
        Update or create a ZugRecord.
        Returns True if this is a new record or plangleis changed.
        """
        old_record = self._zuege.get(zid)
        old_details = old_record.details if old_record else None

        if zid not in self._zuege:
            record = ZugRecord(details=details)
            # Kommentare/Hinweise immer ins DEBUG-File loggen — STS-
            # Stellwerke schreiben hier oft Wegstrecke und Reise-Ziel hinein,
            # die zur späteren Auswertung nützlich sein können.
            if details.usertext or details.hinweistext:
                logger.debug(
                    "ZugDetails first-seen %s [zid=%d] von=%r nach=%r "
                    "gleis=%r plangleis=%r usertext=%r hinweistext=%r",
                    details.name, zid, details.von, details.nach,
                    details.gleis, details.plangleis,
                    details.usertext, details.hinweistext,
                )
            if details.name in self._config.zuege:
                record.config_eintrag = self._config.zuege[details.name]
            elif _is_dienstfahrt(details.name):
                # Dienst-/Leerfahrten nicht in Capture-Liste aufnehmen.
                logger.debug("Ignoring Dienstfahrt for capture: %s",
                             details.name)
            else:
                record.is_new = True
                self._capture_list[details.name] = details
                logger.info("Captured new train: %s  (von=%r, nach=%r)",
                            details.name, details.von, details.nach)
            self._zuege[zid] = record
            self._emit_state_events(old_details, details)
            return True

        old_plangleis = self._zuege[zid].details.plangleis
        self._zuege[zid].details = details
        # Update config entry in case config was updated since last seen
        if details.name in self._config.zuege:
            self._zuege[zid].config_eintrag = self._config.zuege[details.name]
            self._zuege[zid].is_new = False
            self._capture_list.pop(details.name, None)

        self._emit_state_events(old_details, details)
        self._maybe_seed_sim_time_from_train(self._zuege[zid])
        return old_plangleis != details.plangleis

    def _emit_state_events(self,
                           old: Optional[ZugDetails],
                           new: ZugDetails) -> None:
        """Vergleicht alt/neu und feuert Events für den Announcer."""
        if self.event_listener is None:
            return

        platform = new.gleis or new.plangleis or ""
        cfg = self._config.zuege.get(new.name)
        nach = (cfg.nach if cfg and cfg.nach else new.nach) or ""
        nach = _replace_depot(nach, self._station_display)
        von = (cfg.von if cfg and cfg.von else new.von) or ""
        von = _replace_depot(von, self._station_display)
        via = list(cfg.via) if cfg and cfg.via else []
        via = [_replace_depot(v, self._station_display) for v in via]
        is_terminating = (
            nach.strip().lower() == self._station_display.strip().lower()
            or _is_betriebsbahnhof(nach))

        # Durchfahrt? — aus Fahrplan-Flag "D" für genau diesen Halt ableiten
        is_durchfahrt = False
        record = self._zuege.get(new.zid)
        if record and record.fahrplan:
            for zeile in record.fahrplan.zeilen:
                if zeile.plan == platform or zeile.name == platform:
                    if "D" in (zeile.flags or ""):
                        is_durchfahrt = True
                    break

        # Einfahrt-Ansage (~1 min vor Ankunft): sichtbar 0 → 1
        if (old is None or not old.sichtbar) and new.sichtbar and platform:
            try:
                self.event_listener(
                    "einfahrt", name=new.name, nach=nach, via=via,
                    platform=platform, is_terminating=is_terminating,
                    is_durchfahrt=is_durchfahrt)
            except Exception as exc:
                logger.warning("event_listener einfahrt: %s", exc)

        # Zug steht am Bahnsteig: amgleis 0 → 1
        if old is not None and not old.amgleis and new.amgleis and platform:
            # Ankunft = Reset eines evtl. vorher gemerkten Abfahrt-Markers
            # (selten — z. B. Wendezug, der wieder am gleichen Gleis steht).
            record = self._zuege.get(new.zid)
            if record is not None:
                record.departed_at_monotonic = None
            try:
                if is_terminating:
                    self.event_listener(
                        "endet_hier", name=new.name, platform=platform)
                else:
                    self.event_listener(
                        "ankunft", name=new.name, von=von,
                        platform=platform,
                        station=self._station_display)
            except Exception as exc:
                logger.warning("event_listener ankunft: %s", exc)

        # Zug verlässt das Gleis: amgleis 1 → 0
        # Wir merken uns den Zeitpunkt; die Anzeige-Filter unten blenden
        # den Eintrag _DEPARTED_HIDE_AFTER_S Sekunden später aus.
        if old is not None and old.amgleis and not new.amgleis:
            record = self._zuege.get(new.zid)
            if record is not None:
                record.departed_at_monotonic = time.monotonic()
                logger.debug(
                    "Zug %s [zid=%d] hat Gleis verlassen — wird in %.0fs ausgeblendet",
                    new.name, new.zid, _DEPARTED_HIDE_AFTER_S,
                )
            try:
                self.event_listener(
                    "abfahrt", name=new.name, platform=(old.gleis
                                                        or old.plangleis
                                                        or platform))
            except Exception as exc:
                logger.warning("event_listener abfahrt: %s", exc)

        # Verspätung: 0 → >0 oder signifikante Änderung (≥ 2 min)
        if old is not None:
            old_v = old.verspaetung
            new_v = new.verspaetung
            if new_v > 0 and (old_v == 0 or abs(new_v - old_v) >= 2):
                try:
                    self.event_listener(
                        "verspaetung", name=new.name, nach=nach,
                        minuten=new_v, platform=platform)
                except Exception as exc:
                    logger.warning("event_listener verspaetung: %s", exc)

    def update_fahrplan(self, zid: int, plan: ZugFahrplan) -> None:
        if zid not in self._zuege:
            return
        previous = self._zuege[zid].fahrplan
        self._zuege[zid].fahrplan = plan
        # Mit dem neu eingetroffenen Fahrplan eventuell den Sim-Zeit-Anker
        # aus einem aktuell stehenden Zug ableiten.
        self._maybe_seed_sim_time_from_train(self._zuege[zid])

        # Hinweistexte aus den Fahrplanzeilen einmalig ins Debug-File und
        # in den Auto-Parser füttern, der Capture-Liste pre-populiert.
        if previous is None:
            hints = [
                (z.plan or z.name, z.hinweistext)
                for z in plan.zeilen if z.hinweistext
            ]
            record = self._zuege[zid]
            name = record.details.name
            if hints:
                logger.debug(
                    "ZugFahrplan first-seen %s [zid=%d] hinweistexte=%s",
                    name, zid, hints,
                )
            self._auto_parse_route(record, plan)

    def _auto_parse_route(self,
                          record: ZugRecord,
                          plan: ZugFahrplan) -> None:
        """Versucht aus den hinweistext-Feldern Strecke + Ziel zu parsen.

        Bei Erfolg wird der Capture-Listen-Eintrag mit sauberen Werten
        überschrieben (von/nach/via), so dass der Editor pre-populiert ist
        und die Fahrgast-ZZA bereits korrekte Ziele zeigt.
        """
        # Wenn der Zug schon eine echte Config-Zuordnung hat: nicht überschreiben.
        if record.config_eintrag is not None:
            return

        parsed: Optional[tuple[str, str, list[str]]] = None
        for zeile in plan.zeilen:
            parsed = _parse_hinweistext(zeile.hinweistext or "")
            if parsed:
                break
        # Auch im Zug-eigenen Hinweistext nachsehen
        if parsed is None:
            parsed = _parse_hinweistext(record.details.hinweistext or "")
            if parsed is None:
                parsed = _parse_hinweistext(record.details.usertext or "")

        if parsed is None:
            return

        von, nach, via = parsed
        # Sicherheits-Check: wenn beide Endpunkte stellwerks-intern sind,
        # nicht übernehmen.
        if _is_internal_area(von) and _is_internal_area(nach):
            return

        name = record.details.name
        # Capture-Listen-Eintrag aktualisieren (oder neu anlegen, falls
        # zuvor wegen Dienst-Filter ausgeschlossen).
        new_details = ZugDetails(
            zid=record.details.zid,
            name=name,
            verspaetung=record.details.verspaetung,
            gleis=record.details.gleis,
            plangleis=record.details.plangleis,
            von=von,
            nach=nach,
            sichtbar=record.details.sichtbar,
            amgleis=record.details.amgleis,
            usertext=record.details.usertext,
            hinweistext=record.details.hinweistext,
            via=list(via),
        )
        # Live-Daten im record auch durch geparste Werte ergänzen, damit
        # die Fahrgast-ZZA sofort echte Ziele zeigt — ohne Config-Schreiben.
        record.details.von = von
        record.details.nach = nach
        record.details.via = list(via)

        if not _is_dienstfahrt(name):
            self._capture_list[name] = new_details
            logger.info(
                "Auto-parsed %s: von=%r nach=%r via=%s",
                name, von, nach, via,
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_plangleis_for_display(self, zid: int) -> Optional[str]:
        """
        Returns the track to show on the ZZA.
        Uses the actual live gleis (dispatcher assignment) and falls back to
        plangleis only if gleis is not set.
        """
        record = self._zuege.get(zid)
        if record is None:
            return None
        return record.details.gleis or record.details.plangleis or None

    def get_display_data_for_platform(self, platform: str) -> List[DisplayEntry]:
        """
        Returns display-ready entries for trains that will (or did) stop at
        the given platform, sorted by departure time.

        A train matches if any of these is true:
          - its fahrplan contains a stop where plan or name equals platform
            (covers trains that haven't entered the sim area yet)
          - its current live gleis equals platform (covers dispatcher
            reassignments not yet reflected in fahrplan)
        """
        entries: List[DisplayEntry] = []
        now_mono = time.monotonic()
        for zid, record in self._zuege.items():
            # Dienst-/Leerfahrten gehören nicht auf die Fahrgast-ZZA
            if _is_dienstfahrt(record.details.name):
                continue

            # Zug hat das Gleis vor mehr als _DEPARTED_HIDE_AFTER_S
            # verlassen → ausblenden.
            if (record.departed_at_monotonic is not None
                    and now_mono - record.departed_at_monotonic
                        >= _DEPARTED_HIDE_AFTER_S):
                continue

            ab_time: Optional[int] = None
            an_time: Optional[int] = None
            is_terminating = False
            is_durchfahrt = False

            # Effektives Gleis = live (Fdl-Zuweisung) > Plan. So zeigt sich
            # eine Gleis-Umleitung sofort: der Zug verschwindet vom alten
            # Gleis und erscheint auf dem neuen, statt auf beiden zu stehen.
            effective_gleis = (record.details.gleis
                               or record.details.plangleis or "")
            if effective_gleis != platform:
                continue

            # Zeit-Daten aus dem Fahrplan: bevorzugt die Zeile zum
            # ursprünglichen Plangleis (so bleiben An-/Abfahrt korrekt,
            # auch wenn der Fdl auf ein Gleis ohne eigenen Fahrplan-Eintrag
            # umgeleitet hat). Fallback: Zeile zum effektiven Gleis.
            if record.fahrplan and record.fahrplan.zeilen:
                pgleis = record.details.plangleis or effective_gleis
                target = None
                for zeile in record.fahrplan.zeilen:
                    if zeile.plan == pgleis or zeile.name == pgleis:
                        target = zeile
                        break
                if target is None:
                    for zeile in record.fahrplan.zeilen:
                        if (zeile.plan == effective_gleis
                                or zeile.name == effective_gleis):
                            target = zeile
                            break
                if target is not None:
                    ab_time = target.ab
                    an_time = target.an
                    if "D" in (target.flags or ""):
                        is_durchfahrt = True
                    # Endstation nur, wenn KEINE Abfahrtszeit mehr
                    # eingetragen ist — der Zug rollt also wirklich
                    # nicht weiter. Ein „letzter im Fahrplan"-Halt mit
                    # gesetztem `ab` heißt typischerweise nur, dass der
                    # Zug aus dem Sim-Bereich heraus weiter fährt
                    # (z. B. RE/RB, deren Strecke nach München Hbf
                    # endet, der Zug aber Richtung „Fernbahn" austritt).
                    if not is_durchfahrt and target.ab is None:
                        is_terminating = True

            # Prefer config von/nach for display if available
            cfg = record.config_eintrag
            von = cfg.von if cfg and cfg.von else record.details.von
            nach = cfg.nach if cfg and cfg.nach else record.details.nach

            # Abstellung/Bw → aktueller Bahnhof
            von = _replace_depot(von, self._station_display)
            nach = _replace_depot(nach, self._station_display)

            # „Fernbahn" / „Fernverkehr" sind keine Bahnhöfe — leer setzen,
            # damit kein „Aus Fernbahn" auf der ZZA erscheint. Wenn der Zug
            # nur dorthin „endet", endet er in Wirklichkeit gar nicht — er
            # rollt aus dem Sim-Bereich raus.
            if _is_virtual_edge(von):
                von = ""
            if _is_virtual_edge(nach):
                nach = ""
                is_terminating = False

            # Stellwerks-interne Endpunkte (Pasing AuLiDo, München Süd, …)
            # gehören nicht auf die Fahrgast-ZZA. Wenn die Config kein
            # echtes Reise-Ziel liefert und live-nach intern ist, ausblenden.
            if _is_internal_area(nach):
                continue

            # Endet der Zug am aktuellen Bahnhof (nach == station)?
            if nach.strip().lower() == self._station_display.strip().lower():
                is_terminating = True
            # Fährt der Zug nur weiter ins Betriebswerk/Bbf? Für Fahrgäste
            # ist das Endstation — "Nicht einsteigen!" gilt auch hier.
            elif _is_betriebsbahnhof(nach):
                is_terminating = True

            via = list(cfg.via) if cfg and cfg.via else []
            via = [_replace_depot(v, self._station_display) for v in via]

            # Gleis-Umleitung erkennen: nur wenn beide Werte gesetzt sind
            # und sich unterscheiden (sonst meldet STS oft plangleis="" für
            # neu auftauchende Züge, was wir nicht als Änderung werten).
            orig_plan = record.details.plangleis or ""
            gleis_changed_from = (
                orig_plan if orig_plan and orig_plan != platform else ""
            )

            entries.append(DisplayEntry(
                zid=zid,
                name=record.details.name,
                von=von,
                nach=nach,
                plangleis=platform,
                verspaetung=record.details.verspaetung,
                ab=ab_time,
                an=an_time,
                via=via,
                is_new=record.is_new,
                is_terminating=is_terminating,
                is_durchfahrt=is_durchfahrt,
                gleis_changed_from=gleis_changed_from,
            ))

        # Innerhalb eines Bahnsteigs: terminierende Züge (ab=None) anhand
        # ihrer Ankunftszeit einsortieren, damit „Aus …" am richtigen Platz
        # in der Chronologie erscheint und nicht ans Listen-Ende rutscht.
        def _sort_key(e: DisplayEntry) -> float:
            if e.ab is not None:
                return e.ab
            if e.an is not None:
                return e.an
            return float("inf")
        entries.sort(key=_sort_key)
        return entries

    def get_all_display_data(self, platforms: List[str]) -> List[DisplayEntry]:
        """All entries for the given platforms, sorted by departure time."""
        entries: List[DisplayEntry] = []
        for p in platforms:
            entries.extend(self.get_display_data_for_platform(p))
        entries.sort(key=lambda e: e.ab if e.ab is not None else float("inf"))
        return entries

    def get_all_trains_display(self) -> List[DisplayEntry]:
        """All known trains regardless of platform, sorted by departure time."""
        entries: List[DisplayEntry] = []
        now_mono = time.monotonic()
        for zid, record in self._zuege.items():
            if _is_dienstfahrt(record.details.name):
                continue
            if (record.departed_at_monotonic is not None
                    and now_mono - record.departed_at_monotonic
                        >= _DEPARTED_HIDE_AFTER_S):
                continue
            display_plangleis = self.get_plangleis_for_display(zid) or record.details.plangleis or "?"

            ab_time: Optional[int] = None
            an_time: Optional[int] = None
            is_durchfahrt = False
            if record.fahrplan:
                for zeile in record.fahrplan.zeilen:
                    if zeile.plan == display_plangleis or zeile.name == display_plangleis:
                        ab_time = zeile.ab
                        an_time = zeile.an
                        if "D" in (zeile.flags or ""):
                            is_durchfahrt = True
                        break

            cfg = record.config_eintrag
            von = cfg.von if cfg and cfg.von else record.details.von
            nach = cfg.nach if cfg and cfg.nach else record.details.nach
            von = _replace_depot(von, self._station_display)
            nach = _replace_depot(nach, self._station_display)

            # Virtuelle Sim-Außenränder ausblenden (vgl. get_display_data_for_platform).
            if _is_virtual_edge(von):
                von = ""
            virtual_nach = _is_virtual_edge(nach)
            if virtual_nach:
                nach = ""

            if _is_internal_area(nach):
                continue

            is_terminating = (
                not virtual_nach and
                nach.strip().lower() == self._station_display.strip().lower()
                or _is_betriebsbahnhof(nach)
            )

            via = list(cfg.via) if cfg and cfg.via else []
            via = [_replace_depot(v, self._station_display) for v in via]

            entries.append(DisplayEntry(
                zid=zid,
                name=record.details.name,
                von=von,
                nach=nach,
                plangleis=display_plangleis,
                verspaetung=record.details.verspaetung,
                ab=ab_time,
                an=an_time,
                via=via,
                is_new=record.is_new,
                is_terminating=is_terminating,
                is_durchfahrt=is_durchfahrt,
            ))

        entries.sort(key=lambda e: e.ab if e.ab is not None else float("inf"))
        return entries

    # ------------------------------------------------------------------
    # Sim-Zeit
    # ------------------------------------------------------------------

    def set_sim_time(self, sim_ms: int) -> None:
        """Wird vom MainWindow aufgerufen, sobald <simzeit/> beantwortet wird."""
        self._sim_anchor_ms = sim_ms
        self._sim_anchor_monotonic = time.monotonic()
        logger.debug("Sim-Zeit-Anker gesetzt (Server-Antwort): %d ms", sim_ms)

    def _maybe_seed_sim_time_from_train(self, record: ZugRecord) -> None:
        """
        Fallback-Ableitung der Sim-Zeit, falls der Server nicht auf
        <simzeit/> antwortet (manche PluginTester / ältere STS-Builds).

        Wenn ein Zug gerade mit amgleis=True gemeldet wird und der
        Fahrplan eine Ankunfts- bzw. Abfahrtszeit für sein aktuelles
        Gleis enthält, dann ist sim_now ≈ (an+Verspätung) bis
        (ab+Verspätung). Wir nehmen die Mitte als pragmatischen Schätzer.
        """
        if self._sim_anchor_ms is not None:
            return  # echter Server-Wert hat Vorrang
        d = record.details
        if not d.amgleis:
            return
        plan = record.fahrplan
        if plan is None:
            return
        gleis = d.gleis or d.plangleis
        for zeile in plan.zeilen:
            if zeile.plan != gleis and zeile.name != gleis:
                continue
            base: Optional[int] = None
            if zeile.an is not None and zeile.ab is not None:
                base = (zeile.an + zeile.ab) // 2
            elif zeile.ab is not None:
                base = zeile.ab
            elif zeile.an is not None:
                base = zeile.an
            if base is None:
                continue
            sim_ms = base + (d.verspaetung or 0) * 60_000
            self._sim_anchor_ms = sim_ms % (24 * 3_600_000)
            self._sim_anchor_monotonic = time.monotonic()
            logger.info(
                "Sim-Zeit-Anker per Fallback aus Zug %s am Gleis %s: %d ms",
                d.name, gleis, self._sim_anchor_ms,
            )
            return

    def sim_now_ms(self) -> Optional[int]:
        """
        Aktuell geschätzte Sim-Uhrzeit (ms seit Mitternacht).

        Liefert None, solange noch keine <simzeit/>-Antwort eingetrudelt
        ist — Aufrufer (z. B. die Blink-Logik im Board) müssen das
        akzeptieren und in dem Fall einfach nichts tun.
        """
        if self._sim_anchor_ms is None or self._sim_anchor_monotonic is None:
            return None
        elapsed_ms = int((time.monotonic() - self._sim_anchor_monotonic) * 1000)
        return (self._sim_anchor_ms + elapsed_ms) % (24 * 3_600_000)

    def get_capture_list(self) -> Dict[str, ZugDetails]:
        return dict(self._capture_list)

    def get_all_records(self) -> List[ZugRecord]:
        return list(self._zuege.values())
