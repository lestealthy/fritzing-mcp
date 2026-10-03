"""Render test: real Fritzing headless SVG export for a golden project."""

import pytest

from server.fritzing import parts, render, sketch, validation
from server.storage import projects


def test_render_led_golden():
    info = projects.create_project("render_led", "render test")
    pdir = projects.get_project_dir(info["project_id"])
    manifest = sketch.load_manifest(pdir)
    uno = sketch.add_instance(manifest, "arduino_Uno_Rev3(fix)", "Uno", "breadboard", 100, 100, 0, "OFFICIAL")
    res = sketch.add_instance(manifest, "ResistorModuleID", "R1", "breadboard", 500, 100, 0, "OFFICIAL")
    manifest["state"] = "PLACED"
    sketch.add_connection(manifest, uno["instance_id"], "connector64", res["instance_id"], "connector0")
    manifest["state"] = "WIRED"
    sketch.save_manifest(pdir, manifest)
    sketch.pack_fzz(pdir, manifest)
    validation.run_validation(pdir, manifest)
    if manifest.get("state") == "WIRED":
        manifest["state"] = "VALIDATED"
    sketch.save_manifest(pdir, manifest)
    result = render.render_project(pdir, manifest, "all", timeout=45)
    assert result["status"] == "ok"
    assert result["svgs"]
