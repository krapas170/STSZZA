"""
Erzeugt für jede vorhandene Config in configs/ ein GitHub-Issue mit
abhakbarem Testplan. Voraussetzung: gh CLI authentifiziert + im Repo.

Nutzung:
    python scripts/create_test_issues.py            # echtes Anlegen
    python scripts/create_test_issues.py --dry-run  # nur Vorschau
    python scripts/create_test_issues.py --filter Berlin   # nur bestimmte
    python scripts/create_test_issues.py --label stellwerk-test
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def count_zuege(xml_path: Path) -> int:
    try:
        tree = ET.parse(str(xml_path))
        return len(tree.getroot().findall("zug"))
    except Exception:
        return 0


def slug_for_branch(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s.lower()


def build_body(stellwerk: str, n_zuege: int, year: str) -> str:
    """Markdown-Body mit Tasklist."""
    return f"""## Test-Auftrag: **{stellwerk}**

Stellwerk-Plan: {year} · Config: `configs/{stellwerk}.xml` · Voreingestellte Züge: **{n_zuege}**

> Test-Setup: 1 Stunde im **Berufsverkehr** (Mo–Fr, ca. 6:30–8:30 oder 16:00–18:00) spielen
> und während des Spielens jeden Punkt unten abhaken, sobald er verifiziert ist.
> Wenn etwas nicht stimmt: **Punkt nicht abhaken** und stattdessen unten in einem Kommentar
> beschreiben, was kaputt ist (Zugname, was angezeigt wurde, was richtig wäre).
> Sobald alle Punkte abgehakt sind, schließt das Repo das Issue automatisch.

