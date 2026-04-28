"""
Parst alle DB-Kursbuch-PDFs in .dev/Kursbuch DB <Jahr>/.../dn/*.pdf und
baut einen JSON-Index der Form:

    {
      "<train_key>": {
        "name": "RB60 76569",
        "stations": ["Dresden Hbf", "Dresden Mitte", ..., "Görlitz"],
        "kbs": ["230"],
        "sources": ["KB230_H_Taeglich_G24112023....pdf"],
      },
      ...
    }

Verwendet pdfplumber mit layout=True, weil die Kursbuch-PDFs Mehrspalten-
Tabellen sind, die pypdf in falsche Reihenfolge bringt. Die Layout-Variante
erhält die spatiale Struktur und macht Spaltenerkennung trivial.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

# Linien-Tokens, die wir als Zug-Gattung anerkennen
LINE_TOKENS = (
    "RE", "RB", "R", "S", "IRE", "IC", "ICE", "EC", "ECE",
    "RJ", "RJX", "NJ", "EN", "TGV", "MEX", "FLX", "FEX",
    "BRB", "BOB", "BLB", "BEX", "ALX", "VIA", "GoA", "DLB", "WFB",
    "ALEX", "ARZ", "DPN", "STR", "AKN",
)
RE_LINE = re.compile(
    r"^(?:" + "|".join(re.escape(t) for t in LINE_TOKENS) + r")\d{1,3}[A-Za-z]?$"
)
RE_NUMBER = re.compile(r"^\d{3,6}$")


def fix_glyphs(s: str) -> str:
    """Räumt typische pdfplumber-Glyph-Artefakte auf."""
    return re.sub(r"\(cid:\d+\)", "", s).strip()


def parse_train_header(zug_line: str, num_line: str) -> List[str]:
    """
    Aus zwei Zeilen:
        "Zug RB60 RB60 RE2 RE1 RB60 ..."
        "    76569 76501 20841 5671 76505 ..."
    eine Liste von Zugnamen ["RB60 76569", "RB60 76501", ...] erzeugen.
    """
    # Tokenisieren
    tokens = zug_line.split()
    # 'Zug' am Anfang weg
    if tokens and tokens[0].lower() == "zug":
        tokens = tokens[1:]
    nums = num_line.split()
    # Linien können „RE 7" als zwei Tokens sein → zusammenführen
    lines: List[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        # Reine Linien-Buchstaben (RE, RB, IC, …) gefolgt von Nummern
        if t in LINE_TOKENS and i + 1 < len(tokens) and re.fullmatch(r"\d{1,3}[A-Za-z]?", tokens[i + 1]):
            lines.append(t + tokens[i + 1])
            i += 2
            continue
        # „RE7" zusammen
        if RE_LINE.match(t):
            lines.append(t)
            i += 1
            continue
        # alles andere überspringen
        i += 1
    # Mit Nummern paaren
    out: List[str] = []
    n = min(len(lines), len(nums))
    for j in range(n):
        if RE_NUMBER.match(nums[j]):
            out.append(f"{lines[j]} {nums[j]}")
    return out


# Stationszeile beginnt typischerweise mit (optionaler) Kilometerangabe und
# einem Stationsnamen, danach folgen Zeit-Marker („j HH MM" / „| HH MM" / „a"
# / Ziffern). Wir extrahieren den führenden Stationstext.
RE_STATION_LINE = re.compile(
    r"^"
    r"(?:\d+(?:[,.]\d+)?\s*)?"      # optional km
    r"(?P<station>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß \.\-/\(\)]*?)"
    r"\s*(?:[j|]\s+\d|\d\s+\d{2}|\(cid|a\b|—|–|\s*\d{1,2}\s+\d{2})"
)
# Kürzer: alles vor der ersten Zeit/„j"/„a" als Station nehmen.
RE_STATION_PREFIX = re.compile(
    r"^"
    r"(?:\d+(?:[,.]\d+)?\s*)?"
    r"(?P<station>[A-Za-zÄÖÜäöüß\.][A-Za-zÄÖÜäöüß \.\-/\(\)’']*?)"
    r"(?=\s+(?:[j|]\s+\d|[ja]\s|\d\s+\d{2}|\(cid|—|–))"
)


def extract_station(line: str) -> Optional[str]:
    """Liefert den Stationsnamen am Zeilenanfang oder None."""
    line = fix_glyphs(line)
    if not line.strip():
        return None
    m = RE_STATION_PREFIX.match(line)
    if not m:
        return None
    s = m.group("station").strip()
    # Trailing Strecken-Hint /L51817 entfernen
    s = re.sub(r"\s*/L\d+\s*$", "", s).strip()
    # Nicht-Stations-Zeilen: Tabellenkopf, Streckenkopf, Bemerkungen
    bad = ("zug", "von", "nach", "km", "kursbuch", "alle angaben",
           "werktags", "betriebliche", "alle züge")
    if s.lower().startswith(bad):
        return None
    if len(s) < 2 or len(s) > 60:
        return None
    return s


def parse_pdf(path: Path) -> List[Dict]:
    """
    Liefert eine Liste von Zug-Records aus einer PDF.
    Logik: pro Block "Zug…von…nach" suchen. Die Layout-Extraktion legt
    die Spalten zeilengenau ab, daher genügt eine Zeilenautomat:
      - Zeile mit „Zug" beginnt Block → nächste Zeile = Zugnummern
      - Folgende Zeilen bis zu Tabellenende (oder neuer „Zug"-Header) =
        Stationsliste
    """
    try:
        pdf = pdfplumber.open(str(path))
    except Exception as exc:
        print(f"  ! open fail {path.name}: {exc}", file=sys.stderr)
        return []

    # KBS-Nummer aus Dateinamen
    kbs = ""
    m = re.match(r"(?:KB)?(\d{2,4}(?:_\d+)?)", path.name)
    if m:
        kbs = m.group(1).replace("_", ".")

    records: List[Dict] = []

    try:
        for page in pdf.pages:
            try:
                text = page.extract_text(layout=True) or ""
            except Exception:
                continue
            lines = [fix_glyphs(l).rstrip() for l in text.splitlines()]

            i = 0
            while i < len(lines):
                line = lines[i]
                stripped = line.lstrip()
                if not stripped.startswith("Zug "):
                    i += 1
                    continue
                # Header: aktuelle Zeile + nächste (Nummern) + ggf. übernächste (Modifier)
                num_line = lines[i + 1] if i + 1 < len(lines) else ""
                trains = parse_train_header(stripped, num_line)
                i += 2
                # Skip Modifier-Zeilen (Mo-Fr / Sa,So / 1 / 2 / f2.*)
                while i < len(lines):
                    s = lines[i].strip()
                    if not s:
                        i += 1
                        continue
                    # Stationszeile? Dann break
                    if extract_station(lines[i]):
                        break
                    # Sonst Modifier — überspringen
                    if re.fullmatch(
                        r"(?:f\d?\.?\*?|f|Mo-Fr|Mo-Sa|Mo-So|Sa|So|Sa,So|"
                        r"\d{1,2}|[a-z]\d?|km|von|[\(\)\[\]\.\*†‡a-z\s/-]*)",
                        s, flags=re.IGNORECASE,
                    ):
                        i += 1
                        continue
                    # Unbekannt — könnte ne kaputte Stationszeile sein
                    break

                # Stationsliste sammeln
                stations: List[str] = []
                while i < len(lines):
                    s = lines[i].strip()
                    if not s:
                        i += 1
                        continue
                    if s.startswith("Zug "):
                        break
                    if s.lower().startswith("nach"):
                        i += 1
                        # weiter — nach „nach" kommt manchmal noch eine Bahnhofszeile
                        continue
                    st = extract_station(lines[i])
                    if st:
                        if st not in stations:
                            stations.append(st)
                        i += 1
                        continue
                    # Streckenkopf am Ende: "Dresden Hbf - Görlitz   RE 1   230"
                    if " - " in s and re.search(r"\d{2,4}", s):
                        i += 1
                        break
                    i += 1

                if trains and len(stations) >= 2:
                    for tname in trains:
                        records.append({
                            "name": tname,
                            "stations": stations,
                            "kbs": kbs,
                            "src": path.name,
                        })
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return records


def merge_records(all_records: List[Dict]) -> Dict[str, Dict]:
    """Mehrere Funde desselben Zugnamens zu einem Eintrag zusammenführen."""
    merged: Dict[str, Dict] = {}
    for r in all_records:
        key = re.sub(r"\s+", "_", r["name"])
        if key not in merged:
            merged[key] = {
                "name": r["name"],
                "stations": list(r["stations"]),
                "kbs": [r["kbs"]] if r["kbs"] else [],
                "sources": [r["src"]],
            }
        else:
            existing = merged[key]
            for s in r["stations"]:
                if s not in existing["stations"]:
                    existing["stations"].append(s)
            if r["kbs"] and r["kbs"] not in existing["kbs"]:
                existing["kbs"].append(r["kbs"])
            if r["src"] not in existing["sources"]:
                existing["sources"].append(r["src"])
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2024")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out",
                    default=".dev/cache/kursbuch_{year}.json")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    pdf_root = project_root / ".dev" / f"Kursbuch DB {args.year}"
    if not pdf_root.exists():
        print(f"Verzeichnis fehlt: {pdf_root}", file=sys.stderr)
        return 2

    pdfs = sorted([p for p in pdf_root.rglob("*.pdf") if p.stat().st_size > 1000])
    print(f"Gefunden: {len(pdfs)} PDFs in {pdf_root}", flush=True)
    if args.limit:
        pdfs = pdfs[: args.limit]
        print(f"Limitiert auf {len(pdfs)}", flush=True)

    all_records: List[Dict] = []
    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"Parallele Worker: {workers}", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(parse_pdf, pdf): pdf for pdf in pdfs}
        done_count = 0
        for fut in as_completed(futures):
            done_count += 1
            try:
                recs = fut.result()
            except Exception as exc:
                print(f"  ! {futures[fut].name}: {exc}", file=sys.stderr)
                continue
            all_records.extend(recs)
            if done_count % 100 == 0 or done_count == len(pdfs):
                print(f"  [{done_count}/{len(pdfs)}] +{len(recs)} Records (total {len(all_records)})", flush=True)

    print(f"Roh-Records: {len(all_records)}", flush=True)
    merged = merge_records(all_records)
    print(f"Eindeutige Züge nach Merge: {len(merged)}", flush=True)

    out_path = project_root / args.out.format(year=args.year)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Geschrieben: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
