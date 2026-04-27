from __future__ import annotations

import logging
import re
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


@dataclass
class ZugRecord:
    """Live state for one train, combined with config data."""
    details: ZugDetails
    fahrplan: Optional[ZugFahrplan] = None
    config_eintrag: Optional[ZugEintrag] = None
    is_new: bool = False


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
        self._station_display = _clean_station_name(config.station_name)
        # event_listener(event_type: str, **kwargs) wird vom MainWindow gesetzt
        # und an den Announcer weitergeleitet. Mögliche Events:
        #   "einfahrt"   → name, nach, via, platform, is_terminating
        #                  (gefeuert bei sichtbar 0→1, ≈ 1 min vor Ankunft)
        #   "ankunft"    → name, von, platform, station
        #                  (gefeuert bei amgleis 0→1, Zug steht am Bahnsteig)
        #   "endet_hier" → name, platform
        #   "verspaetung"→ name, nach, minuten, platform
        self.event_listener: Optional[Callable[..., None]] = None

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
            if details.name in self._config.zuege:
                record.config_eintrag = self._config.zuege[details.name]
            else:
                record.is_new = True
                self._capture_list[details.name] = details
                logger.info("Captured new train: %s", details.name)
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
            nach.strip().lower() == self._station_display.strip().lower())

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
        if zid in self._zuege:
            self._zuege[zid].fahrplan = plan

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
        for zid, record in self._zuege.items():
            ab_time: Optional[int] = None
            an_time: Optional[int] = None
            matched = False
            is_terminating = False
            is_durchfahrt = False

            # Primary match: fahrplan entry for this platform
            if record.fahrplan and record.fahrplan.zeilen:
                zeilen = record.fahrplan.zeilen
                for idx, zeile in enumerate(zeilen):
                    if zeile.plan == platform or zeile.name == platform:
                        ab_time = zeile.ab
                        an_time = zeile.an
                        matched = True
                        if "D" in (zeile.flags or ""):
                            is_durchfahrt = True
                        # Wenn dieser Halt der letzte im Fahrplan ist
                        # ODER keine Abfahrtszeit gesetzt ist → Endstation
                        # (Durchfahrten haben kein ab → nicht als End behandeln)
                        if not is_durchfahrt and (
                                idx == len(zeilen) - 1 or zeile.ab is None):
                            is_terminating = True
                        break

            # Fallback: dispatcher has put the train on this platform live
            if not matched:
                live = record.details.gleis or record.details.plangleis
                if live == platform:
                    matched = True

            if not matched:
                continue

            # Prefer config von/nach for display if available
            cfg = record.config_eintrag
            von = cfg.von if cfg and cfg.von else record.details.von
            nach = cfg.nach if cfg and cfg.nach else record.details.nach

            # Abstellung/Bw → aktueller Bahnhof
            von = _replace_depot(von, self._station_display)
            nach = _replace_depot(nach, self._station_display)

            # Endet der Zug am aktuellen Bahnhof (nach == station)?
            if nach.strip().lower() == self._station_display.strip().lower():
                is_terminating = True

            via = list(cfg.via) if cfg and cfg.via else []
            via = [_replace_depot(v, self._station_display) for v in via]

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
            ))

        entries.sort(key=lambda e: e.ab if e.ab is not None else float("inf"))
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
        for zid, record in self._zuege.items():
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
            is_terminating = (
                nach.strip().lower() == self._station_display.strip().lower()
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

    def get_capture_list(self) -> Dict[str, ZugDetails]:
        return dict(self._capture_list)

    def get_all_records(self) -> List[ZugRecord]:
        return list(self._zuege.values())
