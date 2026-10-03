"""TEST 003/004: part search and connector inspection."""

from server.fritzing import parts


def test_search_uno():
    results = parts.search_parts("Arduino Uno", limit=5)
    assert any("Uno" in r["title"] for r in results)


def test_search_limit():
    results = parts.search_parts("resistor", limit=50)
    assert len(results) <= 50


def test_get_part():
    part = parts.get_part("arduino_Uno_Rev3(fix)")
    assert part["title"].startswith("Arduino Uno")
    assert part["connectors"]


def test_connector_table():
    connectors = parts.get_connectors("DS18B20_fixed")
    names = {c["name"] for c in connectors}
    assert {"GND", "DQ", "VDD"} <= names


def test_get_unknown_part():
    import server.errors

    try:
        parts.get_part("nonexistent-part-xyz")
        assert False, "expected McpError"
    except server.errors.McpError as e:
        assert e.code == "PART_NOT_FOUND"