### Vorbereitung
- [ ] STS gestartet, Stellwerk **{stellwerk}** geladen
- [ ] STSZZA-Plugin verbindet sich (Status „Verbunden")
- [ ] Bahnsteig-Auswahl-Dialog erscheint, sinnvolle Vorauswahl gewählt
- [ ] Fahrgast-Ansicht zeigt Boards für die ausgewählten Bahnsteige

### Anzeige (während des Spielens)
- [ ] Züge erscheinen mit korrektem **Zugnamen** (z. B. „RE 7", „ICE 884")
- [ ] **Ziel** („nach …") stimmt für die meisten Züge
- [ ] **Herkunft** („Aus …") stimmt für die meisten Züge
- [ ] **Via**-Stationen sind plausibel (max. 3, keine internen Bereiche wie „Stammstrecke")
- [ ] **Plangleis** entspricht dem, was STS anzeigt (kommt nicht aus der Config!)
- [ ] **Verspätungen** werden korrekt angezeigt (`+5'`)
- [ ] **Gleisänderung** wird übernommen (Zug wechselt vom alten aufs neue Gleis)
- [ ] Im weißen Info-Banner steht „Gleisänderung — sonst Gleis X" wenn Fdl umleitet
- [ ] **Endet hier**-Züge werden als „Nicht einsteigen!" gekennzeichnet
- [ ] **Durchfahrten** zeigen „Zugdurchfahrt"
- [ ] Abgefahrene Züge verschwinden nach ~30 s automatisch

### Ansagen
- [ ] **Einfahrt**-Ansage kommt rechtzeitig (~1 min vor Ankunft)
- [ ] **Einfahrt**-Ansage erwähnt Verspätung, falls vorhanden
- [ ] **Bitte einsteigen**-Ansage kommt ~30 s vor Abfahrt
- [ ] **Gleisänderungs**-Ansage kommt, wenn der Fdl umleitet
- [ ] **Verspätungs**-Update wird angesagt, wenn sich Verspätung ändert
- [ ] **Endet hier**/Durchfahrt-Ansagen werden korrekt unterschieden
- [ ] Werkzeuge → Ansage-Warteschlange zeigt aktuelle/wartende Ansagen
- [ ] Sprache klingt natürlich (keine Buchstaben „I-C-E" — sondern „Intercity-Express")

### Capture-Liste & Editor
- [ ] Werkzeuge → Analyse & Editor öffnet sich
- [ ] Neue, vom Plugin live erfasste Züge tauchen in der Liste auf
- [ ] „Dauerhaft speichern" schreibt Einträge zurück in `configs/{stellwerk}.xml`
- [ ] Stellwerks-interne Quellen/Ziele („Stammstrecke", „Aus Fernbahn") werden nicht angezeigt
- [ ] Dienstfahrten (LRV, DPN, Lr, Lt …) tauchen NICHT auf der Fahrgast-ZZA auf

### Stabilität
- [ ] Plugin läuft volle Stunde ohne Crash
- [ ] Keine duplizierten Züge (gleicher Name auf mehreren Boards)
- [ ] Beim Beenden korrekt heruntergefahren (kein hängender Worker-Thread)

---

**Falsch gelaufen?** Liste hier kurz auf, dann lass den Punkt offen:

```
- Zug XYZ: Anzeige sagt "nach Berlin", richtig wäre "nach Hamburg"
- Ansage Einfahrt RE 7: kam erst 10 s vor Ankunft, sollte ~60 s sein
```
"""


def issue_exists(title: str, label: str) -> bool:
    """Prüft, ob ein Issue mit gleichem Titel und Label schon existiert."""
    try:
        out = subprocess.run(
            ["gh", "issue", "list",
             "--state", "all",
             "--label", label,
             "--search", title,
             "--json", "title",
             "--limit", "200"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout
        items = json.loads(out)
        for it in items:
            if it.get("title", "").strip() == title.strip():
                return True
    except Exception as exc:
        print(f"  ! gh issue list failed: {exc}", file=sys.stderr)
    return False


def create_issue(title: str, body: str, labels: List[str], dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry] {title}")
        return True
    cmd = ["gh", "issue", "create",
           "--title", title,
           "--body", body]
    for lab in labels:
        cmd += ["--label", lab]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True,
                                text=True, encoding="utf-8")
        url = (result.stdout or "").strip().splitlines()[-1]
        print(f"  + {title}  →  {url}")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  ! Konnte Issue nicht anlegen: {title}", file=sys.stderr)
        print(f"    stderr: {exc.stderr.strip()}", file=sys.stderr)
        return False


def ensure_label(label: str, color: str, description: str) -> None:
    """Idempotent: Label anlegen wenn nicht vorhanden."""
    try:
        subprocess.run(
            ["gh", "label", "create", label,
             "--color", color, "--description", description, "--force"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
    except subprocess.CalledProcessError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--filter", default="",
                    help="Nur Stellwerke, deren Name diesen Substring enthält")
    ap.add_argument("--label", default="stellwerk-test")
    ap.add_argument("--year", default="2024")
    ap.add_argument("--configs-dir", default="configs")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    cfg_dir = project_root / args.configs_dir
    if not cfg_dir.exists():
        print(f"configs/ fehlt: {cfg_dir}", file=sys.stderr)
        return 2

    xmls = sorted(cfg_dir.glob("*.xml"))
    if args.filter:
        flt = args.filter.lower()
        xmls = [p for p in xmls if flt in p.stem.lower()]

    print(f"Configs gefunden: {len(xmls)}")
    if not xmls:
        return 0

    if not args.dry_run:
        ensure_label(args.label, "1f6feb",
                     "Test-Auftrag für ein STS-Stellwerk")

    created = 0
    skipped = 0
    for xml in xmls:
        stellwerk = xml.stem
        n = count_zuege(xml)
        title = f"Stellwerk-Test: {stellwerk}"
        if not args.dry_run and issue_exists(title, args.label):
            print(f"  = {stellwerk:<40s} (Issue existiert schon)")
            skipped += 1
            continue
        body = build_body(stellwerk, n, args.year)
        if create_issue(title, body, [args.label], args.dry_run):
            created += 1

    print()
    print(f"Erzeugt: {created}    Übersprungen (existiert): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
