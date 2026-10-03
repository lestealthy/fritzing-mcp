"""TEST 001: Fritzing installation detected."""

from server.fritzing.installation import detect_fritzing, detect_parts, run_doctor


def test_fritzing_detected():
    f = detect_fritzing()
    assert f["installed"] is True
    assert f["exe"].endswith("Fritzing.exe")


def test_parts_detected():
    p = detect_parts()
    assert p["available"] is True
    assert p["part_count"] and p["part_count"] > 1000


def test_doctor_report_has_all_checks():
    report = run_doctor()["report"]
    for needle in ["Fritzing", "Version", "Parts repository", "User parts",
                   "writable", "Renderer", "FZP checker", "MCP"]:
        assert needle.lower() in report.lower()
