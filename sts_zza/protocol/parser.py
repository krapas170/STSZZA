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

    Only top-level elements (direct children of <stream>) are passed to the
    callback; nested elements are kept intact so the callback can use
    elem.findall() on them.
    """

    def __init__(self, on_element: ParseCallback) -> None:
        self._on_element = on_element
        self._parser = ET.XMLPullParser(events=["start", "end"])
        self._depth = 0
        self._parser.feed(b"<stream>")
        self._drain()

    def feed(self, data: bytes) -> None:
        """Feed raw bytes received from the TCP socket."""
        try:
            self._parser.feed(data)
            self._drain()
        except ET.ParseError as exc:
            logger.error("XML parse error: %s — data: %r", exc, data[:200])

    def _drain(self) -> None:
        for event, elem in self._parser.read_events():
            if event == "start":
                self._depth += 1
            elif event == "end":
                self._depth -= 1
                if elem.tag == "stream":
                    continue
                # depth==1 means we just closed a direct child of <stream>
                if self._depth == 1:
                    try:
                        self._on_element(elem)
                    except Exception:
                        logger.exception("Error in element callback for <%s>", elem.tag)
                    finally:
                        elem.clear()
