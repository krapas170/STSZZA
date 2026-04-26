# STS ZZA — Zugzielanzeiger-Plugin für StellwerkSim

Ein Python-Plugin für [StellwerkSim](https://www.stellwerksim.de/) (STS), das digitale Zugzielanzeiger (ZZA) darstellt — ähnlich den Abfahrtstafeln an echten Bahnhöfen.

Das Plugin lernt automatisch neue Züge kennen: Unbekannte Züge werden in einer Capture-Liste gesammelt und können direkt im Programm vervollständigt und gespeichert werden.

---

## Features

| Feature | Beschreibung |
|---|---|
| **Fahrgast-Ansicht** | Grafische ZZA-Optik (klassische Abfahrtstafel) |
| **Fdl-Ansicht** | Strukturierte Tabelle für den Fahrdienstleiter |
| **Lernende Konfiguration** | Unbekannte Züge werden automatisch erkannt und in der Capture-Liste gesammelt |
| **Plan-Gleis-Logik** | Zeigt das Soll-Gleis aus der Config — auch wenn der Spieler den Zug umgeleitet hat |
| **Analyse & Editor** | Fehlende Züge direkt im Programm bearbeiten und dauerhaft speichern |
| **Auto-Config** | Beim ersten Start wird automatisch eine `configs/[Bahnhofsname].xml` angelegt |

---

## Voraussetzungen

- Python **3.10** oder neuer
- StellwerkSim läuft auf demselben Rechner (oder im lokalen Netz)
- PyQt6 (wird über `requirements.txt` installiert)

---

## Installation

```bash
git clone https://github.com/krapas170/STSZZA.git
cd STSZZA
pip install -r requirements.txt
```

---

## Starten

1. StellwerkSim starten und eine Anlage laden
2. Plugin starten:

```bash
python main.py
```

Das Programm verbindet sich automatisch auf `localhost:3691`.  
Beim ersten Start erscheint ein Dialog zur Bahnsteig-Auswahl, danach wird die Konfigurationsdatei angelegt:

```
configs/[Bahnhofsname].xml
```

---

## Konfigurationsdateien

Die XML-Dateien liegen in `configs/` (ISO-8859-1-Kodierung):

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<zza station="Musterstadt">

  <!-- Anzuzeigende Bahnsteige -->
  <bahnsteig name="1" />
  <bahnsteig name="2" />

  <!-- Bekannte Züge -->
  <!-- plangleis = ursprüngliches Soll-Gleis (bleibt auch bei Umleitung) -->
  <zug name="IC 100" von="A-Stadt" nach="B-Hausen" plangleis="1">
    <via name="Zwischenhalt" />
  </zug>

</zza>
```

Neue Züge, die noch nicht in der Config stehen, erscheinen im **Analyse & Editor** (`Werkzeuge → Analyse & Editor`). Dort können Von/Nach/Via ergänzt und per Knopfdruck dauerhaft gespeichert werden.

---

## Projektstruktur

```
STSZZA/
├── main.py                      # Einstiegspunkt
├── requirements.txt
├── sts_zza/
│   ├── protocol/
│   │   ├── models.py            # Datenklassen (ZugDetails, BahnsteigInfo, …)
│   │   ├── parser.py            # Inkrementeller XML-Stream-Parser
│   │   └── client.py            # STSClient — TCP-Verbindung + Qt-Signals
│   ├── config/
│   │   └── station_config.py    # Bahnhofs-XML lesen / schreiben
│   ├── logic/
│   │   └── train_manager.py     # ZugManager, Capture-Liste, Plan-Gleis-Logik
│   └── gui/
│       ├── app.py               # QApplication + Startlogik
│       ├── main_window.py       # Hauptfenster
│       └── platform_selector.py # Bahnsteig-Auswahl-Dialog
├── configs/                     # Bahnhofs-Konfigurationen (nicht im Git)
└── tests/                       # Unit-Tests
```

---

## Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## STS-Protokoll

Das Plugin kommuniziert via TCP auf Port **3691** mit dem STS-Server.

| Schritt | Nachricht |
|---|---|
| Server → Plugin | `<status code='300'>` — Registrierung erforderlich |
| Plugin → Server | `<register name='STSZZA' autor='…' version='0.1' protokoll='1' text='…' />` |
| Server → Plugin | `<status code='220'>` — Verbindung aktiv |

---

## Lizenz

MIT
