"""
Liest den Kursbuch-Index (kursbuch_<jahr>.json) und schreibt für jeden
in scripts/stellwerke_<jahr>.txt aufgeführten Stellwerksnamen eine
configs/<Name>.xml mit `<zug>`-Einträgen.

Match-Logik:
  STS-Stellwerksname  → station_aliases.json → Liste DB-Stationsnamen
                     → fuzzy substring match in der Halteliste jedes Zuges
                     → Treffer ⇒ <zug name=… von=… nach=… via=…/>

Hat ein Stellwerk keinen expliziten Alias, fällt das Skript auf einen
Stamm-Namen zurück (Klammern/Suffixe gestrippt).

via-Strategie: alle Zwischenhalte zwischen dem Treffer und Endpunkten
werden auf bis zu 3 „große" Stationen reduziert (Halte mit „Hbf",
gefolgt von alphabetischer Sortierung). So bleibt die Anzeige lesbar.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

# Konsole auf UTF-8, falls Windows mit cp1252 default arbeitet.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET


# ── Helpers ─────────────────────────────────────────────────────────────────

def slug(s: str) -> str:
    """Lowercase + Diakritika-frei + nur a-z0-9 — für Fuzzy-Match."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def stem_stellwerk(name: str) -> List[str]:
    """STS-Stellwerksname → mögliche Stamm-Suchstrings.

    Beispiel:
      „Berlin Hbf (Stadtbahn) 2024" → [„Berlin Hbf", „Berlin"]
      „Bietigheim/Vaihingen (E) 2024" → [„Bietigheim", „Vaihingen"]
    """
    s = name
    # Jahres-Suffix entfernen
    s = re.sub(r"\s*(?:20\d{2}|24)\s*$", "", s).strip()
    # Klammer-Inhalt entfernen
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s).strip()
    # An „/" oder „-" splitten → mehrere Stämme
    parts = re.split(r"\s*[/]\s*", s)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out or [s]


def normalize_station_name(s: str) -> str:
    """Räumt Eigenheiten der Kursbuch-Stationsnamen auf."""
    s = s.strip()
    # Doppelte Leerzeichen
    s = re.sub(r"\s+", " ", s)
    return s


def is_big_station(s: str) -> bool:
    """Ob die Station als „großer" Knoten taugt für via-Auswahl."""
    low = s.lower()
    return ("hbf" in low or "hauptbahnhof" in low
            or "centraal" in low or "central" in low)


# ── Match ────────────────────────────────────────────────────────────────────

def find_index_cached(station_slugs: List[str],
                      target_slugs: List[str]) -> Optional[int]:
    """Match auf vorberechneten Slugs."""
    for i, st_slug in enumerate(station_slugs):
        for ts in target_slugs:
            if ts in st_slug or st_slug in ts:
                return i
    return None


def precompute_slugs(index: Dict[str, dict]) -> None:
    """Berechnet pro Train einmalig die Slug-Liste der Halte."""
    for tr in index.values():
        tr["_slugs"] = [slug(s) for s in tr["stations"]]


def trains_for_stellwerk(
    index: Dict[str, dict],
    targets: List[str],
) -> List[Tuple[dict, int]]:
    """Liefert (train_record, index_in_stations) für alle Treffer."""
    target_slugs = [slug(t) for t in targets if t and slug(t)]
    if not target_slugs:
        return []
    out: List[Tuple[dict, int]] = []
    for tr in index.values():
        idx = find_index_cached(tr["_slugs"], target_slugs)
        if idx is not None:
            out.append((tr, idx))
    return out


