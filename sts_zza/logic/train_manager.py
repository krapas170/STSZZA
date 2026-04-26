from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config.station_config import StationConfig, ZugEintrag
from ..protocol.models import ZugDetails, ZugFahrplan

logger = logging.getLogger(__name__)


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
    is_new: bool = False


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
        if zid not in self._zuege:
            record = ZugRecord(details=details)
            if details.name in self._config.zuege:
                record.config_eintrag = self._config.zuege[details.name]
            else:
                record.is_new = True
                self._capture_list[details.name] = details
                logger.info("Captured new train: %s", details.name)
            self._zuege[zid] = record
            return True

        old_plangleis = self._zuege[zid].details.plangleis
        self._zuege[zid].details = details
        # Update config entry in case config was updated since last seen
        if details.name in self._config.zuege:
            self._zuege[zid].config_eintrag = self._config.zuege[details.name]
            self._zuege[zid].is_new = False
            self._capture_list.pop(details.name, None)
        return old_plangleis != details.plangleis

    def update_fahrplan(self, zid: int, plan: ZugFahrplan) -> None:
        if zid in self._zuege:
            self._zuege[zid].fahrplan = plan

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_plangleis_for_display(self, zid: int) -> Optional[str]:
        """
        Returns the planned track for ZZA display.
        Config plangleis takes priority over live plangleis so rerouted
        trains still show their originally scheduled platform.
        """
        record = self._zuege.get(zid)
        if record is None:
            return None
        if record.config_eintrag and record.config_eintrag.plangleis:
            return record.config_eintrag.plangleis
        return record.details.plangleis or None

    def get_display_data_for_platform(self, platform: str) -> List[DisplayEntry]:
        """
        Returns display-ready entries for trains scheduled to stop at platform,
        sorted by departure time (trains without a time come last).
        """
        entries: List[DisplayEntry] = []
        for zid, record in self._zuege.items():
            display_plangleis = self.get_plangleis_for_display(zid)
            if display_plangleis != platform:
                continue

            ab_time: Optional[int] = None
            an_time: Optional[int] = None
            if record.fahrplan:
                for zeile in record.fahrplan.zeilen:
                    if zeile.plan == platform or zeile.name == platform:
                        ab_time = zeile.ab
                        an_time = zeile.an
                        break

            # Prefer config von/nach for display if available
            cfg = record.config_eintrag
            von = cfg.von if cfg and cfg.von else record.details.von
            nach = cfg.nach if cfg and cfg.nach else record.details.nach

            entries.append(DisplayEntry(
                zid=zid,
                name=record.details.name,
                von=von,
                nach=nach,
                plangleis=display_plangleis,
                verspaetung=record.details.verspaetung,
                ab=ab_time,
                an=an_time,
                is_new=record.is_new,
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
            if record.fahrplan:
                for zeile in record.fahrplan.zeilen:
                    if zeile.plan == display_plangleis or zeile.name == display_plangleis:
                        ab_time = zeile.ab
                        an_time = zeile.an
                        break

            cfg = record.config_eintrag
            von = cfg.von if cfg and cfg.von else record.details.von
            nach = cfg.nach if cfg and cfg.nach else record.details.nach

            entries.append(DisplayEntry(
                zid=zid,
                name=record.details.name,
                von=von,
                nach=nach,
                plangleis=display_plangleis,
                verspaetung=record.details.verspaetung,
                ab=ab_time,
                an=an_time,
                is_new=record.is_new,
            ))

        entries.sort(key=lambda e: e.ab if e.ab is not None else float("inf"))
        return entries

    def get_capture_list(self) -> Dict[str, ZugDetails]:
        return dict(self._capture_list)

    def get_all_records(self) -> List[ZugRecord]:
        return list(self._zuege.values())
