from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Callable

logger = logging.getLogger(__name__)

ParseCallback = Callable[[ET.Element], None]


class STSStreamParser:
    """
    Parses the STS continuous XML element stream.

    STS sends bare top-level XML elements without a document root.
    We wrap the stream in a synthetic <stream> root so that
    XMLPullParser can work incrementally on arbitrary TCP chunks.
    """

    def __init__(self, on_element: ParseCallback) -> None:
        self._on_element = on_element
        self._parser = ET.XMLPullParser(events=["end"])
        self._parser.feed(b"<stream>")

    def feed(self, data: bytes) -> None:
        """Feed raw bytes received from the TCP socket."""
        try:
            self._parser.feed(data)
            self._drain()
        except ET.ParseError as exc:
            logger.error("XML parse error: %s — data: %r", exc, data[:200])

    def _drain(self) -> None:
        for _event, elem in self._parser.read_events():
            if elem.tag == "stream":
                continue
            try:
                self._on_element(elem)
            except Exception:
                logger.exception("Error in element callback for <%s>", elem.tag)
            finally:
                elem.clear()