def via_for_train(
    stations: List[str],
    hit_idx: int,
    von: str,
    nach: str,
    max_via: int = 3,
) -> List[str]:
    """Wählt bis zu `max_via` Zwischenhalte für die Anzeige.

    Drei Fälle:
      1) Stellwerk = letzter Halt → via = ankommende Strecke (von → uns),
         d. h. Halte zwischen Start und Stellwerk.
      2) Stellwerk = erster Halt → via = abfahrende Strecke (uns → nach),
         d. h. Halte zwischen Stellwerk und Endpunkt.
      3) Stellwerk mittendrin → via = abfahrende Strecke (uns → nach).

    In allen Fällen werden große Bahnhöfe (Hbf) bevorzugt; die ersten
    `max_via` Treffer kommen ins via.
    """
    last_idx = len(stations) - 1
    if hit_idx >= last_idx:
        # Endpunkt — via = was vor dem Stellwerk lag (Fahrtrichtung
        # einfach umgekehrt, damit Reisende sehen, woher er kommt).
        between = stations[1:hit_idx]
        # Reihenfolge umkehren, damit die Anzeige in Richtung „kommt aus …"
        # die nächstgelegene Station zuerst nennt — wirkt natürlicher.
        between = list(reversed(between))
    else:
        # Stellwerk in der Mitte ODER Stellwerk = erster Halt
        between = stations[hit_idx + 1:last_idx]

    between = [s for s in between if s and s != von and s != nach]

    big = [s for s in between if is_big_station(s)]
    rest = [s for s in between if s not in big]
    return (big + rest)[:max_via]


# ── Main ─────────────────────────────────────────────────────────────────────

def write_config(out_dir: Path, stellwerk: str, entries: List[dict]) -> Path:
    """Schreibt configs/<stellwerk>.xml im Format von station_config.py."""
    safe = stellwerk.replace("/", "_").replace("\\", "_").replace(":", "_")
    out_path = out_dir / f"{safe}.xml"

    root = ET.Element("zza", {"station": stellwerk})

    # Bahnsteige werden bewusst NICHT vorbelegt — kommt vom User beim
    # ersten Plugin-Lauf via Dialog.

    for e in sorted(entries, key=lambda x: x["name"]):
        z = ET.SubElement(
            root, "zug",
            name=e["name"],
            von=e["von"],
            nach=e["nach"],
        )
        for v in e["via"]:
            ET.SubElement(z, "via", name=v)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(fh, encoding="utf-8", xml_declaration=False)
    return out_path


def load_stellwerke(path: Path) -> List[str]:
    out: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2024")
    ap.add_argument("--stellwerke",
                    default="scripts/stellwerke_{year}.txt")
    ap.add_argument("--aliases",
                    default="scripts/station_aliases.json")
    ap.add_argument("--index",
                    default=".dev/cache/kursbuch_{year}.json")
    ap.add_argument("--out-dir", default="configs")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nur Bericht ausgeben, nichts schreiben")
    ap.add_argument("--min-trains", type=int, default=1,
                    help="Stellwerke mit weniger Treffern überspringen")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    stellwerke = load_stellwerke(
        project_root / args.stellwerke.format(year=args.year))
    aliases = json.loads((project_root / args.aliases).read_text(encoding="utf-8"))
    index = json.loads((project_root /
                        args.index.format(year=args.year)).read_text(encoding="utf-8"))

    print(f"Stellwerke: {len(stellwerke)}")
    print(f"Züge im Index: {len(index)}")
    print("Indexiere Slugs …", flush=True)
    precompute_slugs(index)
    print("Fertig.", flush=True)
    print()

    out_dir = project_root / args.out_dir
    written = 0
    skipped = 0
    report_lines: List[str] = []

    for stellwerk in stellwerke:
        targets = aliases.get(stellwerk)
        if not targets:
            targets = stem_stellwerk(stellwerk)

        hits = trains_for_stellwerk(index, targets)
        if len(hits) < args.min_trains:
            report_lines.append(
                f"  [--] {stellwerk:<40s} 0 Treffer (Aliase: {targets})")
            skipped += 1
            continue

        entries: List[dict] = []
        for tr, hit_idx in hits:
            stations = tr["stations"]
            if len(stations) < 2:
                continue
            von = stations[0]
            nach = stations[-1]
            via = via_for_train(stations, hit_idx, von, nach)
            entries.append({
                "name": tr["name"],
                "von": normalize_station_name(von),
                "nach": normalize_station_name(nach),
                "via": [normalize_station_name(v) for v in via],
            })

        if not args.dry_run:
            path = write_config(out_dir, stellwerk, entries)
            report_lines.append(
                f"  [OK] {stellwerk:<40s} {len(entries):>4d} Züge → {path.name}")
        else:
            report_lines.append(
                f"  [OK] {stellwerk:<40s} {len(entries):>4d} Züge (dry-run)")
        written += 1

    print("\n".join(report_lines))
    print()
    print(f"Geschrieben: {written}    Übersprungen (0 Treffer): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
