from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

CONFIGS_DIR = Path(__file__).parent.parent.parent / "configs"
ENCODING = "utf-8"


@dataclass
class ZugEintrag:
    """One train entry stored in the station config XML.

    Only holds display overrides (von/nach/via). The platform assignment
    always comes from live STS data, never from this config.
    """
    name: str
    von: str = ""
    nach: str = ""
    via: List[str] = field(default_factory=list)


@dataclass
class StationConfig:
    """
    Per-station configuration loaded from / saved to
    configs/[Bahnhofsname].xml (ISO-8859-1).
    """
    station_name: str
    anzeige_name: str = ""   # Echter Bahnhofsname für Anzeige & Ansagen
    bahnsteige: List[str] = field(default_factory=list)
    zuege: Dict[str, ZugEintrag] = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        safe = self.station_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        return CONFIGS_DIR / f"{safe}.xml"

    @classmethod
    def load_or_create(cls, station_name: str) -> StationConfig:
        """Return a StationConfig loaded from disk, or a fresh empty one."""
        cfg = cls(station_name=station_name)
        if cfg.config_path.exists():
            cfg._load()
        return cfg

    def _load(self) -> None:
        try:
            tree = ET.parse(str(self.config_path))
            root = tree.getroot()
        except ET.ParseError as exc:
            logger.error("Failed to parse config %s: %s", self.config_path, exc)
            return

        self.anzeige_name = root.get("anzeige", "")

        for b in root.findall("bahnsteig"):
            name = b.get("name", "")
            if name:
                self.bahnsteige.append(name)

        for z in root.findall("zug"):
            zname = z.get("name", "")
            if not zname:
                continue
            via = [v.get("name", "") for v in z.findall("via") if v.get("name")]
            self.zuege[zname] = ZugEintrag(
                name=zname,
                von=z.get("von", ""),
                nach=z.get("nach", ""),
                via=via,
            )
        logger.info("Loaded config for '%s': %d Bahnsteige, %d Züge",
                    self.station_name, len(self.bahnsteige), len(self.zuege))

    def save(self) -> None:
        """Write the config to disk as ISO-8859-1 XML."""
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        attrs = {"station": self.station_name}
        if self.anzeige_name:
            attrs["anzeige"] = self.anzeige_name
        root = ET.Element("zza", attrs)

        for b_name in sorted(self.bahnsteige):
            ET.SubElement(root, "bahnsteig", name=b_name)

        for zug in sorted(self.zuege.values(), key=lambda z: z.name):
            z_elem = ET.SubElement(
                root, "zug",
                name=zug.name,
                von=zug.von,
                nach=zug.nach,
            )
            for v in zug.via:
                ET.SubElement(z_elem, "via", name=v)

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")

        with open(self.config_path, "wb") as fh:
            fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            tree.write(fh, encoding=ENCODING, xml_declaration=False)

        logger.info("Saved config for '%s' → %s", self.station_name, self.config_path)
