from __future__ import annotations

import logging
import socket
import threading
import xml.etree.ElementTree as ET
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from .models import (
    AnlagenInfo,
    BahnsteigInfo,
    EreignisArt,
    FahrplanZeile,
    ZugDetails,
    ZugFahrplan,
)
from .parser import STSStreamParser

logger = logging.getLogger(__name__)

PLUGIN_NAME = "STSZZA"
PLUGIN_AUTHOR = "krapas170"
PLUGIN_VERSION = "0.1"
PLUGIN_PROTOCOL = "1"
PLUGIN_DESC = "Zugzielanzeiger fuer StellwerkSim"


class STSClient(QObject):
    """
    Manages the TCP connection to the STS simulator on port 3691.

    Socket I/O runs in a daemon background thread.
    Parsed data is emitted as Qt signals so the GUI thread can
    receive it safely via Qt's queued connection mechanism.
    """

    connected = pyqtSignal()
    disconnected = pyqtSignal(str)

    sig_status = pyqtSignal(int, str)
    sig_anlageninfo = pyqtSignal(object)
    sig_bahnsteigliste = pyqtSignal(list)
    sig_zugliste = pyqtSignal(dict)
    sig_zugdetails = pyqtSignal(int, object)
    sig_zugfahrplan = pyqtSignal(int, object)
    sig_ereignis = pyqtSignal(str, object)

    def __init__(self, host: str = "localhost", port: int = 3691, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._registered = False

    # ------------------------------------------------------------------
    # Connection control
    # ------------------------------------------------------------------

    def connect_to_sim(self) -> None:
        """Start the background connection thread. Safe to call repeatedly."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._registered = False
        self._thread = threading.Thread(target=self._run, name="sts-socket", daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Request methods (called from GUI thread)
    # ------------------------------------------------------------------

    def request_anlageninfo(self) -> None:
        self._send("<anlageninfo />\n")

    def request_bahnsteigliste(self) -> None:
        self._send("<bahnsteigliste />\n")

    def request_zugliste(self) -> None:
        self._send("<zugliste />\n")

    def request_zugdetails(self, zid: int) -> None:
        self._send(f"<zugdetails zid='{zid}' />\n")

    def request_zugfahrplan(self, zid: int) -> None:
        self._send(f"<zugfahrplan zid='{zid}' />\n")

    def request_ereignis(self, zid: int, art: EreignisArt) -> None:
        self._send(f"<ereignis zid='{zid}' art='{art.value}' />\n")

    # ------------------------------------------------------------------
    # Internal — background thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        reason = "Connection closed"
        try:
            self._sock = socket.create_connection((self._host, self._port), timeout=10)
            self._sock.settimeout(None)
            parser = STSStreamParser(self._on_element)
            while self._running:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                parser.feed(chunk)
        except OSError as exc:
            reason = str(exc)
            logger.error("Socket error: %s", exc)
        finally:
            self._running = False
            self.disconnected.emit(reason)

    def _on_element(self, elem: ET.Element) -> None:
        """Called from background thread — dispatches to Qt signals."""
        self._dispatch(elem)

    def _send(self, xml: str) -> None:
        if self._sock and self._running:
            try:
                self._sock.sendall(xml.encode("utf-8"))
            except OSError as exc:
                logger.error("Send error: %s", exc)

    def _send_register(self) -> None:
        xml = (
            f"<register name='{PLUGIN_NAME}' autor='{PLUGIN_AUTHOR}' "
            f"version='{PLUGIN_VERSION}' protokoll='{PLUGIN_PROTOCOL}' "
            f"text='{PLUGIN_DESC}' />\n"
        )
        self._send(xml)

    # ------------------------------------------------------------------
    # Internal — element dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, elem: ET.Element) -> None:
        tag = elem.tag

        if tag == "status":
            code = int(elem.get("code", "0"))
            text = elem.text or elem.get("text", "")
            self.sig_status.emit(code, text)
            if code == 300 and not self._registered:
                self._send_register()
            elif code == 220:
                self._registered = True
                self.connected.emit()

        elif tag == "anlageninfo":
            info = AnlagenInfo(
                name=elem.get("name", ""),
                aid=int(elem.get("aid", "0")),
                simbuild=elem.get("simbuild", ""),
                region=elem.get("region", ""),
                online=elem.get("online", "False").lower() == "true",
            )
            self.sig_anlageninfo.emit(info)

        elif tag == "bahnsteigliste":
            result = []
            for b in elem.findall("bahnsteig"):
                nachbarn = {n.get("name", "") for n in b.findall("n")}
                hp_raw = b.get("haltepunkt", "")
                result.append(BahnsteigInfo(
                    name=b.get("name", ""),
                    nachbarn=nachbarn,
                    haltepunkt=hp_raw.lower() in ("true", "1"),
                ))
            self.sig_bahnsteigliste.emit(result)

        elif tag == "zugliste":
            zl = {}
            for z in elem.findall("zug"):
                zid_str = z.get("zid")
                name = z.get("name", "")
                if zid_str is not None:
                    zl[int(zid_str)] = name
            self.sig_zugliste.emit(zl)

        elif tag == "zugdetails":
            zid_str = elem.get("zid")
            if zid_str is None:
                return
            zid = int(zid_str)
            if zid < 0:
                return
            details = ZugDetails(
                zid=zid,
                name=elem.get("name", ""),
                verspaetung=int(elem.get("verspaetung", "0")),
                gleis=elem.get("gleis", ""),
                plangleis=elem.get("plangleis", ""),
                von=elem.get("von", ""),
                nach=elem.get("nach", ""),
                sichtbar=elem.get("sichtbar", "True").lower() == "true",
                amgleis=elem.get("amgleis", "False").lower() == "true",
                usertext=elem.get("usertext", ""),
                hinweistext=elem.get("hinweistext", ""),
            )
            self.sig_zugdetails.emit(zid, details)

        elif tag == "zugfahrplan":
            zid_str = elem.get("zid")
            if zid_str is None:
                return
            zid = int(zid_str)
            plan = ZugFahrplan(zid=zid)
            from ..utils.time_utils import hhmm_to_ms
            for gl in elem.findall("gleis"):
                plan.zeilen.append(FahrplanZeile(
                    plan=gl.get("plan", ""),
                    name=gl.get("name", ""),
                    an=hhmm_to_ms(gl.get("an")),
                    ab=hhmm_to_ms(gl.get("ab")),
                    flags=gl.get("flags", ""),
                    hinweistext=gl.get("hinweistext", ""),
                ))
            self.sig_zugfahrplan.emit(zid, plan)

        elif tag == "ereignis":
            art_str = elem.get("art", "")
            zid_str = elem.get("zid")
            if zid_str is None:
                return
            zid = int(zid_str)
            details = ZugDetails(
                zid=zid,
                name=elem.get("name", ""),
                verspaetung=int(elem.get("verspaetung", "0")),
                gleis=elem.get("gleis", ""),
                plangleis=elem.get("plangleis", ""),
                von=elem.get("von", ""),
                nach=elem.get("nach", ""),
            )
            self.sig_ereignis.emit(art_str, details)
