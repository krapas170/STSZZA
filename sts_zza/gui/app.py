from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..config.station_config import StationConfig
from ..logic.train_manager import ZugManager
from ..protocol.client import STSClient
from .main_window import ZZAMainWindow

logger = logging.getLogger(__name__)

_RETRY_INTERVAL_MS = 5_000    # 5 Sekunden zwischen Verbindungsversuchen
_RETRY_TIMEOUT_MS  = 300_000  # 5 Minuten maximale Wartezeit


def run_app(host: str = "localhost", port: int = 3691) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("STSZZA")
    app.setApplicationVersion("0.1")

    client = STSClient(host=host, port=port)
    placeholder_config = StationConfig(station_name="")
    zug_manager = ZugManager(config=placeholder_config)
    window = ZZAMainWindow(client, placeholder_config, zug_manager)
    window.show()

    # ------------------------------------------------------------------
    # Reconnect-Logik
    # ------------------------------------------------------------------
    elapsed_ms = 0
    connected_once = False

    retry_timer = QTimer()
    retry_timer.setInterval(_RETRY_INTERVAL_MS)

    def attempt_connect() -> None:
        nonlocal elapsed_ms
        if connected_once:
            retry_timer.stop()
            return

        elapsed_ms += _RETRY_INTERVAL_MS
        remaining = (_RETRY_TIMEOUT_MS - elapsed_ms) // 1000
        window.set_status(
            f"Keine Verbindung — bitte ein Modul in StellwerkSim laden … "
            f"(nächster Versuch in 5 s, noch {remaining} s)"
        )
        logger.info("Reconnect attempt (%d s elapsed)", elapsed_ms // 1000)
        client.connect_to_sim()

        if elapsed_ms >= _RETRY_TIMEOUT_MS:
            retry_timer.stop()
            window.set_status(
                "Verbindung fehlgeschlagen — bitte das Plugin neu starten.")
            QMessageBox.critical(
                window,
                "Verbindung fehlgeschlagen",
                "StellwerkSim konnte nach 5 Minuten nicht erreicht werden.\n\n"
                "Bitte ein Modul in StellwerkSim laden und das Plugin neu starten.",
            )

    retry_timer.timeout.connect(attempt_connect)

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def on_anlageninfo(info) -> None:
        nonlocal connected_once
        connected_once = True
        retry_timer.stop()

        real_config = StationConfig.load_or_create(info.name)
        zug_manager._config = real_config
        window.set_config(real_config)

        if not real_config.config_path.exists():
            real_config.save()
            logger.info("Created new config skeleton for '%s'", info.name)

    client.sig_anlageninfo.connect(on_anlageninfo)

    def on_disconnected(reason: str) -> None:
        logger.warning("Disconnected: %s", reason)
        if not connected_once and not retry_timer.isActive():
            window.set_status(
                "Keine Verbindung — bitte ein Modul in StellwerkSim laden …")
            retry_timer.start()

    client.disconnected.connect(on_disconnected)
    client.connect_to_sim()

    return app.exec()
