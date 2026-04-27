from __future__ import annotations

import codecs
import logging
import re
import xml.etree.ElementTree as ET
from typing import Callable

logger = logging.getLogger(__name__)

ParseCallback = Callable[[ET.Element], None]

# STS schickt teilweise einen <?xml … encoding="ISO-8859-1" ?>-Prolog,
# obwohl die tatsächlichen Bytes UTF-8-kodiert sind. Wenn wir die Bytes
# direkt an expat geben, befolgt es die Deklaration und produziert
# Mojibake (z. B. „Hält" → „HÃ¤lt"). Wir dekodieren deshalb selbst zu
# Unicode-Strings und entfernen XML-Deklarationen aus dem Stream — bei
# str-Input ignoriert expat sie ohnehin, der Vollständigkeit halber.
_XML_DECL_RE = re.compile(r"<\?xml\b[^?]*\?>")


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
        # Inkrementeller UTF-8-Decoder — fängt Multibyte-Zeichen ab, die
        # über die TCP-Chunk-Grenze hinweg zerrissen werden ("ä" = c3 a4
        # könnte z. B. mit c3 in Chunk 1 und a4 in Chunk 2 ankommen).
        # `errors="replace"` schluckt seltene Fehl-Bytes lieber, als den
        # ganzen Stream sterben zu lassen.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._parser.feed("<stream>")
        self._drain()

    def feed(self, data: bytes) -> None:
        """Feed raw bytes received from the TCP socket."""
        try:
            text = self._decoder.decode(data)
            # XML-Deklarationen mitten im Stream rauswerfen — sie würden
            # XMLPullParser mit str zwar nicht stören, sehen aber im Log
            # bei einem ParseError wenigstens nach echtem Inhalt aus.
            text = _XML_DECL_RE.sub("", text)
            if text:
                self._parser.feed(text)
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
