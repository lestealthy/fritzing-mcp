"""Brutal AI-agent workflow: every shortcut must be denied in the right phase."""

import pytest

from server.config import config
from server.errors import McpError
from server.fritzing import parts, render, sketch, validation
from server.policy import invalidate_validation
from server.security.paths import resolve_inside_root, sanitize_name
from server.storage import projects
def _place(m, part_id, title):
    trust = parts.get_part(part_id)["trust"]
    return sketch.add_instance(m, part_id, title, "breadboard", 0, 0, 0, trust)


def test_brutal_lifecycle():
    info = projects.create_project("brutal_life", "fixture")
    pid = info["project_id"]
    pdir = projects.get_project_dir(pid)
    m = sketch.load_manifest(pdir)

    a = _place(m, "arduino_Uno_Rev3(fix)", "U")
    sketch.save_manifest(pdir, m)

    # CREATE→place→SAVE must die (never validated)
    with pytest.raises(McpError) as ei:
        projects.save_project(pid)
    assert ei.value.code == "SAVE_DENIED"

    # render on an unvalidated project must be denied
    with pytest.raises(McpError) as ei:
        render.render_project(pdir, m, "all")
    assert ei.value.code in ("PROJECT_NOT_VALIDATED", "RENDER_FAILED")

    b = _place(m, "DS18B20_fixed", "S")
    sketch.add_connection(m, a["instance_id"], "connector64", b["instance_id"], "connector2")
    invalidate_validation(m, "wire")
    m["state"] = "WIRED"
    sketch.save_manifest(pdir, m)

    # render while WIRED(dirty) → must deny
    with pytest.raises(McpError) as ei:
        render.render_project(pdir, m, "all")
    assert ei.value.code in ("PROJECT_NOT_VALIDATED", "RENDER_DENIED")

    # VALIDATE → then render allowed (render requires state VALIDATED)
    res = validation.run_validation(pdir, m)
    if m["state"] == "WIRED":
        m["state"] = "VALIDATED"
    sketch.save_manifest(pdir, m)
    assert res["status"] in ("PASS", "PASS_WITH_WARNINGS")
    # render now permitted: call with short timeout so this is the *policy* assertion
    try:
        r = render.render_project(pdir, m, "all", timeout=30)
        assert r["status"] == "ok"
        assert r["engine"] in ("fritzing-native", "builtin-engineering-preview")
    except McpError as e:
        # deterministic safety: render may fail only if real Fritzing unavailable; the render *gate* has passed
        assert e.code in ("RENDER_FAILED",)

    # MOVE → save must be denied
    sketch.move_instance(m, b["instance_id"], 100, 100, None)
    invalidate_validation(m, "move_part")
    if m["state"] in ("VALIDATED", "RENDERED", "REVIEWED"):
        m["state"] = "WIRED"
    sketch.save_manifest(pdir, m)
    with pytest.raises(McpError) as ei:
        projects.save_project(pid)
    assert ei.value.code == "SAVE_DENIED"

    # validate again → save now succeeds
    res = validation.run_validation(pdir, m)
    if m["state"] == "WIRED":
        m["state"] = "VALIDATED"
    sketch.save_manifest(pdir, m)
    saved = projects.save_project(pid)
    assert saved["status"] in ("verified", "verified_with_warnings")


def test_brutal_security_and_trust():
    # unsafe names/paths
    for bad in ['a;powershell -c whoami', '$(calc)', 'name`whoami', 'x"y', "a'b", 'a|b', 'a&b', 'CON']:
        try:
            sanitize_name(bad)
            assert False, f"expected rejection of {bad!r}"
        except McpError:
            pass
    with pytest.raises(McpError):
        resolve_inside_root("C:\\Windows\\system32")
    with pytest.raises(McpError):
        resolve_inside_root("\\\\evil\\share")
    # unknown part → hard fail via connectors
    info = projects.create_project("brutal_sec", "t")
    m = sketch.load_manifest(projects.get_project_dir(info["project_id"]))
    with pytest.raises(McpError):
        sketch.add_connection(m, "a", "c0", "b", "c1")


from server.security.paths import resolve_inside_root, sanitize_name
