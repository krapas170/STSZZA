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

        new_zids = [zid for zid in current_zids if zid not in self._zuege]
        return new_zids

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
        return old_plangleis != details.plangleis

    def update_fahrplan(self, zid: int, plan: ZugFahrplan) -> None:
        if zid in self._zuege:
            self._zuege[zid].fahrplan = plan

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_plangleis_for_display(self, zid: int) -> Optional[str]:
        """
        Returns the planned track to show on the ZZA board.

        Priority: XML-config plangleis (stable even after in-game rerouting)
        > live plangleis from STS.
        """
        record = self._zuege.get(zid)
        if record is None:
            return None
        if record.config_eintrag and record.config_eintrag.plangleis:
            return record.config_eintrag.plangleis
        return record.details.plangleis or None

    def get_capture_list(self) -> Dict[str, ZugDetails]:
        return dict(self._capture_list)

    def get_trains_for_platform(self, platform_name: str) -> List[ZugRecord]:
        """All trains whose display plangleis matches platform_name."""
        result = []
        for zid, record in self._zuege.items():
            if self.get_plangleis_for_display(zid) == platform_name:
                result.append(record)
        return result

    def get_all_records(self) -> List[ZugRecord]:
        return list(self._zuege.values())
