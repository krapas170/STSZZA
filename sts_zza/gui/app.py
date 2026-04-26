from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from ..config.station_config import StationConfig
from ..protocol.client import STSClient
from .main_window import ZZAMainWindow

logger = logging.getLogger(__name__)


def run_app(host: str = "localhost", port: int = 3691) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("STSZZA")
    app.setApplicationVersion("0.1")

    client = STSClient(host=host, port=port)
    placeholder_config = StationConfig(station_name="")
    window = ZZAMainWindow(client, placeholder_config)
    window.show()

    def on_anlageninfo(info) -> None:
        real_config = StationConfig.load_or_create(info.name)
        window.set_config(real_config)
        if not real_config.config_path.exists():
            real_config.save()
            logger.info("Created new config skeleton for '%s'", info.name)

    client.sig_anlageninfo.connect(on_anlageninfo)

    def on_disconnected(reason: str) -> None:
        logger.warning("Disconnected: %s", reason)
        window.set_status(f"Getrennt: {reason}")

    client.disconnected.connect(on_disconnected)
    client.connect_to_sim()

    return app.exec()
