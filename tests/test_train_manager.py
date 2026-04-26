from sts_zza.config.station_config import StationConfig, ZugEintrag
from sts_zza.logic.train_manager import ZugManager
from sts_zza.protocol.models import ZugDetails


def _make_details(zid: int, name: str, plangleis: str = "1") -> ZugDetails:
    return ZugDetails(zid=zid, name=name, plangleis=plangleis, von="A", nach="B")


def test_new_train_goes_to_capture_list():
    config = StationConfig(station_name="Test")
    mgr = ZugManager(config)
    mgr.update_details(1, _make_details(1, "IC 100"))
    assert "IC 100" in mgr.get_capture_list()


def test_known_train_not_in_capture_list():
    config = StationConfig(station_name="Test")
    config.zuege["RE 42"] = ZugEintrag(name="RE 42", plangleis="2")
    mgr = ZugManager(config)
    mgr.update_details(2, _make_details(2, "RE 42", plangleis="2"))
    assert "RE 42" not in mgr.get_capture_list()


def test_plangleis_from_config_overrides_live(tmp_path):
    config = StationConfig(station_name="Test")
    config.zuege["IC 999"] = ZugEintrag(name="IC 999", plangleis="5")
    mgr = ZugManager(config)
    mgr.update_details(3, _make_details(3, "IC 999", plangleis="7"))
    assert mgr.get_plangleis_for_display(3) == "5"


def test_plangleis_fallback_to_live():
    config = StationConfig(station_name="Test")
    mgr = ZugManager(config)
    mgr.update_details(4, _make_details(4, "ALX 123", plangleis="3"))
    assert mgr.get_plangleis_for_display(4) == "3"
