from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set


class EreignisArt(str, Enum):
    EINFAHRT = "einfahrt"
    AUSFAHRT = "ausfahrt"
    ANKUNFT = "ankunft"
    ABFAHRT = "abfahrt"
    ROTHALT = "rothalt"
    WURDEGRUEN = "wurdegruen"
    FLUEGELN = "fluegeln"
    KUPPELN = "kuppeln"


@dataclass
class AnlagenInfo:
    name: str
    aid: int = 0
    simbuild: str = ""
    region: str = ""
    online: bool = False


@dataclass
class BahnsteigInfo:
    name: str
    nachbarn: Set[str] = field(default_factory=set)
    haltepunkt: bool = False


@dataclass
class ZugDetails:
    zid: int
    name: str
    verspaetung: int = 0
    gleis: str = ""
    plangleis: str = ""
    von: str = ""
    nach: str = ""
    sichtbar: bool = True
    amgleis: bool = False
    usertext: str = ""
    hinweistext: str = ""


@dataclass
class FahrplanZeile:
    plan: str = ""
    name: str = ""
    an: Optional[int] = None
    ab: Optional[int] = None
    flags: str = ""
    hinweistext: str = ""


@dataclass
class ZugFahrplan:
    zid: int
    zeilen: List[FahrplanZeile] = field(default_factory=list)
