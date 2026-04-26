import xml.etree.ElementTree as ET
from sts_zza.protocol.parser import STSStreamParser


def _collect_elements(chunks: list[bytes]) -> list[ET.Element]:
    results = []
    parser = STSStreamParser(on_element=results.append)
    for chunk in chunks:
        parser.feed(chunk)
    return results


def test_single_element():
    elems = _collect_elements([b"<anlageninfo name='Testbahnhof' aid='1' />"])
    assert len(elems) == 1
    assert elems[0].tag == "anlageninfo"
    assert elems[0].get("name") == "Testbahnhof"


def test_chunked_element():
    elems = _collect_elements([b"<anlagen", b"info name='X' />"])
    assert len(elems) == 1
    assert elems[0].tag == "anlageninfo"


def test_multiple_elements():
    elems = _collect_elements([
        b"<status code='300' />",
        b"<anlageninfo name='Y' aid='2' />",
    ])
    assert len(elems) == 2
    assert elems[0].tag == "status"
    assert elems[1].tag == "anlageninfo"


def test_nested_element():
    xml = b"<bahnsteigliste><bahnsteig name='1' haltepunkt='true' /></bahnsteigliste>"
    elems = _collect_elements([xml])
    assert len(elems) == 1
    assert elems[0].tag == "bahnsteigliste"
    assert elems[0].find("bahnsteig") is not None
