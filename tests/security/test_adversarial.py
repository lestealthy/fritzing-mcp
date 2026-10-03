"""Adversarial agent tests."""

import io, zipfile

import pytest

from server.config import config
from server.errors import McpError
from server.fritzing import parts, render, sketch, validation
from server.policy import invalidate_validation
from server.security.paths import resolve_inside_root, sanitize_name
from server.storage import projects


def test_powershell_injection_via_project_name():
    with pytest.raises(McpError):
        sanitize_name("x;powershell -c whoami")
    with pytest.raises(McpError):
        sanitize_name("$(calc)")


def test_windows_system32_absolute_path_blocked():
    with pytest.raises(McpError) as ei:
        resolve_inside_root(r"C:\Windows\System32\drivers\etc\hosts")
    assert ei.value.code == "PATH_NOT_ALLOWED"


def test_unc_blocked():
    with pytest.raises(McpError):
        resolve_inside_root(r"\\server\share\x")
    with pytest.raises(McpError):
        resolve_inside_root(r"\\?\C:\x.fzz")


def test_create_save_rejected():
    info = projects.create_project("adv_create_save", "t")
    with pytest.raises(McpError) as ei:
        projects.save_project(info["project_id"])
    assert ei.value.code == "SAVE_DENIED"


def _wire_one(pid):
    pdir = projects.get_project_dir(pid)
    m = sketch.load_manifest(pdir)
    a = sketch.add_instance(m, "arduino_Uno_Rev3(fix)", "U", "breadboard", 0, 0, 0, "OFFICIAL")
    b = sketch.add_instance(m, "DS18B20_fixed", "D", "breadboard", 400, 0, 0, "OFFICIAL")
    sketch.add_connection(m, a["instance_id"], "connector87", b["instance_id"], "connector3")
    invalidate_validation(m, "wire")
    m["state"] = "WIRED"
    sketch.save_manifest(pdir, m)
    return pdir, m


def test_place_save_rejected():
    info = projects.create_project("adv_place_save", "t")
    pdir = projects.get_project_dir(info["project_id"])
    m = sketch.load_manifest(pdir)
    sketch.add_instance(m, "arduino_Uno_Rev3(fix)", "U", "breadboard", 0, 0, 0, "OFFICIAL")
    sketch.save_manifest(pdir, m)
    with pytest.raises(McpError):
        projects.save_project(info["project_id"])


def test_wire_save_rejected():
    info = projects.create_project("adv_wire_save", "t")
    pdir, m = _wire_one(info["project_id"])
    with pytest.raises(McpError):
        projects.save_project(info["project_id"])


def test_validate_mutate_save_blocked():
    info = projects.create_project("adv_vm_save", "t")
    pdir, m = _wire_one(info["project_id"])
    result = validation.run_validation(pdir, m)
    sketch.save_manifest(pdir, m)
    assert result["status"] in ("PASS", "PASS_WITH_WARNINGS")
    # mutate: move
    sketch.move_instance(m, m["parts"][0]["instance_id"], 50, 50, None)
    invalidate_validation(m, "move_part")
    sketch.save_manifest(pdir, m)
    with pytest.raises(McpError) as ei:
        projects.save_project(info["project_id"])
    assert ei.value.code == "SAVE_DENIED"


def test_render_rejected_before_validation_state_machine():
    info = projects.create_project("adv_render", "t")
    pdir, m = _wire_one(info["project_id"])
    m["state"] = "WIRED"
    m["dirty"] = True
    sketch.save_manifest(pdir, m)
    with pytest.raises(McpError) as ei:
        render.render_project(pdir, m, "schematic")
    assert ei.value.code in ("PROJECT_NOT_VALIDATED", "RENDER_DENIED")


def test_overwrite_other_project_blocked():
    i1 = projects.create_project("adv_src", "t")
    i2 = projects.create_project("adv_dst", "t")
    # force destination conflict
    dst = config.projects_completed / i2["project_id"]
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "x.txt").write_text("x")
    pdir = projects.get_project_dir(i1["project_id"])
    m = sketch.load_manifest(pdir)
    (m := m)["artifacts"]["fzz"] = str(pdir / "circuit.fzz")
    validation.run_validation(pdir, m)
    m2 = sketch.load_manifest(pdir)
    try:
        projects.save_project(i1["project_id"])
    except McpError as ei:
        assert ei.code in ("SAVE_DENIED", "POLICY_DENIED")


def test_unknown_part_trust_denied_placement():
    info = projects.create_project("adv_trust", "t")
    pdir = projects.get_project_dir(info["project_id"])
    m = sketch.load_manifest(pdir)
    # a part id not in DB is rejected when resolving connectors
    m2 = sketch.load_manifest(projects.get_project_dir(info["project_id"]))
    with pytest.raises(McpError):
        sketch.add_connection(m2, "a", "c0", "b", "c1")


def test_malicious_zip_traversal_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../evil.fz", "<x/>")
    fzz = tmp_path / "evil.fzz"
    fzz.write_bytes(buf.getvalue())
    with pytest.raises(McpError):
        sketch.safe_extract_fzz(fzz, tmp_path / "out")


def test_malicious_zip_absolute_windows_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("C:\\Windows\\evil.fzp", "<x/>")
    fzz = tmp_path / "evil2.fzz"
    fzz.write_bytes(buf.getvalue())
    with pytest.raises(McpError):
        sketch.safe_extract_fzz(fzz, tmp_path / "out2")


def test_zip_bomb_rejected(tmp_path):
    import server.policy

    big = tmp_path / "big.fzz"
    with zipfile.ZipFile(big, "w") as z:
        z.writestr("circuit.fz", b"x" * 500)
    # loosen total limit to test path for size
    import server.fritzing.sketch as sk
    orig = server.policy.load_policy
    server.policy._policy_cache = {"zip": {"max_files": 1, "max_total_bytes": 100, "max_member_bytes": 5000}}
    try:
        with pytest.raises(McpError):
            sketch.safe_extract_fzz(big, tmp_path / "out3")
    finally:
        server.policy.reload_policy()


def test_fcccations_no_absolute_paths_in_fz():
    info = projects.create_project("adv_fzz_paths", "t")
    pdir, m = _wire_one(info["project_id"])
    validation.run_validation(pdir, m)
    sketch.save_manifest(pdir, m)
    fzz = sketch.pack_fzz(pdir, m)
    with zipfile.ZipFile(fzz) as z:
        fz = z.read("circuit.fz").decode()
    assert "C:\\\\" not in fz and "Programs\\\\Fritzing" not in fz
    assert 'path="wire.fzp"' in fz


def test_artifacts_fz_not_fzz():
    info = projects.create_project("adv_artifacts", "t")
    pdir, m = _wire_one(info["project_id"])
    sketch.pack_fzz(pdir, m)
    assert m["artifacts"]["fz"].endswith(".fz")
    assert m["artifacts"]["fzz"].endswith(".fzz")
    assert m["artifacts"]["fz"] != m["artifacts"]["fzz"]
    from pathlib import Path

    assert Path(m["artifacts"]["fz"]).is_file()
    assert Path(m["artifacts"]["fzz"]).is_file()
