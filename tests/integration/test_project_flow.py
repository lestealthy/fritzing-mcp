"""Project lifecycle + wiring rules (feature tests 002-015, golden circuits)."""

import pytest

from server.config import config
from server.errors import McpError
from server.fritzing import parts, sketch, validation
from server.storage import projects


@pytest.fixture()
def project():
    info = projects.create_project("pytest_led", "test project")
    pid = info["project_id"]
    pdir = projects.get_project_dir(pid)
    manifest = sketch.load_manifest(pdir)
    return pid, pdir, manifest


def _place(manifest, part_id, title, x=0, y=0):
    part = parts.get_part(part_id)
    return sketch.add_instance(manifest, part_id, title, "breadboard", x, y, 0, part["trust"])


def test_create_project(project):
    pid, pdir, manifest = project
    assert pid.startswith("WTL-FZ-")
    assert (pdir / "project.json").is_file()


def test_place_part(project):
    pid, pdir, manifest = project
    inst = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    sketch.save_manifest(pdir, manifest)
    assert inst["instance_id"] == "inst_0001"


def test_wire_valid(project):
    pid, pdir, manifest = project
    a = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    b = _place(manifest, "DS18B20_fixed", "DS18B20")
    conn = sketch.add_connection(manifest, a["instance_id"], "connector87", b["instance_id"], "connector3")
    assert conn["connection_id"] == "wire_0001"
    sketch.save_manifest(pdir, manifest)


def test_wire_nonexistent_connector(project):
    pid, pdir, manifest = project
    a = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    b = _place(manifest, "DS18B20_fixed", "DS18B20")
    with pytest.raises(McpError) as ei:
        sketch.add_connection(manifest, a["instance_id"], "connector999", b["instance_id"], "connector3")
    assert ei.value.code == "CONNECTOR_NOT_FOUND"


def test_wire_nonexistent_instance(project):
    pid, pdir, manifest = project
    with pytest.raises(McpError) as ei:
        sketch.add_connection(manifest, "inst_9999", "connector0", "inst_8888", "connector0")
    assert ei.value.code == "INSTANCE_NOT_FOUND"


def test_duplicate_wire_rejected(project):
    pid, pdir, manifest = project
    a = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    b = _place(manifest, "DS18B20_fixed", "DS18B20")
    sketch.add_connection(manifest, a["instance_id"], "connector87", b["instance_id"], "connector3")
    with pytest.raises(McpError) as ei:
        sketch.add_connection(manifest, a["instance_id"], "connector87", b["instance_id"], "connector3")
    assert ei.value.code == "DUPLICATE_CONNECTION"


def test_power_conflict_detected():
    info = projects.create_project("pytest_power", "conflict")
    pdir = projects.get_project_dir(info["project_id"])
    manifest = sketch.load_manifest(pdir)
    a = _place(manifest, "arduino_Uno_Rev3(fix)", "A")
    b = _place(manifest, "arduino_Uno_Rev3(fix)", "B")
    sketch.add_connection(manifest, a["instance_id"], "connector46", b["instance_id"], "connector86")  # 5V -> 3V3
    result = validation.run_validation(pdir, manifest)
    assert result["status"] == "FAIL"
    assert any(e["code"] == "POWER_CONFLICT" for e in result["errors"])


def test_missing_ground_warning(project):
    pid, pdir, manifest = project
    a = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    b = _place(manifest, "DS18B20_fixed", "DS18B20")
    sketch.add_connection(manifest, a["instance_id"], "connector87", b["instance_id"], "connector3")
    result = validation.run_validation(pdir, manifest)
    codes = {w["code"] for w in result["warnings"]}
    assert "MISSING_GROUND" in codes or "MISSING_POWER" in codes


def test_save_requires_validation(project):
    pid, pdir, manifest = project
    _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    sketch.save_manifest(pdir, manifest)
    with pytest.raises(McpError) as ei:
        projects.save_project(pid)
    assert ei.value.code == "SAVE_DENIED"


def test_led_golden_project():
    info = projects.create_project("golden_led", "golden LED")
    pdir = projects.get_project_dir(info["project_id"])
    manifest = sketch.load_manifest(pdir)
    uno = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    res = _place(manifest, "ResistorModuleID", "R1")
    led = _place(manifest, "805RedLEDModuleID", "LED")
    sketch.add_connection(manifest, uno["instance_id"], "connector64", res["instance_id"], "connector0")
    sketch.add_connection(manifest, res["instance_id"], "connector1", led["instance_id"], "connector1")
    sketch.add_connection(manifest, led["instance_id"], "connector0", uno["instance_id"], "connector88")
    sketch.save_manifest(pdir, manifest)
    fzz = sketch.pack_fzz(pdir, manifest)
    result = validation.run_validation(pdir, manifest)
    assert result["status"] in ("PASS", "PASS_WITH_WARNINGS")
    assert fzz.is_file()
    if manifest.get("state") in ("WIRED", "PLACED"):
        manifest["state"] = "VALIDATED"
    elif manifest.get("state") == "CREATED":
        manifest["state"] = "VALIDATED"
    sketch.save_manifest(pdir, manifest)
    saved = projects.save_project(info["project_id"])
    assert saved["status"] in ("verified", "verified_with_warnings")


def test_sensor_golden_project():
    info = projects.create_project("golden_sensor", "golden sensor")
    pdir = projects.get_project_dir(info["project_id"])
    manifest = sketch.load_manifest(pdir)
    uno = _place(manifest, "arduino_Uno_Rev3(fix)", "Uno")
    ds = _place(manifest, "DS18B20_fixed", "DS18B20")
    sketch.add_connection(manifest, uno["instance_id"], "connector87", ds["instance_id"], "connector3")
    sketch.add_connection(manifest, uno["instance_id"], "connector88", ds["instance_id"], "connector1")
    sketch.add_connection(manifest, uno["instance_id"], "connector64", ds["instance_id"], "connector2")
    sketch.save_manifest(pdir, manifest)
    sketch.pack_fzz(pdir, manifest)
    result = validation.run_validation(pdir, manifest)
    assert result["status"] == "PASS", result
