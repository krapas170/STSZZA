import tempfile
from pathlib import Path
from unittest.mock import patch

from sts_zza.config.station_config import StationConfig, ZugEintrag, ENCODING


def _make_config_in(tmp_dir: Path, station: str) -> StationConfig:
    with patch("sts_zza.config.station_config.CONFIGS_DIR", tmp_dir):
        cfg = StationConfig(station_name=station)
        return cfg


def test_save_creates_file(tmp_path):
    with patch("sts_zza.config.station_config.CONFIGS_DIR", tmp_path):
        cfg = StationConfig(station_name="TestBahnhof")
        cfg.bahnsteige = ["1", "2"]
        cfg.zuege["IC 100"] = ZugEintrag(
            name="IC 100", von="A-Stadt", nach="B-Hausen", plangleis="1"
        )
        cfg.save()

    saved = tmp_path / "TestBahnhof.xml"
    assert saved.exists()
    content = saved.read_text(encoding=ENCODING)
    assert 'encoding="ISO-8859-1"' in content
    assert 'station="TestBahnhof"' in content
    assert 'name="IC 100"' in content
    assert 'name="1"' in content


def test_load_roundtrip(tmp_path):
    with patch("sts_zza.config.station_config.CONFIGS_DIR", tmp_path):
        cfg = StationConfig(station_name="RoundtripTest")
        cfg.bahnsteige = ["3", "4"]
        cfg.zuege["RE 42"] = ZugEintrag(
            name="RE 42", von="Start", nach="Ziel",
            via=["Mitte"], plangleis="3"
        )
        cfg.save()

        loaded = StationConfig.load_or_create("RoundtripTest")

    assert loaded.bahnsteige == ["3", "4"]
    assert "RE 42" in loaded.zuege
    entry = loaded.zuege["RE 42"]
    assert entry.von == "Start"
    assert entry.nach == "Ziel"
    assert entry.via == ["Mitte"]
    assert entry.plangleis == "3"


def test_load_or_create_missing(tmp_path):
    with patch("sts_zza.config.station_config.CONFIGS_DIR", tmp_path):
        cfg = StationConfig.load_or_create("Nonexistent")
    assert cfg.station_name == "Nonexistent"
    assert cfg.bahnsteige == []
    assert cfg.zuege == {}
